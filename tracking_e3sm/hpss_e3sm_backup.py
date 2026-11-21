#!/usr/bin/env python3
"""Back up the E3SM MCS-tracking output directories to NERSC HPSS with htar, one tar archive per directory (docs/hpss_e3sm.md).

Every top-level directory of ``<root>/<model>_remap_0.1deg`` (``mcs_tbpf``, ``mcs_tbpf_hr2p0``, ``mcs_tbpf_sens``, ``olr_pcp``; the animation and
quicklook folders are left out) becomes ``<hpss-dir>/<model>_remap_0.1deg/<dir>.tar`` with its index ``.tar.idx`` and, when the directory holds
symbolic links or empty directories, a manifest ``<dir>.tar.links.tsv`` (htar limits a link name to 99 characters, the links of these trees are longer,
so htar archives the real files only and the links are recreated from the manifest by hpss_e3sm_restore.py).

**Without --run nothing is written**: the script scans the directories and prints the plan (archive, files, links, GB, notes) and exits. With --run, each
archive is written with ``htar -c -V -Hcrc``, checked against its CRCs with ``htar -K -Hverify=crc``, its manifest is copied to HPSS, and the result is
recorded in a CSV. An archive that exists in HPSS with its index is skipped, so submitting the same job again after a time-out continues. An archive
without its ``.idx`` (an interrupted htar) is reported and never touched. Nothing is ever deleted, on scratch or in HPSS. htar works on login and xfer
nodes only: run it in the xfer QOS (slurm_hpss_e3sm_backup.sbatch).

Examples::

    # what would be archived (nothing is written)
    python hpss_e3sm_backup.py

    # one model, two directories, for real (inside an xfer job)
    python hpss_e3sm_backup.py --models ne120 --dirs mcs_tbpf_hr2p0 olr_pcp --run
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hpss_e3sm_lib as H  # noqa: E402

log = logging.getLogger("hpss_e3sm_backup")


def build_parser() -> argparse.ArgumentParser:
    """Command line of the backup script. Returns the argument parser."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=H.DEFAULT_ROOT, help="data root with <model>_remap_0.1deg (default %(default)s)")
    ap.add_argument("--models", nargs="+", choices=H.MODELS, default=list(H.MODELS), help="models (default both)")
    ap.add_argument("--dirs", nargs="+", metavar="NAME",
                    help=f"directories below <root>/<model>_remap_0.1deg (default: all except {', '.join(H.EXCLUDED_DIRS)}; naming one here includes it)")
    ap.add_argument("--hpss-dir", default=H.DEFAULT_HPSS_DIR, help="HPSS parent folder, must exist; <model>_remap_0.1deg below it is created (default %(default)s)")
    ap.add_argument("--workers", type=int, default=3, help="archives written at the same time (default 3; HPSS allows 15 sessions)")
    ap.add_argument("--no-crc", action="store_true", help="no CRCs in the index and no verification afterwards (faster, not recommended)")
    ap.add_argument("--verify-existing", action="store_true",
                    help="also check archives that are in HPSS already against their CRCs (reads them back; use it after a verification failed)")
    ap.add_argument("--min-age-min", type=float, default=30.0,
                    help="leave a directory for later (SKIP in the plan) if its newest file is younger than this many minutes, a sign that files are still "
                         "being written (default 30; 0 switches the check off)")
    ap.add_argument("--work-dir", metavar="DIR", help="list files (lists/), htar logs (logs/) and the CSV report (default <root>/_hpss_logs); only written with --run")
    ap.add_argument("--run", action="store_true",
                    help="write the archives. Without it the script prints the plan and writes nothing: no list files, no logs, no CSV, nothing in HPSS")
    ap.add_argument("--verbose", "-v", action="store_true", help="debug messages")
    return ap


@dataclass
class Result:
    """What happened to one archive: its plan, a status (verified | written | exists | skipped | refused | incomplete | failed), seconds, a message."""

    plan: H.ArchivePlan
    status: str
    seconds: float = 0.0
    message: str = ""


