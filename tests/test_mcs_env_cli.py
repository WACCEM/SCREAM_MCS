"""Tests of the command-line tools of ``mcs_environment``: extract_mcs_env.py (track file, date filter, overrides), check_mcs_env_output.py (passes a good
file, catches a corrupted value and a duplicated row) and combine_mcs_env.py (two years into one file).

They reuse the synthetic input files of ``test_mcs_env_pipeline.py``.

Run from the scream folder:  python -m pytest tests/test_mcs_env_cli.py
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "mcs_environment"
sys.path.insert(0, str(ROOT))

import combine_mcs_env  # noqa: E402
from mcsenv.outputs import META_KEY, read_mcs_env  # noqa: E402
from test_mcs_env_pipeline import build_world, make_cfg, make_tracks  # noqa: E402


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    """Synthetic input files, a track Parquet file with two periods (the second is the first shifted by one 'year' label), and a sources.yaml."""
    d = tmp_path_factory.mktemp("cli")
    (d / "world").mkdir()
    world = build_world(d / "world")
    tracks = make_tracks()
    both = pd.concat([tracks, tracks.assign(period="2001")], ignore_index=True)
    table = pa.table({
        "period": both["period"].astype(str), "local_track": both["local_track"].astype("int64"),
        "base_time": pa.array(both["t"].to_numpy() * 1000, pa.int64()).cast(pa.timestamp("ms", tz="UTC")),
        "meanlat": both["lat"], "meanlon": both["lon"]})
    pq.write_table(table, d / "tracks.parquet")
    cfg = make_cfg(world)
    cfg["tracks"] = str(d / "tracks.parquet")
    cfg.pop("name")
    with open(d / "sources.yaml", "w") as handle:
        yaml.safe_dump({"defaults": {}, "sources": {"synth": cfg}}, handle)
    return d


def cli(script, *args):
    """Run a script of mcs_environment with the current Python; returns the completed process (output captured)."""
    return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)], capture_output=True, text=True)


def test_extract_cli_reads_the_track_file_and_applies_overrides(setup):
    """The CLI writes one file per year, applies the track-start range and the diameter override, and stores them in the metadata."""
    out = setup / "out_a"
    result = cli("extract_mcs_env.py", "--config", setup / "sources.yaml", "--source", "synth", "--years", 2000, 2001, "--nproc", 2, "--out-dir", out)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    files = sorted((out / "synth").glob("mcs_env_synth_20*.parquet"))
    assert [f.name for f in files] == ["mcs_env_synth_2000.parquet", "mcs_env_synth_2001.parquet"]
    a, b = read_mcs_env(files[0]), read_mcs_env(files[1])
    assert set(a["period"].astype(str)) == {"2000"} and set(b["period"].astype(str)) == {"2001"} and len(a) == len(b)
    filtered = cli("extract_mcs_env.py", "--config", setup / "sources.yaml", "--source", "synth", "--years", 2000, 2000, "--diameters-km", 2000, "--start-date",
                   "2000-01-03", "--end-date", "2000-01-04", "--out-dir", out)
    assert filtered.returncode == 0, filtered.stdout[-2000:] + filtered.stderr[-2000:]
    f = read_mcs_env(out / "synth" / "mcs_env_synth_2000_20000103_20000104.parquet")
    assert sorted(f["local_track"].unique()) == [1, 2, 3] and list(f["diameter_km"].unique()) == [2000]
    assert f.attrs["mcs_env"]["track_start_range"] == ["2000-01-03", "2000-01-04"]


def test_checker_passes_and_catches_corruption(setup):
    """The checker passes a good file (structure and independent recomputation of every row), and fails on a changed value and on a duplicated row."""
    out = setup / "out_b"
    assert cli("extract_mcs_env.py", "--config", setup / "sources.yaml", "--source", "synth", "--years", 2000, 2000, "--out-dir", out).returncode == 0
    good = out / "synth" / "mcs_env_synth_2000.parquet"
    ok = cli("check_mcs_env_output.py", good, "--config", setup / "sources.yaml", "--brute-force", 10000)
    assert ok.returncode == 0, ok.stdout[-3000:]
    assert "ALL CHECKS PASSED" in ok.stdout and "independent recomputation" in ok.stdout
    # A changed value: found by the independent recomputation (every row is recomputed)
    table = pq.read_table(good)
    schema = pq.read_schema(good)
    column = table.column("rh850").to_numpy().copy()
    row = int(np.flatnonzero(np.isfinite(column))[5])
    column[row] += 1.0
    bad_value = out / "synth" / "bad_value.parquet"
    pq.write_table(table.set_column(table.schema.get_field_index("rh850"), schema.field("rh850"), pa.array(column)), bad_value)
    result = cli("check_mcs_env_output.py", bad_value, "--config", setup / "sources.yaml", "--brute-force", 10000)
    assert result.returncode == 1 and "MISMATCH rh850" in result.stdout
    # A duplicated row: found by the key and the row-count checks
    bad_rows = out / "synth" / "bad_rows.parquet"
    pq.write_table(pa.concat_tables([table, table.slice(0, 3)]).replace_schema_metadata({META_KEY: schema.metadata[META_KEY]}), bad_rows)
    result = cli("check_mcs_env_output.py", bad_rows, "--config", setup / "sources.yaml")
    assert result.returncode == 1 and "FAIL  key" in result.stdout


def test_combine_two_years(setup):
    """Two per-year files become one file with all rows, the columns and units of the inputs, a merged document and plain period labels."""
    out = setup / "out_c"
    assert cli("extract_mcs_env.py", "--config", setup / "sources.yaml", "--source", "synth", "--years", 2000, 2001, "--out-dir", out).returncode == 0
    result = cli("combine_mcs_env.py", "--source", "synth", "--years", 2000, 2001, "--dir", out)
    assert result.returncode == 0, result.stdout + result.stderr
    combined = read_mcs_env(out / "synth" / "mcs_env_synth_tropics_2000_2001.parquet")
    one = read_mcs_env(out / "synth" / "mcs_env_synth_2000.parquet")
    two = read_mcs_env(out / "synth" / "mcs_env_synth_2001.parquet")
    assert len(combined) == len(one) + len(two) and list(combined.columns) == list(one.columns)
    assert set(combined["period"].astype(str)) == {"2000", "2001"} and combined.attrs["units"] == one.attrs["units"]
    meta = combined.attrs["mcs_env"]
    assert meta["period"] == ["2000", "2001"] and meta["n_samples"] == one.attrs["mcs_env"]["n_samples"] * 2 and len(meta["combined_from"]) == 2
    pd.testing.assert_frame_equal(combined.iloc[: len(one)].reset_index(drop=True).astype({"period": str}), one.reset_index(drop=True).astype({"period": str}))
    # Files made with other settings must not be combined
    other = cli("extract_mcs_env.py", "--config", setup / "sources.yaml", "--source", "synth", "--years", 2001, 2001, "--diameters-km", 2000, "--out-dir", setup / "out_c2")
    assert other.returncode == 0
    with pytest.raises(ValueError, match="other settings"):
        combine_mcs_env.combine([out / "synth" / "mcs_env_synth_2000.parquet", setup / "out_c2" / "synth" / "mcs_env_synth_2001.parquet"], str(setup / "x.parquet"))
