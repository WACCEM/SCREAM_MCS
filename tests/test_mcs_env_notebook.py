"""Tests of the functions of ``Notebooks/analyze_mcs_env_composites_land_ocean.ipynb`` (robust-MCS selection, loading and matching, composites, figures).

The notebook is self-contained, so the tests run its cells tagged ``functions`` / ``config`` (imports, configuration, function definitions: no cell that reads data)
and call the functions on small synthetic track and environment tables in which every criterion removes a known track.

Run from the scream folder:  python -m pytest tests/test_mcs_env_notebook.py
"""

import json
import os
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

matplotlib.use("Agg")

# The notebook under test (the environment variable lets a mutated copy be tested to check that the tests can fail)
NOTEBOOK = Path(os.environ.get("MCS_ENV_NOTEBOOK", Path(__file__).resolve().parents[1] / "Notebooks" / "analyze_mcs_env_composites_land_ocean.ipynb"))


@pytest.fixture(scope="module")
def nb():
    """The namespace after running the cells tagged 'config' and 'functions' of the notebook, in notebook order."""
    data = json.loads(NOTEBOOK.read_text())
    ns = {"__name__": "nb"}
    for cell in data["cells"]:
        tags = set(cell.get("metadata", {}).get("tags", []))
        if cell["cell_type"] == "code" and tags & {"config", "functions"}:
            exec(compile("".join(cell["source"]), str(NOTEBOOK), "exec"), ns)
    return ns


def make_track(tid, status, lat0=5.0, lf=0.0, rain=None, split=np.nan, merge=np.nan, start_status=1, end_status=0, mcs_duration=None, period="2007"):
    """
    One synthetic track, one row per time step.

    Args:
        tid: int
            local_track.
        status: list of int
            mcs_status per step (its length is the duration).
        lat0: float
            Latitude of the first point (the other points move by 0.1 degree per step).
        lf: float or list
            pf_landfrac (one value or one per step).
        rain: list or None
            total_rain per step; the default is status + 0.1 * step, so the maximum is at the last MCS step (use fewer than 10 steps).
        split, merge: float
            start_split_cloudnumber / end_merge_cloudnumber (NaN = none).
        start_status, end_status: int
            PyFLEXTRKR status codes.
        mcs_duration: int or None
            Default: the number of MCS steps.
        period: str
            Period (year).

    Returns:
        DataFrame with the columns the notebook reads.
    """
    n = len(status)
    step = np.arange(n)
    return pd.DataFrame(dict(
        period=period, local_track=tid, relative_step=step, track_duration=n, meanlat=lat0 + 0.1 * step,
        mcs_status=np.asarray(status, dtype=float), mcs_duration=int(sum(status)) if mcs_duration is None else mcs_duration,
        total_rain=np.asarray(status, dtype=float) + 0.1 * step if rain is None else np.asarray(rain, dtype=float),
        pf_landfrac=lf if isinstance(lf, (list, np.ndarray)) else [float(lf)] * n,
        start_split_cloudnumber=split, end_merge_cloudnumber=merge, start_status=float(start_status), end_status=float(end_status)))


OK = [0, 0, 1, 1, 1, 1, 0]        # two non-MCS steps, one unbroken MCS block, the rain maximum at its last step


def criteria_tracks():
    """Tracks that each break exactly one criterion (and two that pass: an ocean and a land track), keyed by name -> track number."""
    specs = {
        "ok_ocean": dict(status=OK),
        "ok_land": dict(status=OK, lf=1.0),
        "not_tropics": dict(status=OK, lat0=40.0),
        "mcs_at_start": dict(status=[0, 1, 1, 1, 1, 1, 0]),
        "gap": dict(status=[0, 0, 1, 1, 0, 1, 1]),
        "split": dict(status=OK, split=5.0),
        "merge": dict(status=OK, merge=7.0),
        "peak_outside": dict(status=OK, rain=[0, 9, 1, 1, 1, 1, 0]),
        "coastal": dict(status=OK, lf=[0.0, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0]),
    }
    ids = {name: i + 1 for i, name in enumerate(specs)}
    tr = pd.concat([make_track(ids[name], **spec) for name, spec in specs.items()], ignore_index=True)
    return tr, ids


