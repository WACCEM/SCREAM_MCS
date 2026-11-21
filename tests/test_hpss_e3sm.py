"""Tests of the E3SM HPSS backup and restore: archive layout, limits, links and manifest, skipping, failures, partial restores.

htar and hsi are replaced by small programs on PATH that keep a "tape" in a temporary folder (``FAKE_HPSS``; ``/home/f/...`` maps below it), so the
scripts run end to end without HPSS (the pattern of airscape/MRMS_Processing/tests/test_hpss.py). What the real programs print was checked against HPSS
in the smoke test (docs/hpss_e3sm.md).

Run from the scream folder:  python -m pytest tests/test_hpss_e3sm.py
"""

import importlib.util
import json
import os
import stat
import sys
import textwrap
import time
from pathlib import Path

import pytest

TRACKING = Path(__file__).resolve().parents[1] / "tracking_e3sm"
sys.path.insert(0, str(TRACKING))
import hpss_e3sm_lib as H  # noqa: E402

HPSS_DIR = "/home/f/feng045/E3SM_polun"

HSI = '''#!{python}
import os, sys
root = os.environ["FAKE_HPSS"]
real = lambda p: os.path.join(root, p.lstrip("/"))
cmd = sys.argv[-1].split()
def line(path, name):
    st = os.stat(path)
    return "{{}}rwxr-x---  1 feng045 feng045 {{:>12d}} Oct 25 20:00 {{}}".format("d" if os.path.isdir(path) else "-", st.st_size if os.path.isfile(path) else 512, name)
if cmd[0] == "ls":
    p = cmd[-1]
    if not os.path.exists(real(p)):
        sys.stderr.write("*** HSI: No such file or directory: " + p + "\\n"); sys.exit(64)
    if "d" in cmd[1] or os.path.isfile(real(p)):
        print(line(real(p), p))
    else:
        print(); print(p + ":")
        for n in sorted(os.listdir(real(p))): print(line(os.path.join(real(p), n), n))
elif cmd[0] == "mkdir":
    try: os.mkdir(real(cmd[1]))
    except OSError: sys.exit(64)
elif cmd[0] == "put" and cmd[2] == ":":
    if os.environ.get("FAKE_HSI_PUT_FAIL"): sys.exit(64)
    open(real(cmd[3]), "wb").write(open(cmd[1], "rb").read())
elif cmd[0] == "get" and cmd[2] == ":":
    open(cmd[1], "wb").write(open(real(cmd[3]), "rb").read())
else:
    sys.exit(2)
'''

HTAR = '''#!{python}
import json, os, sys, tarfile
root = os.environ["FAKE_HPSS"]
real = lambda p: os.path.join(root, p.lstrip("/"))
args = sys.argv[1:]
mode = tar = lst = None; members = []; i = 0
while i < len(args):
    a = args[i]
    if a in ("-c", "-x", "-t", "-K"): mode = a[1]
    elif a == "-f": tar = args[i + 1]; i += 1
    elif a == "-M": i += 1
    elif a == "-L": lst = args[i + 1]; i += 1
    elif a.startswith("-H") or a in ("-V", "-p", "-v"): pass
    else: members.append(a)
    i += 1
with open(os.path.join(root, "_calls.log"), "a") as fh:
    fh.write(json.dumps({{"mode": mode, "tar": tar, "members": members, "cwd": os.getcwd(), "argv": args, "list": open(lst).read().split() if lst else []}}) + "\\n")
fail = os.environ.get("FAKE_HTAR_FAIL", "")
rt = real(tar)
if mode == "c":
    if not os.path.isdir(os.path.dirname(rt)):
        print("HTAR: HTAR FAILED (no such directory)"); sys.exit(70)
    names = [n for n in open(lst).read().split("\\n") if n]
    with tarfile.open(rt, "w") as t:
        for n in names: t.add(n, recursive=False)
    if fail == "create":
        print("HTAR: HTAR FAILED"); sys.exit(70)          # the tar stays, the index is never written
    open(rt + ".idx", "w").write("\\n".join(names))
    print("HTAR: HTAR SUCCESSFUL")
elif mode == "t":
    if not os.path.exists(rt + ".idx"): print("HTAR: HTAR FAILED"); sys.exit(70)
    with tarfile.open(rt) as t:
        for m in t.getmembers():
            print("HTAR: -rw-r-----  feng045/feng045  {{:>10d}} 2026-10-25 20:00  {{}}".format(m.size, m.name))
    print("HTAR: -rw-------  feng045/feng045  100 2026-10-25 20:00  /tmp/HTAR_CF_CHK_123_456")
    print("HTAR: HTAR SUCCESSFUL")
elif mode == "x":
    with tarfile.open(rt) as t:
        want = t.getmembers() if not members else [m for m in t.getmembers() if any(m.name == w or (w.endswith("/") and m.name.startswith(w)) for w in members)]
        if fail == "extract": want = want[:-1]             # one file too few arrives
        for m in want: t.extract(m, ".", filter="fully_trusted")
    print("HTAR: HTAR SUCCESSFUL")
elif mode == "K":
    if fail == "verify": print("HTAR: HTAR FAILED (CRC)"); sys.exit(65)
    print("HTAR: HTAR SUCCESSFUL")
'''


