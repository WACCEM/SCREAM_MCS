#!/usr/bin/env python
"""Write the Slurm script of one source (an array over years, one node per year) from ``slurm_template.sh``. Nothing is submitted.

Example::

    python gen_mcs_env_jobs.py --source 3km_CTL --years 1995 2005 --account m1867 --time 02:00:00

writes ``slurm/slurm_mcsenv_3km_CTL.sh`` and prints the ``sbatch`` command. Submit it yourself (or ask Claude to, after your approval).
Tasks of an array can be limited with ``sbatch --array=1996-1998 slurm/...`` or ``sbatch --array=1995-2005%2`` (two at a time).
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = "/global/common/software/m1867/python/pyflex26.3/bin/python"


def render(template_path, values):
    """Fill the ``@NAME@`` markers of a template.

    Args:
        template_path: template file.
        values: dictionary NAME -> text.

    Returns:
        the filled text (an error when a marker remains).
    """
    text = open(template_path).read()
    for name, value in values.items():
        text = text.replace(f"@{name}@", str(value))
    # Every marker must have been filled
    left = sorted(set(re.findall(r"@[A-Z0-9_]+@", text)))
    if left:
        raise ValueError(f"markers of the template were not filled: {left}")
    return text


def main():
    """Parse the command line and write the script."""
    parser = argparse.ArgumentParser(description="Write the Slurm array script of one source (nothing is submitted).")
    parser.add_argument("--source", required=True, help="source name in config/sources.yaml")
    parser.add_argument("--years", nargs=2, type=int, required=True, metavar=("Y0", "Y1"), help="first and last year (one array task each)")
    parser.add_argument("--account", required=True, help="Slurm account (project), for example m1867")
    parser.add_argument("--qos", default="regular", help="QOS (default regular)")
    parser.add_argument("--time", default="02:00:00", help="wall time per year (default 02:00:00)")
    parser.add_argument("--nproc", type=int, default=128, help="worker processes per node (default 128)")
    parser.add_argument("--out-dir", default=os.path.join(os.environ.get("SCRATCH", "."), "mcs_env"), help="output folder (default $SCRATCH/mcs_env)")
    parser.add_argument("--script-dir", default=os.path.join(HERE, "slurm"), help="where the script and the log folder go (default: mcs_environment/slurm)")
    args = parser.parse_args()

    log_dir = os.path.join(args.out_dir, args.source, "_logs")
    os.makedirs(args.script_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    text = render(os.path.join(HERE, "slurm_template.sh"), {
        "JOB_NAME": f"mcsenv_{args.source}", "ACCOUNT": args.account, "QOS": args.qos, "TIME": args.time, "SOURCE": args.source,
        "YEAR0": args.years[0], "YEAR1": args.years[1], "LOG_DIR": log_dir, "OUT_DIR": args.out_dir, "CODE_DIR": HERE, "NPROC": args.nproc, "PYTHON": PYTHON})
    path = os.path.join(args.script_dir, f"slurm_mcsenv_{args.source}.sh")
    with open(path, "w") as handle:
        handle.write(text)
    print(f"wrote {path}\nsubmit with:  sbatch {path}")


if __name__ == "__main__":
    sys.exit(main())