def test_each_criterion_removes_exactly_its_track(nb):
    """Only the ocean and the land track that break nothing are robust; every other track fails the one criterion it was built to break."""
    tr, ids = criteria_tracks()
    flags = nb["select_robust_tracks"](tr, duration_pct=None)
    robust = {name: bool(flags.loc[("2007", tid), "robust"]) for name, tid in ids.items()}
    assert robust == {name: name in ("ok_ocean", "ok_land") for name in ids}
    assert flags.loc[("2007", ids["ok_ocean"]), "surface"] == "Ocean" and flags.loc[("2007", ids["ok_land"]), "surface"] == "Land"
    assert flags.loc[("2007", ids["coastal"]), "surface"] == "Coastal"
    # The failing flag is the one that was meant (the others of that track pass)
    expected = {"not_tropics": "tropics", "mcs_at_start": "nonmcs_start", "gap": "continuous", "split": "no_split_merge", "merge": "no_split_merge",
                "peak_outside": "peak_in_mcs"}
    for name, column in expected.items():
        row = flags.loc[("2007", ids[name])]
        failing = [c for c in ("tropics", "nonmcs_start", "continuous", "no_split_merge", "peak_in_mcs") if not row[c]]
        assert failing == [column], (name, failing)


def test_summary_quantities_and_order_independence(nb):
    """The per-track table has the right lead, MCS block, peak status and latitude, and does not depend on the row order."""
    tr, ids = criteria_tracks()
    t = nb["summarize_tracks"](tr)
    row = t.loc[("2007", ids["ok_ocean"])]
    assert (row["n_steps"], row["lead_nonmcs"], row["first_mcs"], row["last_mcs"], row["n_mcs"], row["peak_status"]) == (7, 2, 2, 5, 4, 1)
    assert t.loc[("2007", ids["mcs_at_start"]), "lead_nonmcs"] == 1 and t.loc[("2007", ids["peak_outside"]), "peak_status"] == 0
    assert np.isclose(t.loc[("2007", ids["not_tropics"]), "lat0"], 40.0)
    shuffled = nb["summarize_tracks"](tr.sample(frac=1.0, random_state=3))
    pd.testing.assert_frame_equal(t.sort_index(), shuffled.sort_index())


def test_missing_data_cannot_pass(nb):
    """No position at the first step, no rain data, no land fraction at all: the track is not robust and nothing fails."""
    no_pos = make_track(1, OK)
    no_pos.loc[0, "meanlat"] = np.nan
    no_rain = make_track(2, OK, rain=[np.nan] * 7)
    no_lf = make_track(3, OK, lf=[np.nan] * 7)
    tr = pd.concat([no_pos, no_rain, no_lf, make_track(4, OK)], ignore_index=True)
    flags = nb["select_robust_tracks"](tr, duration_pct=None)
    assert flags["robust"].to_dict() == {("2007", 1): False, ("2007", 2): False, ("2007", 3): False, ("2007", 4): True}
    assert flags.loc[("2007", 3), "surface"] == "Coastal"


def test_duration_cut_is_per_surface_on_the_other_criteria_passing_tracks(nb):
    """The 95th percentile is taken over ocean tracks and land tracks separately, only over tracks that pass the other criteria (a long track that fails one is ignored)."""
    ocean = [make_track(i, [0, 0] + [1] * (n - 2)) for i, n in enumerate(range(6, 26), start=1)]
    land = [make_track(100 + i, [0, 0] + [1] * (n - 2), lf=1.0) for i, n in enumerate(range(6, 16), start=1)]
    long_but_split = [make_track(200, [0, 0] + [1] * 78, split=3.0)]            # fails another criterion: must not move the percentile
    tr = pd.concat(ocean + land + long_but_split, ignore_index=True)
    flags = nb["select_robust_tracks"](tr)
    cuts = flags.groupby("surface")["duration_cut"].first()
    assert np.isclose(cuts["Ocean"], np.quantile(np.arange(6, 26), 0.95)) and np.isclose(cuts["Land"], np.quantile(np.arange(6, 16), 0.95))
    robust = flags[flags["robust"]]
    assert (robust["surface"] == "Ocean").sum() == 19 and robust.loc[robust["surface"] == "Ocean", "duration"].max() == 24
    assert (robust["surface"] == "Land").sum() == 9 and robust.loc[robust["surface"] == "Land", "duration"].max() == 14
    assert not flags.loc[("2007", 200), "robust"]


