#!/usr/bin/env python3
"""Restore E3SM MCS-tracking output directories (or parts of them) from the HPSS archives written by hpss_e3sm_backup.py (docs/hpss_e3sm.md).

``--list`` shows the archives in HPSS. A restore names the model(s), the archive(s) (``--dirs``), optionally sub-paths of them (``--path``) and a
destination folder ``--dest`` that plays the role of the data root: the files come back as ``<dest>/<model>_remap_0.1deg/<dir>/...``, the original tree.
The member list is read from the archive's index (no tape), only the wanted members are extracted with ``htar -x -p`` (a sub-path ``mcs_tbpf/2010/stats``
extracts that folder only), and afterwards the number of files per requested path is compared with the member list. The symbolic links and empty
directories of the manifest ``<dir>.tar.links.tsv`` are recreated (only those under the requested paths); with ``--relink`` an absolute link target
that points into the original data root is rewritten to point into ``--dest``, so that a tree restored together with the tree it links to works.
A directory or path that already exists in ``--dest`` is left alone unless ``--overwrite``; restoring into the original data root is refused.

htar works on login and xfer nodes only: for more than a few files run it in the xfer QOS (slurm_hpss_e3sm_restore.sbatch).

Examples::

    # what is in HPSS
    python hpss_e3sm_restore.py --list

    # the plan and the htar commands, nothing is extracted
    python hpss_e3sm_restore.py --models ne120 --dirs mcs_tbpf_hr2p0 --path mcs_tbpf_hr2p0/2010/stats --dest $SCRATCH/restore --dry-run

    # do it
    python hpss_e3sm_restore.py --models ne120 --dirs mcs_tbpf_hr2p0 --path mcs_tbpf_hr2p0/2010/stats --dest $SCRATCH/restore
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import os
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hpss_e3sm_lib as H  # noqa: E402

log = logging.getLogger("hpss_e3sm_restore")


def build_parser() -> argparse.ArgumentParser:
    """Command line of the restore script. Returns the argument parser."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", choices=H.MODELS, default=list(H.MODELS), help="models (default both)")
    ap.add_argument("--dirs", nargs="+", metavar="NAME", help="archives to serve, by directory name (default: all of the models)")
    ap.add_argument("--path", nargs="+", metavar="PATH", dest="paths", default=[],
                    help="only these paths of the archives, relative to the model folder (<dir>/..., a folder or a file); default: everything")
    ap.add_argument("--dest", metavar="DIR", help="data root to restore into: <dest>/<model>_remap_0.1deg/<dir>/... is created")
    ap.add_argument("--hpss-dir", default=H.DEFAULT_HPSS_DIR, help="HPSS parent folder of the archives (default %(default)s)")
    ap.add_argument("--source-root", default=H.DEFAULT_ROOT, help="the original data root: restoring into it is refused (default %(default)s)")
    ap.add_argument("--workers", type=int, default=2, help="archives extracted at the same time (default 2; HPSS allows 15 sessions)")
    ap.add_argument("--no-crc", action="store_true", help="do not check CRCs while extracting (faster)")
    ap.add_argument("--nostage", action="store_true", help="htar -Hnostage: for a few small members of archives of 100 GB or more")
    ap.add_argument("--relink", action="store_true", help="rewrite absolute link targets that point into the original data root so that they point into --dest")
    ap.add_argument("--overwrite", action="store_true", help="extract into paths that already exist in --dest and replace links that point elsewhere (default: leave them)")
    ap.add_argument("--list", action="store_true", help="list the archives in HPSS (size, index, manifest) and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the htar commands, extract nothing")
    ap.add_argument("--work-dir", metavar="DIR", help="htar logs, the manifests and the CSV report (default <dest>/_hpss_logs)")
    ap.add_argument("--verbose", "-v", action="store_true", help="debug messages")
    return ap


@dataclass
class Job:
    """One archive to read: its plan, the paths that are skipped because ``--dest`` has them, the files expected below each requested path, and its manifest."""

    plan: H.ExtractPlan
    skipped: list[str]
    expected: dict[str, int]
    manifest: H.Manifest


