"""HPSS archives of the E3SM MCS-tracking output: which tar holds which directory, how to write one with ``htar`` and how to get parts back.

Every top-level directory of ``<root>/<model>_remap_0.1deg`` (``mcs_tbpf``, ``mcs_tbpf_hr2p0``, ``mcs_tbpf_sens``, ``olr_pcp``) is bundled in ONE tar
archive, so a restore needs no catalog::

    <hpss_dir>/<model>_remap_0.1deg/<dir>.tar               the real files of the directory, members ``<dir>/<path below it>``
    <hpss_dir>/<model>_remap_0.1deg/<dir>.tar.idx           index written by htar (list the members without reading tape)
    <hpss_dir>/<model>_remap_0.1deg/<dir>.tar.links.tsv     manifest of the symbolic links and empty directories (see below)

**Symbolic links are not archived by htar.** htar limits a link name to 99 characters and the trees hold tens of thousands of absolute links with
110-116 character targets (``mcs_tbpf/<year>/tracking/campaign_*/cloudid_*.nc``, ``stats/mcs_tracks_*.rows`` of the derived trees). The scan of a
directory therefore does not follow links; it puts every link (path relative to the model folder, target) and every empty directory in the manifest,
which the backup script copies to HPSS next to the tar and the restore script reads back to recreate them. A link is never followed, so a derived
tree (``mcs_tbpf_hr2p0``, ``mcs_tbpf_sens``) does not duplicate the files it links to; it is complete only together with the tree it links to.

This module holds the logic that does not need HPSS (scanning with the limits of NERSC's ``htar``, names, manifest, command lines, parsing of ``hsi`` /
``htar`` output, what a restore request needs); ``hpss_e3sm_backup.py`` and ``hpss_e3sm_restore.py`` run it. Limits (docs.nersc.gov/filesystems/htar):
a member path of at most 154 + 99 characters (prefix + name), a member of at most ~68 GB (64 GB used here), an archive of 100 GB to 2 TB (the system
takes ~20 TB), 1,000,000 members by default (raised with ``-M``, hard limit 5,000,000), no appending, ``htar`` only on login and ``xfer`` nodes.
The helpers ``run_tool``, ``hsi_ls``, ``hsi_mkdir_p``, ``ensure_transfer_host`` and the parsers are those of ``mrms_processing/hpss.py`` (airscape).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

log = logging.getLogger(__name__)

DEFAULT_ROOT = "/pscratch/sd/f/feng045/E3SM_polun"          # the data root: <root>/<model>_remap_0.1deg/<dir>
DEFAULT_HPSS_DIR = "/home/f/feng045/E3SM_polun"             # must exist in HPSS; the levels below it are created
MODELS = ("ne120", "ne30")
EXCLUDED_DIRS = ("animations_2panel_tbpf", "quicklooks_2panel_tbpf")        # not backed up unless named with --dirs
PATH_PREFIX_MAX, NAME_MAX = 154, 99              # htar: directory part and file name of a member
MEMBER_MAX_BYTES = 64 * 10 ** 9                  # documented ~68 GB; the conservative value of the MRMS scripts
ARCHIVE_MIN_BYTES, ARCHIVE_MAX_BYTES = 100 * 10 ** 9, 2 * 10 ** 12   # recommended range of an htar bundle
MEMBERS_DEFAULT, MEMBERS_HARD = 1_000_000, 5_000_000                 # htar's soft limit (raised with -M) and hard limit
HTAR_INTERNAL = "HTAR_CF_CHK_"                   # the member htar adds to every archive (an index check file)
MANIFEST_SUFFIX = ".links.tsv"                   # <dir>.tar + MANIFEST_SUFFIX
MANIFEST_HEADER = "# e3sm_hpss_manifest v1"


class HpssError(RuntimeError):
    """A request that cannot be served (unknown folder, nothing to do, a limit of htar that would be exceeded ...)."""


# --------------------------------------------------------------------------------------------
# Names and folders
# --------------------------------------------------------------------------------------------
def model_folder(model: str) -> str:
    """Folder name of a model below the data root and below the HPSS directory: ``ne120`` -> ``ne120_remap_0.1deg``."""
    return f"{model}_remap_0.1deg"


def list_dirs(root: str | Path, model: str, exclude: Sequence[str] = EXCLUDED_DIRS) -> list[str]:
    """Top-level directories of ``<root>/<model>_remap_0.1deg`` that are backed up: all, minus ``exclude`` (default :data:`EXCLUDED_DIRS`),
    minus names that start with ``.`` or ``_`` (work folders). Sorted. Raises :class:`HpssError` if the model folder does not exist."""
    base = Path(root) / model_folder(model)
    if not base.is_dir():
        raise HpssError(f"{base} does not exist")
    with os.scandir(base) as it:
        names = [e.name for e in it if e.is_dir(follow_symlinks=False) and not e.name.startswith((".", "_")) and e.name not in exclude]
    return sorted(names)


def hpss_tar_path(hpss_dir: str, model: str, name: str) -> str:
    """HPSS path of the archive of directory ``name``: ``<hpss_dir>/<model>_remap_0.1deg/<name>.tar``."""
    return f"{hpss_dir.rstrip('/')}/{model_folder(model)}/{name}.tar"


# --------------------------------------------------------------------------------------------
# Scanning one directory
# --------------------------------------------------------------------------------------------
@dataclass
class DirScan:
    """What a scan of one directory found. ``members`` are the real files (paths relative to the model folder, ``<dir>/...``), ``links`` the symbolic
    links ``(path, target)``, ``empty_dirs`` the directories without any entry, ``bytes`` the size of the members, ``newest`` the newest modification
    time of the members. ``problems`` refuse the archive, ``warnings`` change nothing."""

    members: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    empty_dirs: list[str] = field(default_factory=list)
    bytes: int = 0
    newest: float = 0.0
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _temporary(name: str) -> bool:
    """True for the name of a file that is probably still being written (``.part`` / ``.tmp``)."""
    return name.endswith((".part", ".tmp")) or ".tmp." in name or ".part." in name


def scan_directory(base: str | Path, name: str) -> DirScan:
    """Walk ``<base>/<name>`` without following symbolic links and judge every file against the limits of htar.

    Inputs: ``base`` the model folder (the member paths are relative to it); ``name`` the directory. Output: a :class:`DirScan`. Files are listed
    (sorted by name, directory by directory) and ``stat``ed, never opened. A temporary file, a path longer than htar allows, a member above
    :data:`MEMBER_MAX_BYTES` and a file that is neither a regular file nor a link (socket, fifo ...) are problems."""
    base = Path(base)
    scan = DirScan()
    n_hard = 0
    stack = [name]
    # Depth-first walk: one directory at a time, its entries sorted so that the member list is the same on every run
    while stack:
        rel_dir = stack.pop()
        with os.scandir(base / rel_dir) as it:
            entries = sorted(it, key=lambda e: e.name)
        if not entries:
            scan.empty_dirs.append(rel_dir)
            continue
        subdirs = []
        for e in entries:
            rel = f"{rel_dir}/{e.name}"
            if e.is_symlink():
                # A link (to a file or a directory) goes to the manifest, it is never followed
                scan.links.append((rel, os.readlink(e.path)))
            elif e.is_dir(follow_symlinks=False):
                subdirs.append(rel)
            elif e.is_file(follow_symlinks=False):
                st = e.stat(follow_symlinks=False)
                if _temporary(e.name):
                    scan.problems.append(f"temporary file in the source: {rel}")
                    continue
                if len(rel_dir) > PATH_PREFIX_MAX or len(e.name) > NAME_MAX:
                    scan.problems.append(f"path too long for htar (prefix {len(rel_dir)} > {PATH_PREFIX_MAX} or name {len(e.name)} > {NAME_MAX}): {rel}")
                if st.st_size > MEMBER_MAX_BYTES:
                    scan.problems.append(f"member larger than {MEMBER_MAX_BYTES / 1e9:.0f} GB: {rel}")
                n_hard += st.st_nlink > 1
                scan.members.append(rel)
                scan.bytes += st.st_size
                scan.newest = max(scan.newest, st.st_mtime)
            else:
                scan.problems.append(f"not a regular file or a link: {rel}")
        stack.extend(reversed(subdirs))
    if n_hard:
        scan.warnings.append(f"{n_hard} files with several hard links (archived as separate files)")
    return scan


@dataclass
class ArchivePlan:
    """One archive to write: what goes in, where it goes and what is wrong with it.

    ``members`` are the relative paths, ``links`` and ``empty_dirs`` go to the manifest, ``bytes`` is the size of the members, ``newest_age_min`` the
    age of the newest member. ``problems`` refuse the archive, ``skip`` is a reason to leave it for later without any fault (no files, or the newest
    file is too young: the directory is probably still being written), ``warnings`` change nothing."""

    model: str
    name: str
    base: Path
    hpss_path: str
    members: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    empty_dirs: list[str] = field(default_factory=list)
    bytes: int = 0
    newest_age_min: float = float("inf")
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skip: str = ""

    @property
    def tar_name(self) -> str:
        """File name of the archive: ``<dir>.tar``."""
        return f"{self.name}.tar"

    @property
    def manifest_path(self) -> str:
        """HPSS path of the manifest: ``<tar>.links.tsv``."""
        return self.hpss_path + MANIFEST_SUFFIX

    @property
    def has_manifest(self) -> bool:
        """True if there is anything for the manifest (a link or an empty directory)."""
        return bool(self.links or self.empty_dirs)


def plan_archive(root: str | Path, model: str, name: str, hpss_dir: str, *, min_age_min: float = 30.0, now: Optional[float] = None) -> ArchivePlan:
    """Scan ``<root>/<model>_remap_0.1deg/<name>`` and judge it against the limits of htar.

    Inputs: ``root`` the data root; ``model``; ``name`` the directory; ``hpss_dir`` the HPSS parent; ``min_age_min`` (default 30): a newest file
    younger than this means that the directory is probably still being written (``skip``). Output: an :class:`ArchivePlan`; no file is opened.
    Raises :class:`HpssError` if the directory does not exist."""
    now = time.time() if now is None else now
    base = Path(root) / model_folder(model)
    if not (base / name).is_dir():
        raise HpssError(f"{base / name} is not a directory")
    scan = scan_directory(base, name)
    plan = ArchivePlan(model, name, base, hpss_tar_path(hpss_dir, model, name), scan.members, scan.links, scan.empty_dirs, scan.bytes,
                       problems=list(scan.problems), warnings=list(scan.warnings))
    if not plan.members:
        plan.skip = "no files in this directory"
        return plan
    plan.newest_age_min = (now - scan.newest) / 60.0
    if plan.newest_age_min < min_age_min:
        plan.skip = f"newest file is {plan.newest_age_min:.0f} min old (< {min_age_min:.0f}): still being written?"
    if len(plan.members) + 1 > MEMBERS_HARD:
        plan.problems.append(f"{len(plan.members)} members exceed htar's hard limit of {MEMBERS_HARD:,}")
    elif len(plan.members) + 1 > MEMBERS_DEFAULT:
        plan.warnings.append(f"{len(plan.members)} members: above htar's soft limit of {MEMBERS_DEFAULT:,}, written with -M")
    if plan.bytes > ARCHIVE_MAX_BYTES:
        plan.problems.append(f"{plan.bytes / 1e12:.2f} TB is above the 2 TB limit of a good htar bundle: split the directory")
    elif plan.bytes < ARCHIVE_MIN_BYTES:
        plan.warnings.append(f"{plan.bytes / 1e9:.1f} GB is below the recommended 100 GB per bundle")
    return plan


# --------------------------------------------------------------------------------------------
# The manifest of links and empty directories
# --------------------------------------------------------------------------------------------
def manifest_text(source_base: str | Path, links: Sequence[tuple[str, str]], empty_dirs: Sequence[str]) -> str:
    """Text of the manifest: a header with the folder the paths come from, one ``L<TAB>link<TAB>target`` line per link, one ``D<TAB>dir`` per empty directory.

    Inputs: ``source_base`` the model folder on the source side (restore uses it for ``--relink``); ``links`` ``(path, target)``; ``empty_dirs``.
    Raises :class:`HpssError` for a name that contains a tab or a line break."""
    lines = [MANIFEST_HEADER, f"# source_base\t{source_base}"]
    for path, target in links:
        if any(c in path + target for c in "\t\n"):
            raise HpssError(f"a tab or line break in the link {path!r} -> {target!r}")
        lines.append(f"L\t{path}\t{target}")
    for path in empty_dirs:
        if any(c in path for c in "\t\n"):
            raise HpssError(f"a tab or line break in the directory {path!r}")
        lines.append(f"D\t{path}")
    return "\n".join(lines) + "\n"


@dataclass
class Manifest:
    """A parsed manifest: the source model folder, the links ``(path, target)`` and the empty directories."""

    source_base: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    empty_dirs: list[str] = field(default_factory=list)


def parse_manifest(text: str) -> Manifest:
    """Inverse of :func:`manifest_text`. Raises :class:`HpssError` if the text is not a manifest."""
    lines = text.splitlines()
    if not lines or lines[0] != MANIFEST_HEADER:
        raise HpssError("not an E3SM HPSS manifest (header missing)")
    out = Manifest()
    for line in lines[1:]:
        parts = line.split("\t")
        if parts[0] == "# source_base" and len(parts) == 2:
            out.source_base = parts[1]
        elif parts[0] == "L" and len(parts) == 3:
            out.links.append((parts[1], parts[2]))
        elif parts[0] == "D" and len(parts) == 2:
            out.empty_dirs.append(parts[1])
        elif line and not line.startswith("#"):
            raise HpssError(f"manifest line not understood: {line!r}")
    return out


def apply_manifest(manifest: Manifest, dest_base: str | Path, prefixes: Sequence[str] = (), relink_to: Optional[str | Path] = None, overwrite: bool = False) -> dict[str, int]:
    """Recreate the empty directories and the links of a manifest below ``dest_base`` (the folder that plays the role of the model folder).

    Inputs: ``manifest``; ``dest_base``; ``prefixes`` (default none = everything) only the entries at or below one of these paths; ``relink_to`` (default
    None) a folder: an absolute link target that starts with the manifest's source model folder is rewritten to start with this folder instead;
    ``overwrite`` (default False): replace a link that exists with another target (a file or directory of that name is never replaced).
    Output: counts ``created``, ``same`` (link existed with this target), ``replaced``, ``conflict`` (something else is there: left alone), ``relinked``."""
    dest_base = Path(dest_base)
    count = dict(created=0, same=0, replaced=0, conflict=0, relinked=0)

    def wanted(path: str) -> bool:
        return not prefixes or any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)

    # Empty directories first, then the links (their parent folders are made when they are missing)
    for path in manifest.empty_dirs:
        if wanted(path):
            (dest_base / path).mkdir(parents=True, exist_ok=True)
    src = manifest.source_base.rstrip("/")
    for path, target in manifest.links:
        if not wanted(path):
            continue
        if relink_to is not None and src and (target == src or target.startswith(src + "/")):
            target = f"{str(relink_to).rstrip('/')}{target[len(src):]}"
            count["relinked"] += 1
        link = dest_base / path
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if os.readlink(link) == target:
                count["same"] += 1
                continue
            if not overwrite:
                count["conflict"] += 1
                continue
            link.unlink()
            count["replaced"] += 1
        elif link.exists():
            count["conflict"] += 1
            continue
        else:
            count["created"] += 1
        os.symlink(target, link)
    return count


# --------------------------------------------------------------------------------------------
# hsi / htar: command lines and output parsers
# --------------------------------------------------------------------------------------------
def htar_create_cmd(tar: str, listfile: str, n_members: int, crc: bool = True) -> list[str]:
    """``htar`` command that writes ``tar`` in HPSS from the relative paths in ``listfile`` (run it in the model folder).

    ``-Hcrc`` stores CRCs in the index (default on), ``-M`` raises the member limit above the number of files plus htar's own member."""
    return ["htar", "-c", "-V", "-f", tar, "-Hcrc" if crc else "-Hnocrc", "-M", str(max(n_members + 1, MEMBERS_DEFAULT)), "-L", listfile]