def test_variants_reproduce_the_gsrm_repository_choices(nb):
    """Each option changes exactly the track built for it: three leading non-MCS steps, mcs_duration, status codes and the land-fraction sum."""
    specs = {
        "two_lead": dict(status=OK),
        "three_lead": dict(status=[0, 0, 0, 1, 1, 1, 0]),
        "gap_in_group": dict(status=[0, 0, 1, 1, 0, 1, 1], mcs_duration=4),          # PyFLEXTRKR counts the steps of a qualifying run that has a gap
        "spurious": dict(status=[0, 0, 1, 1, 1, 0, 1], mcs_duration=3),
        "start13": dict(status=OK, start_status=13),
        "small_land": dict(status=OK, lf=0.05),
    }
    ids = {name: i + 1 for i, name in enumerate(specs)}
    tr = pd.concat([make_track(ids[name], **spec) for name, spec in specs.items()], ignore_index=True)
    t = nb["summarize_tracks"](tr)

    def robust(**options):
        f = nb["apply_criteria"](t, duration_pct=None, **options)
        return {name for name, tid in ids.items() if f.loc[("2007", tid), "robust"]}

    assert robust() == {"two_lead", "three_lead", "start13", "small_land"}
    assert robust(n_nonmcs=3) == {"three_lead"}
    assert robust(continuity="mcs_duration") == {"two_lead", "three_lead", "gap_in_group", "start13", "small_land"}
    assert robust(split_merge="status") == {"two_lead", "three_lead", "small_land"}
    assert robust(ocean_rule="sum") == {"two_lead", "three_lead", "start13"}
    with pytest.raises(ValueError):
        nb["apply_criteria"](t, continuity="nonsense")


def test_funnel_counts_are_sequential(nb):
    """The funnel never increases from left to right and its last column is the number of robust tracks of the surface."""
    tr, ids = criteria_tracks()
    flags = nb["select_robust_tracks"](tr, duration_pct=None)
    funnel = nb["funnel_counts"](flags)
    assert list(funnel.loc["Ocean"])[1:] == [7, 6, 5, 4, 2, 1, 1] and funnel.loc["Ocean", "all tracks"] == len(ids)      # ocean class, tropics, non-MCS start, continuous, split / merge, rain peak, duration
    assert all(np.all(np.diff(funnel.loc[s].to_numpy()[1:]) <= 0) for s in funnel.index)
    for s in funnel.index:
        assert funnel.loc[s].iloc[-1] == int((flags["robust"] & (flags["surface"] == s)).sum())


def write_env(path, rows, extra_meta=None, drop=()):
    """Write a small environment Parquet file with the metadata key of the extraction."""
    df = pd.DataFrame(rows)
    df = df.drop(columns=list(drop))
    table = pa.Table.from_pandas(df, preserve_index=False)
    table = table.replace_schema_metadata({"mcs_env": json.dumps({"tracks_file": "/some/tracks.parquet", **(extra_meta or {})})})
    pq.write_table(table, path)


def env_rows(period="2007", tracks=(1, 2), diameters=(200, 400), offsets=(-1.0, 0.0, 1.0)):
    """Rows of a synthetic environment file: prw = 10 * track + offset, rh500 valid-area fraction 0.3 for track 2 at offset 1 (for the mask test)."""
    rows = []
    for tid in tracks:
        for d in diameters:
            for o in offsets:
                rows.append(dict(period=period, local_track=tid, time_offset_hours=np.float32(o), diameter_km=np.int16(d), prw=np.float32(10 * tid + o),
                                 prw_validfrac=np.float32(1.0), rh500=np.float32(50.0 + tid), rh500_validfrac=np.float32(0.3 if (tid == 2 and o == 1.0) else 1.0)))
    return rows


def test_load_env_filters_diameter_masks_validfrac_and_skips_missing_variables(nb, tmp_path):
    """One diameter, circle means with too little valid area become NaN (and are counted), a variable that the file lacks is skipped, the metadata is read."""
    path = tmp_path / "env.parquet"
    write_env(path, env_rows())
    env, info = nb["load_env"]([str(path)], 400, ["prw", "rh500", "q850"], 0.5)
    assert len(env) == 6 and list(env.columns) == ["period", "local_track", "time_offset_hours", "prw", "rh500"]
    assert info["variables"] == ["prw", "rh500"] and info["periods"] == ["2007"] and info["masked"] == {"prw": 0, "rh500": 1}
    assert np.isnan(env.loc[(env.local_track == 2) & (env.time_offset_hours == 1.0), "rh500"].iloc[0]) and env["rh500"].notna().sum() == 5
    assert env["time_offset_hours"].dtype == np.float32
    assert nb["read_env_metadata"](str(path))["tracks_file"] == "/some/tracks.parquet"