@pytest.fixture
def tape(tmp_path, monkeypatch):
    """Fake hsi/htar on PATH with a tape folder; returns an object with the tape folder, a reader of the htar call log and a path mapper."""
    bin_dir, root = tmp_path / "bin", tmp_path / "tape"
    bin_dir.mkdir()
    (root / HPSS_DIR.lstrip("/")).mkdir(parents=True)
    for name, body in (("hsi", HSI), ("htar", HTAR)):
        p = bin_dir / name
        p.write_text(textwrap.dedent(body).format(python=sys.executable))
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_HPSS", str(root))
    for var in ("FAKE_HTAR_FAIL", "FAKE_HSI_PUT_FAIL", "SLURM_JOB_QOS", "SLURM_JOB_ID"):
        monkeypatch.delenv(var, raising=False)

    def calls(mode=None):
        log = root / "_calls.log"
        rows = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
        return [r for r in rows if mode is None or r["mode"] == mode]
    return type("Tape", (), {"root": root, "calls": staticmethod(calls), "path": lambda self, p: root / p.lstrip("/")})()


def make_file(path: Path, text: str, age_days: float = 3.0) -> Path:
    """A file with the given content, made ``age_days`` old."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))
    return path


@pytest.fixture
def source(tmp_path):
    """A data root with one model folder: a production tree with links, a derived tree that links into it, an input tree, and the two folders that are left out."""
    root = tmp_path / "root"
    base = root / "ne120_remap_0.1deg"
    for y in (2009, 2010):
        for k in range(3):
            make_file(base / "mcs_tbpf" / str(y) / "mcstracking" / f"mcstrack_{y}{k:02d}.nc", f"pixel {y} {k}")
        make_file(base / "mcs_tbpf" / str(y) / "stats" / "monthly" / f"mcs_rainmap_{y}01.nc", f"map {y}")
        make_file(base / "mcs_tbpf" / str(y) / "tracking" / "2009-01" / f"cloudid_{y}0101.nc", f"cloudid {y}")
        folder = base / "mcs_tbpf" / str(y) / "tracking" / "campaign_a"
        folder.mkdir(parents=True, exist_ok=True)
        # an absolute link whose target is longer than the 99 characters that htar allows for a link name
        os.symlink(str(base / "mcs_tbpf" / str(y) / "tracking" / "2009-01" / f"cloudid_{y}0101.nc"), folder / f"cloudid_{y}0101.nc")
    (base / "mcs_tbpf" / "2009" / "empty_logs").mkdir()
    # a derived tree: its own files and links into the production tree (a link to a folder, a relative link to a file)
    make_file(base / "mcs_tbpf_hr2p0" / "2010" / "stats" / "mcs_tracks_pf.txt", "pf rows")
    os.symlink(str(base / "mcs_tbpf" / "2010" / "tracking"), base / "mcs_tbpf_hr2p0" / "2010" / "tracking")
    os.symlink("../2010/stats/mcs_tracks_pf.txt", base / "mcs_tbpf_hr2p0" / "link_to_pf.txt")
    make_file(base / "olr_pcp" / "olr_2009.nc", "olr")
    make_file(base / "quicklooks_2panel_tbpf" / "a.png", "png")
    make_file(base / "animations_2panel_tbpf" / "a.mp4", "mp4")
    return root


def script(name):
    """Load one of the scripts of tracking_e3sm as a module."""
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", TRACKING / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                     # a module that defines dataclasses must be registered before it runs
    spec.loader.exec_module(mod)
    return mod


def backup(root, *args):
    return script("hpss_e3sm_backup").main(["--root", str(root), "--hpss-dir", HPSS_DIR, "--min-age-min", "0", *args])


def restore(root, *args):
    return script("hpss_e3sm_restore").main(["--hpss-dir", HPSS_DIR, "--source-root", str(root), *args])


def tree(path: Path) -> dict:
    """Relative path -> (kind, content or link target) of everything below ``path``."""
    out = {}
    for p in sorted(path.rglob("*")):
        rel = str(p.relative_to(path))
        if p.is_symlink():
            out[rel] = ("link", os.readlink(p))
        elif p.is_file():
            out[rel] = ("file", p.read_text())
        else:
            out[rel] = ("dir", None)
    return out


# ------------------------------------------------------------------------------------------------ pure parts
def test_list_dirs_leaves_out_the_animation_and_quicklook_folders(source):
    assert H.list_dirs(source, "ne120") == ["mcs_tbpf", "mcs_tbpf_hr2p0", "olr_pcp"]
    assert "quicklooks_2panel_tbpf" in H.list_dirs(source, "ne120", exclude=())
    with pytest.raises(H.HpssError):
        H.list_dirs(source, "ne30")


def test_scan_records_links_and_empty_dirs_and_does_not_follow(source):
    base = source / "ne120_remap_0.1deg"
    scan = H.scan_directory(base, "mcs_tbpf_hr2p0")
    assert scan.members == ["mcs_tbpf_hr2p0/2010/stats/mcs_tracks_pf.txt"]            # the folder link is NOT followed: no file of mcs_tbpf
    assert dict(scan.links)["mcs_tbpf_hr2p0/2010/tracking"] == str(base / "mcs_tbpf" / "2010" / "tracking")
    assert dict(scan.links)["mcs_tbpf_hr2p0/link_to_pf.txt"] == "../2010/stats/mcs_tracks_pf.txt"
    prod = H.scan_directory(base, "mcs_tbpf")
    assert len(prod.members) == 2 * (3 + 1 + 1) and len(prod.links) == 2 and prod.empty_dirs == ["mcs_tbpf/2009/empty_logs"]
    assert max(len(t) for _, t in prod.links) > 99 and not prod.problems          # links with targets above 99 characters are no problem


def test_scan_flags_what_htar_cannot_take(source):
    base = source / "ne120_remap_0.1deg"
    make_file(base / "olr_pcp" / "x.nc.123.tmp", "t")
    make_file(base / "olr_pcp" / ("n" * 100 + ".nc"), "long")
    os.mkfifo(base / "olr_pcp" / "pipe")
    scan = H.scan_directory(base, "olr_pcp")
    text = " | ".join(scan.problems)
    assert "temporary file" in text and "path too long" in text and "not a regular file" in text


def test_plan_archive_judges_sizes_and_age(source, monkeypatch):
    p = H.plan_archive(source, "ne120", "mcs_tbpf", HPSS_DIR)
    assert p.hpss_path == f"{HPSS_DIR}/ne120_remap_0.1deg/mcs_tbpf.tar" and not p.problems and not p.skip
    assert any("below the recommended 100 GB" in w for w in p.warnings) and p.has_manifest
    fresh = H.plan_archive(source, "ne120", "mcs_tbpf", HPSS_DIR, now=time.time() - 3 * 86400 + 60)
    assert fresh.skip.startswith("newest file is")
    monkeypatch.setattr(H, "ARCHIVE_MAX_BYTES", 10)
    assert any("above the 2 TB limit" in x for x in H.plan_archive(source, "ne120", "mcs_tbpf", HPSS_DIR).problems)
    with pytest.raises(H.HpssError):
        H.plan_archive(source, "ne120", "nothing_here", HPSS_DIR)


def test_manifest_round_trip_and_apply(tmp_path):
    links = [("a/l1", "/data/ne120_remap_0.1deg/a/target"), ("a/sub/l2", "../x"), ("b/l3", "/elsewhere/file")]
    text = H.manifest_text("/data/ne120_remap_0.1deg", links, ["a/empty"])
    m = H.parse_manifest(text)
    assert m.source_base == "/data/ne120_remap_0.1deg" and m.links == links and m.empty_dirs == ["a/empty"]
    with pytest.raises(H.HpssError):
        H.parse_manifest("not a manifest")
    with pytest.raises(H.HpssError):
        H.manifest_text("/x", [("a\tb", "t")], [])
    dest = tmp_path / "d"
    c = H.apply_manifest(m, dest, ["a"], relink_to=dest)                 # only the entries below a/, absolute targets into the old root rewritten
    assert c["created"] == 2 and c["relinked"] == 1 and not (dest / "b").exists()
    assert os.readlink(dest / "a/l1") == f"{dest}/a/target" and os.readlink(dest / "a/sub/l2") == "../x" and (dest / "a/empty").is_dir()
    assert H.apply_manifest(m, dest, ["a"], relink_to=dest)["same"] == 2                    # again: nothing changes
    assert H.apply_manifest(m, dest, ["a"])["conflict"] == 1                                # the link exists with another target (not relinked this time)
    assert H.apply_manifest(m, dest, ["a"], overwrite=True)["replaced"] == 1


def test_plan_extract_names_folders_and_files():
    info = H.ArchiveInfo("ne120", "mcs_tbpf", f"{HPSS_DIR}/ne120_remap_0.1deg/mcs_tbpf.tar", 1, True, True)
    members = ["mcs_tbpf/2009/a.nc", "mcs_tbpf/2010/stats/b.nc", "mcs_tbpf/2010/stats/c.nc"]
    assert H.plan_extract(info, members).whole
    p = H.plan_extract(info, members, ["mcs_tbpf/2010/stats"])
    assert p.names == ["mcs_tbpf/2010/stats/"] and p.files == members[1:] and not p.whole
    assert H.plan_extract(info, members, ["mcs_tbpf/2009/a.nc"]).names == ["mcs_tbpf/2009/a.nc"]
    with pytest.raises(H.HpssError):
        H.plan_extract(info, members, ["mcs_tbpf/2011"])
    assert H.htar_extract_cmd("/h/t.tar", ["mcs_tbpf/2010/"], nostage=True)[-2:] == ["-Hnostage", "mcs_tbpf/2010/"]
    big = H.htar_create_cmd("/h/t.tar", "/l", 5_000_000)
    assert big[big.index("-M") + 1] == "5000001" and "-Hcrc" in big and "-Hnocrc" in H.htar_create_cmd("/h/t.tar", "/l", 1, crc=False)


def test_parsers_for_hsi_and_htar_output():
    ls = "\n/home/f/x:\n-rw-r-----  1 feng045 feng045  123456 Oct 25 20:00 a.tar\n-rw-r-----  1 feng045 feng045  12 Jun 25  2013 a.tar.idx\ndrwxr-s---  7 feng045 feng045  512 Jun 25  2013 sub\n"
    assert H.parse_hsi_ls(ls) == {"a.tar": (123456, False), "a.tar.idx": (12, False), "sub": (512, True)}
    tl = "HTAR: -rw-r-----  feng045/feng045  5 2026-10-25 20:00  t/f.nc\nHTAR: -rw-------  feng045/feng045  1 2026-10-25 20:00  /tmp/HTAR_CF_CHK_1_2\nHTAR: HTAR SUCCESSFUL\n"
    assert H.parse_htar_list(tl) == ["t/f.nc"]


def test_ensure_transfer_host(monkeypatch):
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_JOB_QOS", raising=False)
    H.ensure_transfer_host()                                                    # no Slurm: a login node
    monkeypatch.setenv("SLURM_JOB_ID", "1")
    monkeypatch.setenv("SLURM_JOB_QOS", "xfer")
    H.ensure_transfer_host()
    monkeypatch.setenv("SLURM_JOB_QOS", "interactive")
    with pytest.raises(H.HpssError, match="login node or in the xfer QOS"):
        H.ensure_transfer_host()


# ------------------------------------------------------------------------------------------------ backup
def test_plan_only_prints_and_writes_nothing(source, tape, capsys):
    rc = backup(source, "--models", "ne120")
    out = capsys.readouterr().out
    assert rc == 0 and "plan only" in out and not tape.calls()
    assert "ne120_remap_0.1deg/mcs_tbpf.tar" in out and "ne120_remap_0.1deg/olr_pcp.tar" in out and "quicklooks" not in out and "animations" not in out
    assert not list((tape.root / HPSS_DIR.lstrip("/")).iterdir())               # nothing was created in HPSS
    assert not (source / "_hpss_logs").exists()                                  # and no work folder on scratch


def test_run_writes_real_files_only_and_the_manifest(source, tape, capsys):
    rc = backup(source, "--models", "ne120", "--dirs", "mcs_tbpf", "mcs_tbpf_hr2p0", "--run")
    out = capsys.readouterr().out
    assert rc == 0 and out.count("verified") >= 2
    folder = tape.path(f"{HPSS_DIR}/ne120_remap_0.1deg")
    assert sorted(p.name for p in folder.iterdir()) == ["mcs_tbpf.tar", "mcs_tbpf.tar.idx", "mcs_tbpf.tar.links.tsv",
                                                       "mcs_tbpf_hr2p0.tar", "mcs_tbpf_hr2p0.tar.idx", "mcs_tbpf_hr2p0.tar.links.tsv"]
    creates = {Path(c["tar"]).name: c for c in tape.calls("c")}
    assert creates["mcs_tbpf_hr2p0.tar"]["list"] == ["mcs_tbpf_hr2p0/2010/stats/mcs_tracks_pf.txt"]        # no link, no file of the linked tree
    assert creates["mcs_tbpf.tar"]["cwd"] == str(source / "ne120_remap_0.1deg") and len(tape.calls("K")) == 2
    m = H.parse_manifest((folder / "mcs_tbpf_hr2p0.tar.links.tsv").read_text())
    assert m.source_base == str(source / "ne120_remap_0.1deg") and len(m.links) == 2
    assert (source / "_hpss_logs" / "lists").is_dir() and list((source / "_hpss_logs").glob("backup_*.csv"))


def test_a_second_run_skips_what_is_in_hpss(source, tape, capsys):
    assert backup(source, "--models", "ne120", "--dirs", "olr_pcp", "--run") == 0
    capsys.readouterr()
    assert backup(source, "--models", "ne120", "--dirs", "olr_pcp", "--run") == 0
    assert "exists" in capsys.readouterr().out and len(tape.calls("c")) == 1
    assert backup(source, "--models", "ne120", "--dirs", "olr_pcp", "--run", "--verify-existing") == 0
    assert len(tape.calls("c")) == 1 and len(tape.calls("K")) == 2            # read back and checked, not written again


def test_a_manifest_that_is_missing_is_added_to_an_archive_that_exists(source, tape, capsys):
    assert backup(source, "--models", "ne120", "--dirs", "mcs_tbpf_hr2p0", "--run") == 0
    man = tape.path(f"{HPSS_DIR}/ne120_remap_0.1deg/mcs_tbpf_hr2p0.tar.links.tsv")
    man.unlink()
    capsys.readouterr()
    assert backup(source, "--models", "ne120", "--dirs", "mcs_tbpf_hr2p0", "--run") == 0
    assert "manifest added" in capsys.readouterr().out and man.exists() and len(tape.calls("c")) == 1


def test_interrupted_failed_refused_and_young_archives(source, tape, capsys, monkeypatch):
    # an interrupted htar: the tar without its index is reported and never touched
    folder = tape.path(f"{HPSS_DIR}/ne120_remap_0.1deg")
    folder.mkdir(parents=True)
    (folder / "olr_pcp.tar").write_bytes(b"half")
    assert backup(source, "--models", "ne120", "--dirs", "olr_pcp", "--run") == 1
    out = capsys.readouterr().out
    assert "incomplete" in out and (folder / "olr_pcp.tar").read_bytes() == b"half" and not tape.calls("c")
    (folder / "olr_pcp.tar").unlink()
    # a failed htar, then a failed verification, then a failed manifest copy
    for what, text in (("create", "htar -c exited"), ("verify", "CRC"), ("put", "hsi put")):
        for p in folder.glob("*"):
            p.unlink()
        monkeypatch.delenv("FAKE_HTAR_FAIL", raising=False)
        monkeypatch.delenv("FAKE_HSI_PUT_FAIL", raising=False)
        if what == "put":
            monkeypatch.setenv("FAKE_HSI_PUT_FAIL", "1")
        else:
            monkeypatch.setenv("FAKE_HTAR_FAIL", what)
        assert backup(source, "--models", "ne120", "--dirs", "mcs_tbpf_hr2p0", "--run") == 1
        assert "failed" in capsys.readouterr().out
    monkeypatch.delenv("FAKE_HTAR_FAIL", raising=False)
    monkeypatch.delenv("FAKE_HSI_PUT_FAIL", raising=False)
    # a temporary file in the source refuses the archive, the others are written
    make_file(source / "ne120_remap_0.1deg" / "olr_pcp" / "x.nc.9.tmp", "t")
    for p in folder.glob("*"):
        p.unlink()
    assert backup(source, "--models", "ne120", "--dirs", "olr_pcp", "mcs_tbpf_hr2p0", "--run") == 1
    out = capsys.readouterr().out
    assert "refused" in out and (folder / "mcs_tbpf_hr2p0.tar").exists() and not (folder / "olr_pcp.tar").exists()
    # files that are still being written: left for later
    make_file(source / "ne120_remap_0.1deg" / "olr_pcp" / "x.nc.9.tmp", "t", age_days=0)
    (source / "ne120_remap_0.1deg" / "olr_pcp" / "x.nc.9.tmp").unlink()
    make_file(source / "ne120_remap_0.1deg" / "olr_pcp" / "new.nc", "new", age_days=0)
    rc = script("hpss_e3sm_backup").main(["--root", str(source), "--hpss-dir", HPSS_DIR, "--models", "ne120", "--dirs", "olr_pcp", "--run"])
    assert "SKIP: newest file is" in capsys.readouterr().out and rc == 0


def test_a_missing_hpss_folder_stops_the_run(source, tape, monkeypatch):
    with pytest.raises(SystemExit, match="does not exist"):
        script("hpss_e3sm_backup").main(["--root", str(source), "--hpss-dir", "/home/f/feng045/NOPE", "--models", "ne120", "--dirs", "olr_pcp", "--min-age-min", "0", "--run"])


# ------------------------------------------------------------------------------------------------ restore
def archive_all(source):
    assert backup(source, "--models", "ne120", "--run") == 0


def test_list_shows_the_archives(source, tape, capsys):
    archive_all(source)
    capsys.readouterr()
    assert restore(source, "--models", "ne120", "--list") == 0
    out = capsys.readouterr().out
    assert "ne120_remap_0.1deg/mcs_tbpf.tar" in out and "index yes" in out and out.count("links yes") == 2 and "olr_pcp.tar" in out and "links no" in out


def test_restore_whole_archives_recreates_files_links_and_empty_dirs(source, tape, tmp_path, capsys):
    archive_all(source)
    dest = tmp_path / "dest"
    rc = restore(source, "--models", "ne120", "--dest", str(dest))
    assert rc == 0, capsys.readouterr().out
    got, want = tree(dest / "ne120_remap_0.1deg"), tree(source / "ne120_remap_0.1deg")
    for skipped in ("quicklooks_2panel_tbpf", "animations_2panel_tbpf"):
        want = {k: v for k, v in want.items() if not k.startswith(skipped)}
    assert got == want                                                       # files, links with the same targets, the empty folder
    assert list((dest / "_hpss_logs").glob("restore_*.csv"))


def test_restore_a_sub_path_only(source, tape, tmp_path):
    archive_all(source)
    dest = tmp_path / "dest"
    assert restore(source, "--models", "ne120", "--dirs", "mcs_tbpf", "--path", "mcs_tbpf/2010/stats", "--dest", str(dest)) == 0
    got = tree(dest / "ne120_remap_0.1deg")
    assert [k for k, v in got.items() if v[0] == "file"] == ["mcs_tbpf/2010/stats/monthly/mcs_rainmap_201001.nc"]
    assert not any(v[0] == "link" for v in got.values())                     # the links of the manifest are outside the requested path
    assert tape.calls("x")[-1]["members"] == ["mcs_tbpf/2010/stats/"]        # only that folder was named to htar, not the whole archive
    # a file, and a link below a requested folder
    dest2 = tmp_path / "dest2"
    assert restore(source, "--models", "ne120", "--dirs", "mcs_tbpf", "--path", "mcs_tbpf/2010/tracking", "--dest", str(dest2)) == 0
    got = tree(dest2 / "ne120_remap_0.1deg")
    assert got["mcs_tbpf/2010/tracking/campaign_a/cloudid_20100101.nc"][0] == "link" and got["mcs_tbpf/2010/tracking/2009-01/cloudid_20100101.nc"][0] == "file"


def test_relink_points_absolute_links_into_the_destination(source, tape, tmp_path):
    archive_all(source)
    dest = tmp_path / "dest"
    assert restore(source, "--models", "ne120", "--dirs", "mcs_tbpf", "mcs_tbpf_hr2p0", "--dest", str(dest), "--relink") == 0
    base = dest / "ne120_remap_0.1deg"
    link = base / "mcs_tbpf_hr2p0" / "2010" / "tracking"
    assert os.readlink(link) == str(base / "mcs_tbpf" / "2010" / "tracking") and (link / "2009-01" / "cloudid_20100101.nc").read_text() == "cloudid 2010"
    assert os.readlink(base / "mcs_tbpf_hr2p0" / "link_to_pf.txt") == "../2010/stats/mcs_tracks_pf.txt"          # a relative target stays as it is


def test_restore_leaves_existing_paths_refuses_the_source_root_and_checks_counts(source, tape, tmp_path, capsys, monkeypatch):
    archive_all(source)
    dest = tmp_path / "dest"
    assert restore(source, "--models", "ne120", "--dirs", "olr_pcp", "--dest", str(dest)) == 0
    n = len(tape.calls("x"))
    capsys.readouterr()
    assert restore(source, "--models", "ne120", "--dirs", "olr_pcp", "--dest", str(dest)) == 0
    out = capsys.readouterr().out
    assert "nothing to restore" in out or "already in" in out
    assert len(tape.calls("x")) == n                                          # nothing was extracted again
    with pytest.raises(SystemExit, match="original data root"):
        restore(source, "--models", "ne120", "--dirs", "olr_pcp", "--dest", str(source))
    monkeypatch.setenv("FAKE_HTAR_FAIL", "extract")                           # one file too few arrives
    assert restore(source, "--models", "ne120", "--dirs", "mcs_tbpf", "--dest", str(tmp_path / "d2")) == 1
    assert "too few files" in capsys.readouterr().out


def test_dry_run_extracts_nothing_and_a_missing_archive_is_an_error(source, tape, tmp_path, capsys):
    archive_all(source)
    dest = tmp_path / "dest"
    capsys.readouterr()
    assert restore(source, "--models", "ne120", "--dirs", "mcs_tbpf", "--path", "mcs_tbpf/2009", "--dest", str(dest), "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "mcs_tbpf/2009/" in out and not tape.calls("x") and not dest.exists()
    with pytest.raises(SystemExit, match="nothing in HPSS"):
        restore(source, "--models", "ne120", "--dirs", "nope", "--dest", str(dest))
    with pytest.raises(SystemExit, match="give --dest"):
        restore(source, "--models", "ne120", "--dirs", "olr_pcp")