def htar_verify_cmd(tar: str) -> list[str]:
    """``htar`` command that checks the archive against the CRCs of its index (reads the archive back)."""
    return ["htar", "-K", "-Hverify=crc", "-f", tar]


def htar_list_cmd(tar: str) -> list[str]:
    """``htar`` command that lists the members from the index (``.idx``): no tape is read."""
    return ["htar", "-t", "-f", tar]


def htar_extract_cmd(tar: str, members: Sequence[str] = (), *, crc: bool = True, nostage: bool = False) -> list[str]:
    """``htar`` command that extracts into the current folder: everything when ``members`` is empty, else the given files or ``dir/`` folders.

    ``-p`` keeps permissions, ``-Hcrc`` checks CRCs while extracting (default on), ``-Hnostage`` helps when one or two small members of an archive of
    100 GB or more are wanted."""
    return ["htar", "-x", "-p", "-f", tar, "-Hcrc" if crc else "-Hnocrc", *(["-Hnostage"] if nostage else []), *members]


_LS = re.compile(r"^(?P<mode>[-dl][-rwxsStT]{9})\s+\d+\s+\S+\s+\S+\s+(?P<size>\d+)\s+\w{3}\s+\d+\s+(?:\d{1,2}:\d{2}|\d{4})\s+(?P<name>.+?)\s*$")