def test_load_env_refuses_overlapping_or_unequal_files(nb, tmp_path):
    """The same track and time in two files, different variables in two files and a diameter that is not in the file are errors."""
    a, b, c = tmp_path / "a.parquet", tmp_path / "b.parquet", tmp_path / "c.parquet"
    write_env(a, env_rows())
    write_env(b, env_rows())
    with pytest.raises(ValueError, match="overlap"):
        nb["load_env"]([str(a), str(b)], 400, ["prw"], 0.5)
    write_env(c, env_rows(period="2008"), drop=["rh500", "rh500_validfrac"])
    with pytest.raises(ValueError, match="first file"):
        nb["load_env"]([str(a), str(c)], 400, ["prw", "rh500"], 0.5)
    with pytest.raises(ValueError, match="no row"):
        nb["load_env"]([str(a)], 600, ["prw"], 0.5)
    env, _ = nb["load_env"]([str(a)], 200, ["prw"], 0.5)
    assert len(env) == 6


def test_expand_files_and_load_tracks(nb, tmp_path):
    """Wildcards are expanded and sorted, a pattern without a match is an error; tracks are read only for the requested periods and must have every column."""
    for year in ("2007", "2008"):
        write_env(tmp_path / f"mcs_env_OBS_{year}.parquet", env_rows(period=year))
    files = nb["expand_files"]([str(tmp_path / "mcs_env_OBS_20??.parquet")])
    assert [Path(f).name for f in files] == ["mcs_env_OBS_2007.parquet", "mcs_env_OBS_2008.parquet"]
    with pytest.raises(FileNotFoundError):
        nb["expand_files"]([str(tmp_path / "nothing_*.parquet")])
    tracks = pd.concat([make_track(1, OK, period="2007"), make_track(1, OK, period="2008"), make_track(2, OK, period="2008")], ignore_index=True)
    path = tmp_path / "tracks.parquet"
    tracks.to_parquet(path)
    got = nb["load_tracks"](str(path), ["2008"])
    assert set(got["period"]) == {"2008"} and got["local_track"].nunique() == 2 and set(got.columns) == set(nb["TRACK_COLUMNS"])
    tracks.drop(columns=["total_rain"]).to_parquet(path)
    with pytest.raises(ValueError, match="total_rain"):
        nb["load_tracks"](str(path), ["2008"])


def test_composite_statistics_counts_and_masking(nb):
    """Median, quartiles, mean, valid counts and tracks per bin equal numpy on a small table; a bin with too few valid values has no statistics but keeps its counts."""
    values = {-3.0: [1.0, 2.0, 3.0, 4.0], 0.0: [10.0, np.nan, 30.0, 50.0], 3.0: [5.0, np.nan, np.nan, np.nan]}
    rows = [dict(time_offset_hours=np.float32(o), prw=v, rh500=2 * v) for o, vs in values.items() for v in vs]
    comp = nb["composite_by_offset"](pd.DataFrame(rows), ["prw", "rh500"], min_count=2)
    prw = comp[comp["variable"] == "prw"].set_index("time_offset_hours")
    v0 = np.array([10.0, 30.0, 50.0])
    assert np.isclose(prw.loc[0.0, "median"], 30.0) and np.isclose(prw.loc[0.0, "mean"], 30.0)
    assert np.isclose(prw.loc[0.0, "q25"], np.quantile(v0, 0.25)) and np.isclose(prw.loc[0.0, "q75"], np.quantile(v0, 0.75))
    assert prw.loc[0.0, "count"] == 3 and prw.loc[0.0, "n_tracks"] == 4
    assert np.isclose(prw.loc[-3.0, "q75"], np.quantile([1, 2, 3, 4], 0.75))
    assert prw.loc[3.0, "count"] == 1 and prw.loc[3.0, "n_tracks"] == 4 and np.isnan(prw.loc[3.0, "median"])
    rh = comp[comp["variable"] == "rh500"].set_index("time_offset_hours")
    assert np.isclose(rh.loc[-3.0, "median"], 5.0)