def _manifest_in_hpss(plan: H.ArchivePlan, work: Path) -> None:
    """Write the manifest of ``plan`` into the work folder and copy it to HPSS next to the tar. Raises :class:`H.HpssError`."""
    local = work / "lists" / f"{plan.model}_{plan.tar_name}{H.MANIFEST_SUFFIX}"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(H.manifest_text(plan.base, plan.links, plan.empty_dirs))
    H.hsi_put(local, plan.manifest_path)


def write_archive(plan: H.ArchivePlan, work: Path, crc: bool = True, verify_existing: bool = False) -> Result:
    """Write one archive: skip it if it exists, else ``htar -c`` from the model folder, verify against the CRCs, check the index, copy the manifest.

    Inputs: the plan; ``work`` the folder for list files and logs; ``crc`` (default True) CRCs and verification; ``verify_existing`` (default False)
    also verify an archive that is already in HPSS. Output: a :class:`Result`; never raises for a failed htar (the status says so and the log file
    holds htar's output)."""
    t0 = time.time()
    tag = f"{plan.model}_{plan.tar_name}"
    # Refused or left for later: nothing is written
    if plan.problems:
        return Result(plan, "refused", message="; ".join(plan.problems[:2]))
    if plan.skip:
        return Result(plan, "skipped", message=plan.skip)
    folder, name = plan.hpss_path.rsplit("/", 1)
    have = H.hsi_ls(folder) or {}
    # The archive is in HPSS already: nothing to write (optionally verify it, and add a manifest that is missing)
    if name in have and f"{name}.idx" in have:
        note = f"{have[name][0] / 1e9:.1f} GB already in HPSS"
        if plan.has_manifest and f"{name}{H.MANIFEST_SUFFIX}" not in have:
            try:
                _manifest_in_hpss(plan, work)
                note += "; manifest added"
            except H.HpssError as exc:
                return Result(plan, "failed", time.time() - t0, f"{note}; {exc}")
        if verify_existing and crc:
            rc, _ = H.run_tool(H.htar_verify_cmd(plan.hpss_path), log_path=work / "logs" / f"{tag}.verify.log")
            return Result(plan, "verified" if rc == 0 else "failed", time.time() - t0,
                          note + ("" if rc == 0 else f"; htar -K -Hverify=crc exited {rc}, see {work / 'logs' / (tag + '.verify.log')}"))
        return Result(plan, "exists", time.time() - t0, note)
    # An interrupted htar left a tar without its index: reported, never touched
    if name in have:
        return Result(plan, "incomplete", time.time() - t0,
                      f"{plan.hpss_path} exists without its .idx (an interrupted htar). Not touched: check it, remove it with `hsi rm` if it is garbage, run again")
    # Write the archive from the model folder with the list of the real files (the links are not archived: they go to the manifest)
    listfile = work / "lists" / f"{tag}.list"
    listfile.parent.mkdir(parents=True, exist_ok=True)
    listfile.write_text("\n".join(plan.members) + "\n")
    rc, out = H.run_tool(H.htar_create_cmd(plan.hpss_path, str(listfile), len(plan.members), crc), cwd=plan.base, log_path=work / "logs" / f"{tag}.create.log")
    if rc != 0 or "HTAR FAILED" in out:
        return Result(plan, "failed", time.time() - t0, f"htar -c exited {rc}; see {work / 'logs' / (tag + '.create.log')}")
    status = "written"
    # Read it back against the CRCs of the index
    if crc:
        rc, out = H.run_tool(H.htar_verify_cmd(plan.hpss_path), log_path=work / "logs" / f"{tag}.verify.log")
        if rc != 0:
            return Result(plan, "failed", time.time() - t0, f"written, but htar -K -Hverify=crc exited {rc}; see {work / 'logs' / (tag + '.verify.log')}")
        status = "verified"
    after = H.hsi_ls(folder) or {}
    if name not in after or f"{name}.idx" not in after:
        return Result(plan, "failed", time.time() - t0, "the archive or its .idx is not in HPSS after htar")
    # The manifest of links and empty directories next to the tar
    if plan.has_manifest:
        try:
            _manifest_in_hpss(plan, work)
        except H.HpssError as exc:
            return Result(plan, "failed", time.time() - t0, f"archive {status}, {exc}")
    return Result(plan, status, time.time() - t0, f"{after[name][0] / 1e9:.1f} GB" + (f", {len(plan.links)} links in the manifest" if plan.links else ""))