def parse_hsi_ls(text: str) -> dict[str, tuple[int, bool]]:
    """Entries of an ``hsi ls -l`` listing: ``{name: (size in bytes, is_directory)}``. Header and blank lines are ignored."""
    out: dict[str, tuple[int, bool]] = {}
    for line in text.splitlines():
        m = _LS.match(line.strip("\r"))
        if m:
            out[os.path.basename(m["name"].rstrip("/"))] = (int(m["size"]), m["mode"][0] == "d")
    return out


_MODE = re.compile(r"^[-dl][-rwxsStT]{9}$")


def parse_htar_list(text: str) -> list[str]:
    """The member paths of an ``htar -t`` listing: lines that start (after an optional ``HTAR:``) with a mode string such as ``-rw-r-----``; the name is
    the last word (the file names of the E3SM trees have no blanks). htar's own check member is left out."""
    names = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "HTAR:":
            parts = parts[1:]
        if len(parts) >= 6 and _MODE.match(parts[0]) and HTAR_INTERNAL not in parts[-1]:
            names.append(parts[-1])
    return names


def run_tool(cmd: Sequence[str], *, cwd: Optional[str | Path] = None, log_path: Optional[str | Path] = None, timeout: Optional[float] = None) -> tuple[int, str]:
    """Run an external program without a terminal; its output (stdout and stderr together) goes to ``log_path`` if given.

    Output: ``(return code, output)``; with a log file the output is its last 64 KB. A program that cannot be started gives ``(127, message)``."""
    try:
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "wb") as fh:
                res = subprocess.run([str(c) for c in cmd], cwd=cwd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, check=False)
            with open(log_path, "rb") as fh:
                fh.seek(max(0, os.path.getsize(log_path) - 65536))
                return res.returncode, fh.read().decode(errors="replace")
        res = subprocess.run([str(c) for c in cmd], cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)
        return res.returncode, (res.stdout or "") + (res.stderr or "")
    except OSError as exc:
        return 127, f"cannot run {cmd[0]}: {exc}"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out after {timeout} s"