def test_env_of_selected_keeps_only_robust_tracks_of_the_surface(nb):
    """The join of environment rows and flags keeps the rows of the robust tracks of the requested surface only."""
    tr, ids = criteria_tracks()
    flags = nb["select_robust_tracks"](tr, duration_pct=None)
    env = pd.DataFrame(env_rows(tracks=tuple(ids.values()), diameters=(400,))).drop(columns=["diameter_km", "prw_validfrac", "rh500_validfrac"])
    ocean = nb["env_of_selected"](env, flags, "Ocean")
    land = nb["env_of_selected"](env, flags, "Land")
    assert set(ocean["local_track"]) == {ids["ok_ocean"]} and set(land["local_track"]) == {ids["ok_land"]} and len(ocean) == 3


def test_relative_frequency(nb):
    """Percent of all valid values per bin; NaN is ignored, values outside the range count in the total only."""
    centers, freq, n = nb["relative_frequency"]([0.5, 0.5, 1.5, 2.5, 9.0, np.nan], 0.0, 3.0, 3)
    assert n == 5 and np.allclose(centers, [0.5, 1.5, 2.5]) and np.allclose(freq, [40.0, 20.0, 20.0])


def test_kde_frequency_is_the_smooth_version_of_relative_frequency(nb):
    """Percent per bin width like relative_frequency: about 100 % over a wide range, follows the histogram of a large sample, is smoother for a small one, NaN without data."""
    rng = np.random.default_rng(3)
    lo, hi, nbins = -5.0, 5.0, 40
    big = rng.normal(0.0, 1.0, 200_000)
    x, kde, n = nb["kde_frequency"](big, lo, hi, nbins, 0.15)
    width = (hi - lo) / nbins
    assert n == big.size and x.size == nbins * 10 and x[0] == lo and x[-1] == hi
    assert abs(kde.sum() * (x[1] - x[0]) / width - 100.0) < 1.0                       # the integral over the range, in bin widths, is the whole sample
    centers, hist, _ = nb["relative_frequency"](big, lo, hi, nbins)
    assert np.max(np.abs(np.interp(centers, x, kde) - hist)) < 0.4                       # the same numbers as the histogram (percent per bin), within the smoothing
    # A small sample: the histogram is noisy, the KDE is smoother (total variation relative to the maximum)
    small = big[:300]
    _, kde_small, _ = nb["kde_frequency"](small, lo, hi, nbins, 0.4)
    _, hist_small, _ = nb["relative_frequency"](small, lo, hi, nbins)
    variation = lambda y: np.abs(np.diff(y)).sum() / y.max()                         # noqa: E731
    assert variation(kde_small) < 0.8 * variation(hist_small)
    # NaN is ignored; no valid value gives NaN everywhere and n = 0
    assert nb["kde_frequency"]([1.0, 2.0, np.nan], lo, hi, nbins, 0.4)[2] == 2
    _, empty, n_empty = nb["kde_frequency"]([np.nan], lo, hi, nbins, 0.4)
    assert n_empty == 0 and np.isnan(empty).all()


def test_load_env_applies_scales_after_the_mask(nb, tmp_path):
    """A factor per variable (Qv850 to g/kg); variables that are not listed or not in the file are untouched; the mask counts are the same."""
    path = tmp_path / "env.parquet"
    write_env(path, env_rows())
    plain, info_plain = nb["load_env"]([str(path)], 400, ["prw", "rh500"], 0.5)
    scaled, info = nb["load_env"]([str(path)], 400, ["prw", "rh500"], 0.5, scales={"prw": 1000.0, "q850": 5.0})
    assert np.allclose(scaled["prw"], 1000.0 * plain["prw"]) and np.array_equal(scaled["rh500"].to_numpy(), plain["rh500"].to_numpy(), equal_nan=True)
    assert info["masked"] == info_plain["masked"] == {"prw": 0, "rh500": 1}


