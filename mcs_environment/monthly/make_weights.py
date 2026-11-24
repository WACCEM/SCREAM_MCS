#!/usr/bin/env python
"""Step 0: the 1 degree target grid and one bilinear weight file per distinct source grid of the dataset configs.

Writes into ``maps_dir`` of ``config/grids.yaml``: ``grid_<target>.nc`` (SCRIP file of the target grid, from ``ncremap -G``), the SCRIP files of
generated source grids (``grid_<source>.nc``), and ``map_<source>_to_<target>_<method>.nc`` for every source grid used by the given dataset
configs (ne30pg2 is shared by 3km_CTL, 3km_TUNE and 100km, so it is made once). Existing files are kept. Every map is checked (sizes, row
sums of 1, unmapped destination cells only beyond the outermost source cell centre). Weight generation needs memory and minutes: run it on a
compute node.

Example:
    python make_weights.py --configs config/ERA5.yaml config/3km_CTL.yaml config/3km_TUNE.yaml config/25km.yaml config/100km.yaml
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from envmonthly.config import load_dataset  # noqa: E402
from envmonthly.ncotools import check_weights, make_grid_file, make_weights, node_kind  # noqa: E402


def main():
    """Make the grid files and weight files and check them; exit code 1 when a check fails."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", nargs="+", required=True, help="dataset YAML files whose source grids need weights")
    args = ap.parse_args()
    if node_kind() == "login":
        print("warning: this is a login node; weight generation is better done on a compute node")

    # The distinct source grids of the datasets, and the target grid
    datasets = [load_dataset(c) for c in args.configs]
    common = datasets[0].common
    maps = Path(common.maps_dir)
    dst = make_grid_file(common.target["generate"], maps / f"grid_{common.target['name']}.nc")
    print(f"target grid {common.target['name']}: {dst}")
    grids = sorted({d.grid for d in datasets})

    # One weight file per source grid, then its checks
    failed = False
    for gname in grids:
        spec = common.sources[gname]
        src = spec["scrip"] if "scrip" in spec else make_grid_file(spec["generate"], maps / f"grid_{gname}.nc")
        map_path = datasets[[d.grid for d in datasets].index(gname)].map_path()
        make_weights(src, dst, map_path, common.method, common.weight_options)
        problems, info = check_weights(map_path, src, dst, bilinear=(common.method == "bilinear"))
        print(f"{gname}: {map_path}")
        for line in info:
            print("   ", line)
        for problem in problems:
            print("    PROBLEM:", problem)
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