def main(argv: list[str] | None = None) -> int:
    """Plan (and with --run write) the archives; returns the exit status (1 if an archive was refused or failed)."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = Path(args.root).expanduser()
    work = Path(args.work_dir) if args.work_dir else root / "_hpss_logs"
    # The directories of every model and their plans (the scan lists and stats files: metadata only, threads are enough)
    try:
        jobs = []
        for model in args.models:
            for name in (args.dirs if args.dirs else H.list_dirs(root, model)):
                if args.dirs and not (root / H.model_folder(model) / name).is_dir():
                    log.warning("%s: no directory %s, skipped", model, name)
                    continue
                jobs.append((model, name))
        if not jobs:
            raise H.HpssError("no directory to archive")
        with ThreadPoolExecutor(max_workers=8) as ex:
            plans = list(ex.map(lambda j: H.plan_archive(root, j[0], j[1], args.hpss_dir, min_age_min=args.min_age_min), jobs))
    except H.HpssError as exc:
        raise SystemExit(f"error: {exc}") from None
    # The plan table
    print(f"{'archive':64s} {'files':>9s} {'links':>8s} {'GB':>8s}  notes")
    for p in plans:
        notes = p.problems + ([f"SKIP: {p.skip}"] if p.skip else []) + p.warnings
        print(f"{p.hpss_path[len(args.hpss_dir.rstrip('/')) + 1:]:64s} {len(p.members):9,d} {len(p.links):8,d} {p.bytes / 1e9:8.1f}  " + ("; ".join(notes) or "ok"))
    ok = [p for p in plans if not p.problems and not p.skip]
    print(f"{len(plans)} archive(s): {len(ok)} to write, {sum(1 for p in plans if p.skip)} to leave for later, {sum(1 for p in plans if p.problems)} refused; "
          f"{sum(p.bytes for p in ok) / 1e12:.2f} TB to write")
    if not args.run:
        print("(plan only: add --run to write the archives)")
        return 1 if any(p.problems for p in plans) else 0

    # Real run: a transfer host, the HPSS parent must exist, the model folders below it are made
    try:
        H.ensure_transfer_host()
        if H.hsi_ls(args.hpss_dir) is None:
            raise H.HpssError(f"the HPSS folder {args.hpss_dir} does not exist (create it with `hsi mkdir`; only the levels below it are created here)")
        for folder in sorted({p.hpss_path.rsplit("/", 1)[0] for p in ok}):
            H.hsi_mkdir_p(folder)
    except H.HpssError as exc:
        raise SystemExit(f"error: {exc}") from None
    workers = max(1, min(args.workers, 15))
    t0 = time.time()
    results = []
    # Loop over the archives, `workers` at a time: one line per finished archive
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(lambda p: write_archive(p, work, not args.no_crc, args.verify_existing), plans):
            results.append(r)
            print(f"{r.status:10s} {r.plan.model + '/' + r.plan.tar_name:40s} {r.seconds:7.0f} s  {r.message}", flush=True)
    # The CSV report of the run
    report = work / f"backup_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    report.parent.mkdir(parents=True, exist_ok=True)
    with open(report, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["archive", "hpss_path", "files", "links", "bytes", "status", "seconds", "message"])
        for r in results:
            w.writerow([r.plan.tar_name, r.plan.hpss_path, len(r.plan.members), len(r.plan.links), r.plan.bytes, r.status, f"{r.seconds:.0f}", r.message])
    bad = [r for r in results if r.status in ("failed", "refused", "incomplete")]
    print(f"done in {time.time() - t0:.0f} s: " + ", ".join(f"{k} {sum(r.status == k for r in results)}" for k in
                                                              ("verified", "written", "exists", "skipped", "refused", "incomplete", "failed")) + f"; report {report}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