def hsi_ls(path: str) -> Optional[dict[str, tuple[int, bool]]]:
    """Entries of the HPSS folder ``path`` (or the one entry of a file): ``{name: (size, is_dir)}``; None if ``path`` does not exist."""
    rc, out = run_tool(["hsi", "-q", f"ls -l {path}"])
    if rc != 0 and not parse_hsi_ls(out):
        return None
    return parse_hsi_ls(out)


def hsi_mkdir_p(path: str) -> None:
    """Create ``path`` and its parents in HPSS (``hsi mkdir`` one level at a time; existing levels are left alone). Raises :class:`HpssError`."""
    parts = [p for p in path.split("/") if p]
    cur = ""
    for p in parts:
        cur += "/" + p
        rc, _ = run_tool(["hsi", "-q", f"ls -ld {cur}"])
        if rc == 0:
            continue
        rc, out = run_tool(["hsi", "-q", f"mkdir {cur}"])
        if rc != 0:
            raise HpssError(f"cannot create {cur} in HPSS: {out.strip()[-200:]}")


def hsi_put(local: str | Path, remote: str) -> None:
    """Copy a small local file to HPSS (``hsi put local : remote``). Raises :class:`HpssError` if hsi fails or the size in HPSS differs."""
    rc, out = run_tool(["hsi", "-q", f"put {local} : {remote}"])
    folder, name = remote.rsplit("/", 1)
    have = hsi_ls(folder) or {}
    if rc != 0 or name not in have or have[name][0] != os.path.getsize(local):
        raise HpssError(f"hsi put {local} -> {remote} failed (exit {rc}): {out.strip()[-200:]}")


