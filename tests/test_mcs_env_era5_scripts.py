"""Tests of the ERA5 copy scripts (``mcs_environment/era5_copy``) on a small fake CFS tree: what is listed, what is skipped, what stops the generator, and the
exit status of the verification. Nothing is copied (the generator only writes lists and a script).

Run from the scream folder:  python -m pytest tests/test_mcs_env_era5_scripts.py
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "mcs_environment" / "era5_copy"


def months_of(year0, year1):
    """The months the scripts handle for a range: the December before, all months of the years, the January after."""
    out = [f"{year0 - 1}12"] + [f"{y}{m:02d}" for y in range(year0, year1 + 1) for m in range(1, 13)] + [f"{year1 + 1}01"]
    return out


def days(ym):
    """Number of days of a month (Gregorian)."""
    import calendar

    return calendar.monthrange(int(ym[:4]), int(ym[4:]))[1]


def expected_names(ym):
    """File names of one month in the CFS layout: (type, name) for the pressure-level days and the surface months."""
    names = []
    for var in ("128_133_q", "128_157_r", "128_135_w"):
        names += [("pl", f"e5.oper.an.pl.{var}.ll025sc.{ym}{d:02d}00_{ym}{d:02d}23.nc") for d in range(1, days(ym) + 1)]
    names += [("sfc", f"e5.oper.an.sfc.{var}.ll025sc.{ym}0100_{ym}{days(ym):02d}23.nc") for var in ("128_137_tcwv", "128_134_sp")]
    return names


@pytest.fixture()
def tree(tmp_path):
    """A fake CFS tree for 2006-12 ... 2008-01 with files of 100 bytes, and empty destination and work folders."""
    src = tmp_path / "cfs"
    for ym in months_of(2007, 2007):
        for kind, name in expected_names(ym):
            path = src / f"e5.oper.an.{kind}" / ym / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 100)
    return {"src": src, "dst": tmp_path / "scratch", "work": tmp_path / "work"}


def bash(script, tree, *args, extra_env=None):
    """Run a script of era5_copy with the fake source and destination; returns the completed process."""
    env = dict(os.environ, ERA5_SRC=str(tree["src"]), ERA5_DST=str(tree["dst"]), WORKDIR=str(tree["work"]), FORCE="1", **(extra_env or {}))
    return subprocess.run(["bash", str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, env=env)


def test_generator_lists_every_file_and_writes_one_task_per_month_and_type(tree):
    """2007 with its margin months: 1309 files, 28 transfer tasks, the mkdir lines, lists per month and type, and no copy."""
    result = bash("make_era5_globus_script.sh", tree, 2007, 2007)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "files to copy: 1309, already complete on scratch: 0" in result.stdout and "28 transfer tasks" in result.stdout
    runner = (tree["work"] / "globus_copy_2007.sh").read_text().splitlines()
    tasks = [line for line in runner if line.startswith("transfer_files.py")]
    assert len(tasks) == 28 and sum(line.startswith("mkdir -p") for line in runner) == 28
    assert "set -e" in runner and any("generate_token.py -s dtn -t dtn --renew" in line for line in runner)       # stops at the first failure and says how to renew the login
    assert f"transfer_files.py -s dtn -t dtn -d {tree['dst']}/e5.oper.an.pl/200612/ -i {tree['work']}/list_pl_200612 -p" in runner
    assert len((tree["work"] / "list_pl_200612").read_text().splitlines()) == 93 and len((tree["work"] / "list_sfc_200701").read_text().splitlines()) == 2
    assert len((tree["work"] / "list_pl_200802").read_text().splitlines()) == 0 if (tree["work"] / "list_pl_200802").exists() else True
    assert not tree["dst"].exists()                                      # the generator copies nothing and creates nothing on the destination


def test_generator_skips_complete_files_and_relists_wrong_sizes(tree):
    """A file that is already on scratch with the same size is left out, a file with another size is listed again."""
    done = tree["dst"] / "e5.oper.an.pl" / "200701"
    done.mkdir(parents=True)
    first, second = [n for k, n in expected_names("200701") if k == "pl"][:2]
    (done / first).write_bytes(b"x" * 100)                               # complete
    (done / second).write_bytes(b"x" * 40)                               # partial
    result = bash("make_era5_globus_script.sh", tree, 2007, 2007)
    assert "files to copy: 1308, already complete on scratch: 1" in result.stdout
    lines = (tree["work"] / "list_pl_200701").read_text().splitlines()
    assert not any(first in line for line in lines) and any(second in line for line in lines)


def test_generator_stops_when_a_source_file_is_missing(tree):
    """A missing source file is reported and no script is usable (status 1)."""
    missing = tree["src"] / "e5.oper.an.pl" / "200703" / expected_names("200703")[10][1]
    missing.unlink()
    result = bash("make_era5_globus_script.sh", tree, 2007, 2007)
    assert result.returncode == 1 and "MISSING source file" in result.stdout and "ERROR: 1 source files are missing" in result.stdout


def test_generator_year_ranges_add_margins_only_at_the_ends(tree):
    """Two years: 2006-12 only in the first script, 2008-01 only in the last; the middle December belongs to the first year."""
    for ym in months_of(2007, 2008):
        for kind, name in expected_names(ym):
            path = tree["src"] / f"e5.oper.an.{kind}" / ym / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 100)
    result = bash("make_era5_globus_script.sh", tree, 2007, 2008)
    assert result.returncode == 0, result.stdout
    first = (tree["work"] / "globus_copy_2007.sh").read_text()
    last = (tree["work"] / "globus_copy_2008.sh").read_text()
    assert "200612" in first and "200801" not in first and "200612" not in last and "200901" in last
    assert last.count("\ntransfer_files.py") == 26 and first.count("\ntransfer_files.py") == 26


def test_verify_reports_missing_wrong_size_and_success(tree):
    """verify_era5_copy.sh: status 1 for an uncopied year and for a wrong size, status 0 for a complete copy."""
    empty = bash("verify_era5_copy.sh", tree, 2007, 2007)
    assert empty.returncode == 1 and "verified 0 files, 1309 problems" in empty.stdout
    for ym in months_of(2007, 2007):                                      # simulate the transfer
        for kind, name in expected_names(ym):
            target = tree["dst"] / f"e5.oper.an.{kind}" / ym / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 100)
    ok = bash("verify_era5_copy.sh", tree, 2007, 2007)
    assert ok.returncode == 0 and "verified 1309 files, 0 problems" in ok.stdout
    (tree["dst"] / "e5.oper.an.sfc" / "200705" / expected_names("200705")[-1][1]).write_bytes(b"x" * 99)
    wrong = bash("verify_era5_copy.sh", tree, 2007, 2007)
    assert wrong.returncode == 1 and "size differs" in wrong.stdout and "1 problems" in wrong.stdout
    again = bash("make_era5_globus_script.sh", tree, 2007, 2007)         # the generator now lists exactly that one file
    assert "files to copy: 1, already complete on scratch: 1308" in again.stdout


def test_runner_stops_at_the_first_failed_transfer_call(tree, tmp_path):
    """The generated script calls transfer_files.py once per month and type, in order, and stops at the first call that fails (a fake helper stands in)."""
    assert bash("make_era5_globus_script.sh", tree, 2007, 2007).returncode == 0
    log = tmp_path / "calls.log"
    fake = tmp_path / "bin" / "transfer_files.py"
    fake.parent.mkdir()
    fake.write_text(f'#!/bin/bash\necho "$@" >> {log}\n[ "$(wc -l < {log})" -ge 2 ] && echo "fake: authentication failed" >&2 && exit 1\nexit 0\n')
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{fake.parent}:{os.environ['PATH']}")
    result = subprocess.run(["bash", str(tree["work"] / "globus_copy_2007.sh")], capture_output=True, text=True, env=env, timeout=120)
    calls = log.read_text().splitlines()
    assert result.returncode != 0 and len(calls) == 2                      # the second call failed and nothing after it was tried
    assert calls[0].startswith(f"-s dtn -t dtn -d {tree['dst']}/e5.oper.an.pl/200612/ -i {tree['work']}/list_pl_200612")
    assert calls[1].startswith(f"-s dtn -t dtn -d {tree['dst']}/e5.oper.an.sfc/200612/ -i {tree['work']}/list_sfc_200612")
    assert (tree["dst"] / "e5.oper.an.pl" / "200612").is_dir() and not (tree["dst"] / "e5.oper.an.pl" / "200701").exists()      # mkdir only for the months reached
