#!/usr/bin/env python
"""Combine the per-year output files of one source into one multi-year Parquet file.

``extract_mcs_env.py`` writes one file per year (``mcs_env_<source>_<year>.parquet``). This script concatenates them (same columns, units and
attributes) into ``mcs_env_<source>_tropics_<year0>_<year1>.parquet`` (the naming of the MCS track files ``mcs_tracks_final_combined_tropics_*.parquet``,
so the two sets can be joined on period, local_track and track_time). The file document gets ``combined_from`` (the input files), the summed counts and
the missing-frame counts of every year.

Example:  python combine_mcs_env.py --source 3km_CTL --years 1995 2005 --dir $SCRATCH/mcs_env
"""

import os

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from mcsenv.outputs import META_KEY, write_mcs_env  # noqa: E402


def combine(files, out_path):
    """Concatenate output files of one source into one file with merged metadata.

    Args:
        files: list of per-year files (same source, same settings), in the order of the years.
        out_path: output ``.parquet`` file.

    Returns:
        number of rows written.
    """
    # Step 1: read every file; the dictionary-coded period becomes plain strings so that the tables concatenate, and the settings must agree
    tables, documents, column_meta = [], [], {}
    for path in files:
        table = pq.read_table(path)
        schema = pq.read_schema(path)
        document = json.loads(schema.metadata[META_KEY])
        if documents and (document["source"] != documents[0]["source"] or document["diameters_km"] != documents[0]["diameters_km"]
                          or document["step_hours"] != documents[0]["step_hours"]):
            raise ValueError(f"{path} was made with other settings (source, diameters or step) than {files[0]}")
        if tables and table.column_names != tables[0].column_names:
            raise ValueError(f"{path} has other columns than {files[0]}")
        index = table.schema.get_field_index("period")
        tables.append(table.set_column(index, "period", table.column("period").cast(pa.string())))
        documents.append(document)
        for field in schema:
            if field.metadata:
                column_meta[field.name] = {k.decode(): v.decode() for k, v in field.metadata.items()}
    # Step 2: one table with period dictionary-coded again, and the combined file document
    combined = pa.concat_tables([t.replace_schema_metadata(None) for t in tables])
    columns = {name: combined.column(name).combine_chunks() for name in combined.column_names}
    columns["period"] = columns["period"].dictionary_encode()
    merged = dict(documents[0])
    merged.update({
        "period": [d["period"] for d in documents], "combined_from": [os.path.basename(p) for p in files],
        "n_tracks": sum(d["n_tracks"] for d in documents), "n_samples": sum(d["n_samples"] for d in documents),
        "n_rows": sum(d["n_rows"] for d in documents), "groups_by_period": {d["period"]: d["groups"] for d in documents},
        "created": max(d["created"] for d in documents),
    })
    merged.pop("groups", None)
    write_mcs_env(out_path, columns, column_meta, merged)
    return combined.num_rows


def main():
    """Find the per-year files of a source and combine them."""
    parser = argparse.ArgumentParser(description="Combine per-year MCS environment files into one multi-year file.")
    parser.add_argument("--source", required=True, help="source name (OBS, 3km_CTL, ...)")
    parser.add_argument("--years", nargs=2, type=int, required=True, metavar=("Y0", "Y1"), help="first and last year")
    parser.add_argument("--dir", default=os.path.join(os.environ.get("SCRATCH", "."), "mcs_env"), help="the --out-dir of extract_mcs_env.py (default: $SCRATCH/mcs_env)")
    args = parser.parse_args()
    folder = os.path.join(args.dir, args.source)
    files = [os.path.join(folder, f"mcs_env_{args.source}_{y}.parquet") for y in range(args.years[0], args.years[1] + 1)]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        sys.exit(f"missing per-year files: {missing}")
    out = os.path.join(folder, f"mcs_env_{args.source}_tropics_{args.years[0]}_{args.years[1]}.parquet")
    rows = combine(files, out)
    print(f"wrote {out}: {rows} rows from {len(files)} files ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