def hsi_get(remote: str, local: str | Path) -> None:
    """Copy a small file from HPSS to a local path (``hsi get local : remote``). Raises :class:`HpssError` if hsi fails."""
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    rc, out = run_tool(["hsi", "-q", f"get {local} : {remote}"])
    if rc != 0 or not Path(local).exists():
        raise HpssError(f"hsi get {remote} -> {local} failed (exit {rc}): {out.strip()[-200:]}")


def ensure_transfer_host() -> None:
    """Refuse to run inside a Slurm allocation that is not the ``xfer`` QOS: htar cannot work on compute nodes. A login node is fine."""
    qos = os.environ.get("SLURM_JOB_QOS", "")
    if os.environ.get("SLURM_JOB_ID") and qos and qos.lower() != "xfer":
        raise HpssError(f"this is a {qos} allocation: run HPSS transfers on a login node or in the xfer QOS (htar needs incoming connections)")


# --------------------------------------------------------------------------------------------
# Restore: which archives, which paths
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ArchiveInfo:
    """An archive found in HPSS: its model, directory name, path, size, and whether its index ``.idx`` and its manifest are there."""

    model: str
    name: str
    path: str
    size: int
    has_index: bool
    has_manifest: bool


def list_archives(hpss_dir: str, model: str) -> list[ArchiveInfo]:
    """The archives of a model in HPSS, sorted by name (an empty list if the folder does not exist)."""
    folder = f"{hpss_dir.rstrip('/')}/{model_folder(model)}"
    entries = hsi_ls(folder) or {}
    out = []
    for name, (size, is_dir) in entries.items():
        if not is_dir and name.endswith(".tar"):
            out.append(ArchiveInfo(model, name[:-4], f"{folder}/{name}", size, f"{name}.idx" in entries, f"{name}{MANIFEST_SUFFIX}" in entries))
    return sorted(out, key=lambda a: a.name)