def test_variables_have_kde_bandwidths_and_qv850_is_in_g_per_kg(nb):
    """Every variable has a positive bandwidth smaller than a tenth of its range; Qv850 is converted to g/kg with a range of simple numbers."""
    for name, spec in nb["VARIABLES"].items():
        lo, hi = spec["pdf_range"]
        assert 0 < spec["kde_bw"] < (hi - lo) / 10, name
    q = nb["VARIABLES"]["q850"]
    assert q["unit"] == "g/kg" and q["scale"] == 1000.0 and q["pdf_range"] == (5, 18)
    assert all("scale" not in s for k, s in nb["VARIABLES"].items() if k != "q850")


def test_plot_distributions_draws_the_kde_or_the_histogram(nb):
    """PDF_STYLE 'kde' draws 10 points per bin, 'histogram' one per bin; both are smooth curves of the same sources."""
    import matplotlib.pyplot as plt
    rng = np.random.default_rng(5)
    init = {("obs", "Ocean"): pd.DataFrame({v: rng.normal(np.mean(s["pdf_range"]), (s["pdf_range"][1] - s["pdf_range"][0]) / 8, 500) for v, s in nb["VARIABLES"].items()})}
    sources = {"obs": nb["SOURCES"]["obs"]}
    try:
        for style, points in (("kde", nb["PDF_BINS"] * 10), ("histogram", nb["PDF_BINS"])):
            nb["PDF_STYLE"] = style
            fig = nb["plot_distributions"](init, "Ocean", sources=sources)
            assert [len(ax.lines[0].get_xdata()) for ax in fig.axes[:6]] == [points] * 6
            plt.close(fig)
    finally:
        nb["PDF_STYLE"] = "kde"


def test_figures_are_made_and_saved_as_24_bit_png(nb, tmp_path):
    """The three figure functions run on synthetic composites (a source without some variables included) and the saved PNG has no alpha channel."""
    from PIL import Image
    rng = np.random.default_rng(1)
    sources = {k: nb["SOURCES"][k] for k in ("obs", "100km")}
    tables, init, nsel = {}, {}, {}
    for key in sources:
        variables = list(nb["VARIABLES"]) if key == "obs" else ["prw", "rh850", "omega500"]            # the 100-km run lacks some variables
        rows = [dict(time_offset_hours=np.float32(o), **{v: rng.normal(1.0, 0.1) * (1 + o / 100) for v in variables}) for o in range(-24, 25, 3) for _ in range(40)]
        df = pd.DataFrame(rows)
        for surface in ("Ocean", "Land"):
            comp = nb["composite_by_offset"](df, variables, min_count=30)
            comp.insert(0, "surface", surface)
            tables[key] = pd.concat([tables[key], comp]) if key in tables else comp
            init[(key, surface)] = df[df["time_offset_hours"] == 0][variables].assign(period="2007", local_track=1)
            nsel[(key, surface)] = 40
    distributions = nb["plot_distributions"](init, "Ocean", sources=sources)
    shaded = nb["plot_evolution"](tables, "Ocean", sources=sources, nsel=nsel)
    mean_only = nb["plot_evolution"](tables, "Land", stat="mean", band_source=None, sources=sources, nsel=nsel)
    overlay = nb["plot_surface_overlay"](tables, ["obs", "100km"])
    for fig in (distributions, shaded, mean_only, overlay):
        path = nb["save_figure"](fig, "test.png", directory=str(tmp_path), dpi_out=60)
        assert Image.open(path).mode == "RGB"
    # All figures: a dotted grid (the style the user set in the notebook) drawn above the shaded band (zorder 1) and below the data lines (zorder 3 and above)
    for fig in (distributions, shaded, mean_only, overlay):
        ax = fig.axes[0]
        assert ax.get_axisbelow() == "line" and ax.xaxis.get_gridlines()[0].get_linestyle() == ":" and ax.yaxis.get_gridlines()[0].get_linestyle() == ":"
        assert all(c.get_zorder() < ax.xaxis.get_zorder() < min(line.get_zorder() for line in ax.lines if line.get_marker() == "o") for c in ax.collections)
    assert shaded.axes[0].collections and not mean_only.axes[0].collections                      # the shaded figure has the band, the mean figure none
    key_numbers = nb["key_numbers"](tables, "Ocean", [0.0, 6.0])
    assert key_numbers.shape == (len(nb["VARIABLES"]), 4) and key_numbers.loc["q850"].notna().sum() == 2       # q850 only in the first source