def select_archives(args: argparse.Namespace) -> list[H.ArchiveInfo]:
    """The archives of the requested models and directories. Raises :class:`H.HpssError` if a named directory is not in HPSS."""
    out = []
    for model in args.models:
        have = H.list_archives(args.hpss_dir, model)
        if args.dirs:
            names = {a.name for a in have}
            missing = [d for d in args.dirs if d not in names]
            if missing and len(args.models) == 1:
                raise H.HpssError(f"nothing in HPSS for {missing} in {H.model_folder(model)}; archived: {sorted(names)}")
            out += [a for a in have if a.name in args.dirs]
        else:
            out += have
    return out


def make_job(info: H.ArchiveInfo, args: argparse.Namespace, dest_base: Path, work: Path) -> Job | None:
    """Read the member list (and the manifest) of one archive and decide what to extract; None if nothing of it is wanted.

    Inputs: the archive; the arguments; ``dest_base`` the model folder in ``--dest``; ``work`` the folder for manifests. Paths that exist and are not empty
    in ``dest_base`` are dropped unless ``--overwrite``; when that happens the whole-archive extraction is replaced by naming the remaining paths."""
    rc, out = H.run_tool(H.htar_list_cmd(info.path))
    if rc != 0:
        raise H.HpssError(f"cannot list {info.path} (htar -t exited {rc}): {out.strip()[-200:]}")
    members = H.parse_htar_list(out)
    # The requested paths that belong to this archive (the first component is the directory name)
    mine = [p for p in args.paths if p.strip("/").split("/")[0] == info.name]
    if args.paths and not mine:
        return None
    plan = H.plan_extract(info, members, mine)
    if not plan.files:
        return None
    expected: dict[str, int] = {}
    for m in plan.files:
        key = next((p.strip("/") for p in mine if m == p.strip("/") or m.startswith(p.strip("/") + "/")), info.name) if mine else info.name
        expected[key] = expected.get(key, 0) + 1
    # What already exists in the destination is left alone
    skipped = []
    if not args.overwrite:
        for key in list(expected):
            target = dest_base / key
            if target.is_dir() and any(target.iterdir()) or (target.is_file()):
                skipped.append(key)
        if skipped:
            keep = [p for p in (mine or [info.name]) if p.strip("/") not in skipped]
            for key in skipped:
                expected.pop(key, None)
            plan = H.plan_extract(info, members, keep) if keep else H.ExtractPlan(info, [], [], whole=False)
    manifest = H.Manifest()
    if info.has_manifest:
        local = work / f"{info.model}_{info.name}.tar{H.MANIFEST_SUFFIX}"
        H.hsi_get(f"{info.path}{H.MANIFEST_SUFFIX}", local)
        manifest = H.parse_manifest(local.read_text())
    return Job(plan, skipped, expected, manifest)


def extract(job: Job, dest_base: Path, work: Path, args: argparse.Namespace) -> tuple[str, float, str]:
    """Run htar for one job in ``dest_base``, check the restored file counts and recreate the links of the manifest.

    Output: ``(status, seconds, message)`` with status ``restored``, ``nothing`` or ``failed``."""
    t0 = time.time()
    if not job.plan.files and not job.plan.whole:
        return "nothing", 0.0, "everything requested is in the destination already"
    name = job.plan.archive.path.rsplit("/", 1)[1]
    log_path = work / f"{job.plan.archive.model}_{name}.restore.log"
    dest_base.mkdir(parents=True, exist_ok=True)
    rc, out = H.run_tool(job.plan.command(crc=not args.no_crc, nostage=args.nostage), cwd=dest_base, log_path=log_path)
    if rc != 0 or "HTAR FAILED" in out:
        return "failed", time.time() - t0, f"htar -x exited {rc}; see {log_path}"
    # Files per requested path against the member list
    bad = []
    for key, n in job.expected.items():
        target = dest_base / key
        have = 1 if target.is_file() else sum(len(files) for _, _, files in os.walk(target))
        if have < n:
            bad.append(f"{key} {have}/{n}")
    if bad:
        return "failed", time.time() - t0, f"too few files after extraction: {', '.join(bad[:3])}"
    # The links and empty directories of the manifest, below the requested paths only
    prefixes = [] if job.plan.whole else [n.rstrip("/") for n in job.plan.names]
    relink_to = dest_base if args.relink else None
    counts = H.apply_manifest(job.manifest, dest_base, prefixes if prefixes else [job.plan.archive.name], relink_to, args.overwrite) if (job.manifest.links or job.manifest.empty_dirs) else {}
    note = f"{sum(job.expected.values())} files in {len(job.expected)} path(s)"
    if any(counts.values()):
        note += ", links " + ", ".join(f"{k} {v}" for k, v in counts.items() if v)
    return "restored", time.time() - t0, note