@dataclass
class ExtractPlan:
    """What to take out of one archive: the ``files`` (members) that are wanted, the ``names`` to give to htar (files, or ``dir/`` for a folder) and
    whether that is the whole archive."""

    archive: ArchiveInfo
    files: list[str]
    names: list[str]
    whole: bool

    def command(self, *, crc: bool = True, nostage: bool = False) -> list[str]:
        """The htar command for this plan (run it in the destination model folder)."""
        return htar_extract_cmd(self.archive.path, [] if self.whole else self.names, crc=crc, nostage=nostage)


def plan_extract(archive: ArchiveInfo, members: Sequence[str], paths: Sequence[str] = ()) -> ExtractPlan:
    """Choose what to extract from ``archive`` given its member list (``htar -t``) and the requested ``paths`` (default none = everything).

    A path is a member (a file) or a folder: the members below it are wanted and htar gets ``path/``. A path that matches no member is an error
    (:class:`HpssError`). Output: an :class:`ExtractPlan`; when every member is wanted, the whole archive is extracted (no names are passed)."""
    if not paths:
        return ExtractPlan(archive, list(members), [], whole=True)
    wanted: list[str] = []
    names: list[str] = []
    member_set = set(members)
    for p in paths:
        p = p.strip("/")
        if p in member_set:
            wanted.append(p)
            names.append(p)
            continue
        below = [m for m in members if m.startswith(p + "/")]
        if not below:
            raise HpssError(f"nothing in {archive.path} below {p!r}")
        wanted += below
        names.append(p + "/")
    wanted = list(dict.fromkeys(wanted))
    return ExtractPlan(archive, wanted, list(dict.fromkeys(names)), whole=len(wanted) == len(members))