def main(argv: list[str] | None = None) -> int:
    """List, plan and (unless --dry-run) restore; returns the exit status (1 if a restore failed)."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        archives = select_archives(args)
        if args.list:
            for a in archives:
                print(f"{H.model_folder(a.model)}/{a.name + '.tar':36s} {a.size / 1e9:9.1f} GB  index {'yes' if a.has_index else 'MISSING'}  links {'yes' if a.has_manifest else 'no'}")
            return 0
        if not args.dest:
            raise H.HpssError("give --dest (or --list)")
        dest = Path(args.dest).expanduser()
        if dest.resolve() == Path(args.source_root).resolve() and not args.overwrite:
            raise H.HpssError(f"--dest is the original data root {args.source_root}: refused (use another folder, or --overwrite)")
        if not archives:
            raise H.HpssError("no archive in HPSS for this request")
        work = Path(args.work_dir) if args.work_dir else dest / "_hpss_logs"
        work.mkdir(parents=True, exist_ok=True) if not args.dry_run else None
        jobs: list[tuple[Path, Job]] = []
        for info in archives:
            if not info.has_index:
                print(f"{info.path}: no .idx index, skipped (htar -X rebuilds it)")
                continue
            dest_base = dest / H.model_folder(info.model)
            job = make_job(info, args, dest_base, work if not args.dry_run else Path(os.environ.get("TMPDIR", "/tmp")))
            if job is None:
                print(f"{info.path}: nothing of the request is in it")
            else:
                jobs.append((dest_base, job))
    except H.HpssError as exc:
        raise SystemExit(f"error: {exc}") from None

    # The plan
    for dest_base, j in jobs:
        n = sum(j.expected.values())
        print(f"{H.model_folder(j.plan.archive.model) + '/' + j.plan.archive.name + '.tar':56s} {len(j.expected):4d} path(s) {n:9,d} files; {len(j.manifest.links):,} links in the manifest"
              + (f"; already in {dest_base}: {', '.join(j.skipped)}" if j.skipped else "") + ("; whole archive" if j.plan.whole else ""))
    if args.dry_run or not jobs:
        for dest_base, j in jobs:
            print("would run in", dest_base, ":", " ".join(shlex.quote(c) for c in j.plan.command(crc=not args.no_crc, nostage=args.nostage)[:12]))
        print("(dry run: nothing extracted)" if jobs else "nothing to restore")
        return 0

    # Extract, `workers` archives at a time
    try:
        H.ensure_transfer_host()
    except H.HpssError as exc:
        raise SystemExit(f"error: {exc}") from None
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 15))) as ex:
        for (dest_base, j), (status, secs, msg) in zip(jobs, ex.map(lambda x: extract(x[1], x[0], work, args), jobs)):
            print(f"{status:9s} {j.plan.archive.model}/{j.plan.archive.name + '.tar':36s} {secs:7.0f} s  {msg}", flush=True)
            rows.append((j.plan.archive.path, status, secs, msg))
    report = work / f"restore_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    with open(report, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["archive", "status", "seconds", "message"])
        w.writerows(rows)
    failed = sum(r[1] == "failed" for r in rows)
    print(f"done in {time.time() - t0:.0f} s: {sum(r[1] == 'restored' for r in rows)} restored, {failed} failed; report {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
