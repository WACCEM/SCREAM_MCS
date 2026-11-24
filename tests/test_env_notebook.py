"""Tests of the functions of ``Notebooks/plot_global_env_climo_scream_e3sm_obs.ipynb``: the ERA5 interannual band of the zonal mean and the two fill styles of the maps.

The notebook is self-contained, so the tests run its cells tagged ``functions`` / ``config`` (imports, configuration, function definitions: no cell that reads data)
and call the functions on small synthetic fields in which the answer is recomputed with plain numpy.

Run from the scream folder:  python -m pytest tests/test_env_notebook.py
"""

import json
import os
from pathlib import Path

import matplotlib
import numpy as np
import pytest
import xarray as xr

matplotlib.use("Agg")

# The notebook under test (the environment variable lets a mutated copy be tested to check that the tests can fail)
NOTEBOOK = Path(os.environ.get("ENV_NOTEBOOK", Path(__file__).resolve().parents[1] / "Notebooks" / "plot_global_env_climo_scream_e3sm_obs.ipynb"))
# The 1 degree grid of the monthly files
LAT = np.arange(-89.5, 90.0, 1.0)
LON = np.arange(-179.5, 180.0, 1.0)
YEARS = [2007, 2008, 2009, 2010]
KEEP = (LAT >= -60.0) & (LAT <= 60.0)           # the rows of the latitude band that the notebook keeps (the masks of the notebook have this shape)


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


@pytest.fixture(autouse=True)
def restore_matplotlib_settings():
    """plot_obs_and_bias_maps sets the global font size; restore the settings of matplotlib after every test so that no test depends on the tests that ran before it."""
    with matplotlib.rc_context():
        yield


@pytest.fixture(scope="module")
def months(tmp_path_factory):
    """Synthetic monthly files env_ERA5_1deg_<YYYYMM>.nc of four years (variables prw and hus850; hus850 has a hole that is NaN in every month) and the stored fields.

    Returns:
        (folder, fields): fields[(year, month)] = {'prw': array, 'hus850': array}, float32 like the files.
    """
    folder = tmp_path_factory.mktemp("era5_monthly")
    rng = np.random.default_rng(7)
    base = np.cos(np.deg2rad(LAT))[:, None] * np.ones(LON.size)[None, :]
    fields = {}
    for year in YEARS:
        for month in range(1, 13):
            prw = (20.0 * base * (1 + 0.05 * (year - YEARS[0])) + 0.5 * month + rng.normal(0.0, 1.0, base.shape)).astype("f4")
            hus = (0.01 * base * (1 + 0.1 * (year - YEARS[0])) * (1 + 0.02 * month) + rng.normal(0.0, 0.0005, base.shape)).astype("f4")
            hus[100:110, 50:80] = np.nan
            ds = xr.Dataset({"prw": (("time", "lat", "lon"), prw[None]), "hus850": (("time", "lat", "lon"), hus[None])},
                            coords={"time": [0.0], "lat": LAT, "lon": LON})
            ds.to_netcdf(folder / f"env_ERA5_1deg_{year}{month:02d}.nc")
            fields[(year, month)] = {"prw": prw, "hus850": hus}
    return folder, fields


def zonal_expected(field, valid, bin_deg=2.0, lat_cut=(-60.0, 60.0)):
    """The cos(latitude)-weighted zonal mean in latitude bins, in plain numpy: rows of the bin [lo, hi), finite cells of the valid mask."""
    keep = (LAT >= lat_cut[0]) & (LAT <= lat_cut[1])
    lat, f, ok = LAT[keep], field[keep], valid[keep]
    edges = np.arange(lat_cut[0], lat_cut[1] + 0.5 * bin_deg, bin_deg)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        rows = (lat >= lo) & (lat < hi)
        use = np.isfinite(f[rows]) & ok[rows]
        w = np.cos(np.deg2rad(lat[rows]))[:, None] * np.ones(f.shape[1])[None, :]
        out.append(float((np.where(use, f[rows], 0.0) * w).sum() / (use * w).sum()) if use.any() else np.nan)
    return np.array(out)


def yearly_field(fields, var, scale, month_list):
    """The season mean field of every year, in numpy: scale * the mean over the months (NaN skipped), as the climatology fields are made."""
    return [scale * np.nanmean(np.stack([fields[(y, m)][var].astype(float) for m in month_list]), axis=0) for y in YEARS]


@pytest.mark.parametrize("season, month_list", [("ANN", range(1, 13)), ("JJA", [6, 7, 8])])
def test_obs_zonal_band_matches_numpy(nb, months, season, month_list):
    """Both bands, the yearly zonal means, the season months, the scale and the valid mask agree with a plain numpy recomputation."""
    folder, fields = months
    variables = {"prw": dict(var="prw", scale=1.0), "hus": dict(var="hus850", scale=1000.0)}
    valid_mask = np.ones((LAT.size, LON.size), dtype=bool)
    valid_mask[:, 200:230] = False                                              # a strip that is not used
    valid = {"prw": valid_mask[KEEP], "hus": valid_mask[KEEP]}
    obs_lat = xr.DataArray(LAT[KEEP])
    obs_lon = xr.DataArray(LON)
    band = nb["obs_zonal_band"](variables, valid, str(folder), (YEARS[0], YEARS[-1]), obs_lat, obs_lon, season=season, method="cell_iqr")
    for v, (var, scale) in {"prw": ("prw", 1.0), "hus": ("hus850", 1000.0)}.items():
        stack = np.stack(yearly_field(fields, var, scale, month_list))
        annual = np.array([zonal_expected(f, valid_mask) for f in stack])
        q25, q75 = np.nanpercentile(stack, [25, 75], axis=0)
        cell = (zonal_expected(q25, valid_mask), zonal_expected(q75, valid_mask))
        b = band[v]
        assert b["years"] == YEARS and b["lat"].shape == annual.shape[1:] and np.allclose(b["lat"][:2], [-59.0, -57.0])
        assert np.allclose(b["annual"], annual, equal_nan=True)
        assert np.allclose(b["cell_iqr"][0], cell[0], equal_nan=True) and np.allclose(b["cell_iqr"][1], cell[1], equal_nan=True)
        assert np.allclose(b["zonal_iqr"][0], np.nanpercentile(annual, 25, axis=0), equal_nan=True)
        assert np.allclose(b["zonal_iqr"][1], np.nanpercentile(annual, 75, axis=0), equal_nan=True)
        # The band of the chosen method is the returned q25 / q75, and the two bands are different things
        assert np.array_equal(b["q25"], b["cell_iqr"][0], equal_nan=True) and not np.allclose(b["cell_iqr"][1] - b["cell_iqr"][0], b["zonal_iqr"][1] - b["zonal_iqr"][0])
    # The hole of hus850 is not used: the same result when the hole is also masked in `valid`
    hole = valid_mask.copy()
    hole[100:110, 50:80] = False
    again = nb["obs_zonal_band"](variables, {"prw": valid_mask[KEEP], "hus": hole[KEEP]}, str(folder), (YEARS[0], YEARS[-1]), obs_lat, obs_lon, season=season)
    assert np.allclose(again["hus"]["annual"], band["hus"]["annual"], equal_nan=True)
    # The other method
    zonal = nb["obs_zonal_band"](variables, valid, str(folder), (YEARS[0], YEARS[-1]), obs_lat, obs_lon, season=season, method="zonal_iqr")
    assert np.array_equal(zonal["prw"]["q25"], band["prw"]["zonal_iqr"][0], equal_nan=True)


def test_obs_zonal_band_refuses_wrong_arguments(nb, months):
    """An unknown method and a grid that differs from the common grid are refused."""
    folder, _ = months
    variables = {"prw": dict(var="prw", scale=1.0)}
    obs_lat, obs_lon = xr.DataArray(LAT[(LAT >= -60) & (LAT <= 60)]), xr.DataArray(LON)
    with pytest.raises(ValueError, match="method"):
        nb["obs_zonal_band"](variables, {}, str(folder), (2007, 2008), obs_lat, obs_lon, method="mean")
    with pytest.raises(ValueError, match="differs from the common grid"):
        nb["obs_zonal_band"](variables, {}, str(folder), (2007, 2008), xr.DataArray(LAT[(LAT >= -50) & (LAT <= 50)]), obs_lon)


def test_close_global_grid_adds_one_cyclic_column_at_each_side(nb):
    """A global grid gets the last column in front (lon - 360) and the first at the end (lon + 360); a regional grid is not changed."""
    lon = np.arange(-179.5, 180.0, 1.0)
    values = np.arange(3 * lon.size, dtype=float).reshape(3, lon.size)
    lon_c, values_c = nb["close_global_grid"](lon, values)
    assert lon_c.size == lon.size + 2 and lon_c[0] == -180.5 and lon_c[-1] == 180.5 and np.array_equal(lon_c[1:-1], lon)
    assert np.array_equal(values_c[:, 0], values[:, -1]) and np.array_equal(values_c[:, -1], values[:, 0]) and np.array_equal(values_c[:, 1:-1], values)
    regional_lon, regional_values = lon[100:200], values[:, 100:200]
    same_lon, same_values = nb["close_global_grid"](regional_lon, regional_values)
    assert same_lon is regional_lon and same_values is regional_values
    # A 0..359 grid is global as well
    assert nb["close_global_grid"](np.arange(0.0, 360.0, 1.0), np.zeros((2, 360)))[0].size == 362


def _pixel_at(fig, ax, proj, data_proj, lon, lat):
    """RGB (0-1) of the rendered figure at a longitude and latitude."""
    fig.canvas.draw()
    x, y = proj.transform_point(lon, lat, data_proj)
    px, py = ax.transData.transform((x, y))
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3]
    return img[int(img.shape[0] - py), int(px)] / 255.0


def test_draw_map_panel_fill_styles(nb):
    """contourf returns a QuadContourSet and pcolormesh a QuadMesh; both color the date line (no gap: the cyclic columns of contourf); an unknown style is refused."""
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt
    proj, data_proj = ccrs.Robinson(central_longitude=225), ccrs.PlateCarree()
    lat = np.arange(-59.5, 60.0, 1.0)
    field = xr.DataArray(np.full((lat.size, LON.size), 5.0), dims=("lat", "lon"), coords={"lat": lat, "lon": LON})
    cmap = nb["get_cmap"]("YlGnBu", under="white")
    norm = matplotlib.colors.BoundaryNorm([0, 2, 4, 6, 8], ncolors=cmap.N)
    wanted = np.array(cmap(norm(5.0))[:3])
    for style, cls in (("contourf", matplotlib.contour.QuadContourSet), ("pcolormesh", matplotlib.collections.QuadMesh)):
        fig = plt.figure(figsize=(8, 4), dpi=200)
        ax = fig.add_subplot(1, 1, 1, projection=proj)
        mappable = nb["draw_map_panel"](ax, field, norm, cmap, proj, data_proj, fill_style=style)
        assert isinstance(mappable, cls)
        # Just east of the date line, where the first and the last column of the grid are 1 degree apart
        assert np.allclose(_pixel_at(fig, ax, proj, data_proj, 180.4, 2.0), wanted, atol=0.03), style
        plt.close(fig)
    fig = plt.figure(figsize=(4, 2))
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    with pytest.raises(ValueError, match="fill_style"):
        nb["draw_map_panel"](ax, field, norm, cmap, proj, data_proj, fill_style="hatched")
    plt.close(fig)


# ---------------------------------------------------------------------------------------------------------------------------------
# Zonal-mean legend
# ---------------------------------------------------------------------------------------------------------------------------------
def zonal_lines(nb_ns, with_band=True):
    """Five synthetic zonal-mean lines on 2 degree bins; the first (ERA5) has an interquartile band."""
    centers = np.arange(-59.0, 60.0, 2.0)
    lines = []
    for k, (label, color) in enumerate([("ERA5 (2007-2017)", "black"), ("3-km CTL (1995-2005)", "tomato"), ("3-km TUNE (2019-08 to 2021-02)", "firebrick"),
                                        ("25-km (2009-2011)", "forestgreen"), ("100-km (2009-2020)", "limegreen")]):
        values = 40.0 - 0.01 * centers ** 2 + 2.0 * k
        line = dict(lat=centers, values=values, label=label, color=color, linewidth=3.0 if k == 0 else 1.8, linestyle="-")
        if k == 0 and with_band:
            line.update(band=(values - 1.5, values + 1.5), band_color="gray", band_alpha=0.35)
        lines.append(line)
    return lines


def test_draw_zonal_panel_gives_one_legend_entry_per_source(nb):
    """A line with a band is one entry (the tuple band + line); the labels are the labels of the lines; the legend of the axes has one text per source."""
    import matplotlib.pyplot as plt
    lines = zonal_lines(nb)
    fig, ax = plt.subplots()
    handles, labels = nb["draw_zonal_panel"](ax, lines, legend_ncol=1)
    assert labels == [ln["label"] for ln in lines] and isinstance(handles[0], tuple) and len(handles[0]) == 2 and not any(isinstance(h, tuple) for h in handles[1:])
    assert [t.get_text() for t in ax.get_legend().get_texts()] == labels
    plt.close(fig)
    fig, ax = plt.subplots()
    handles, _ = nb["draw_zonal_panel"](ax, zonal_lines(nb, with_band=False))
    assert not any(isinstance(h, tuple) for h in handles)
    plt.close(fig)


def test_extend_ylim_for_legend_raises_the_limit_only_when_a_line_touches_the_legend(nb):
    """A legend over the lines needs a higher y limit (and then touches nothing); a legend over empty space needs none."""
    import matplotlib.pyplot as plt
    lines = zonal_lines(nb)
    fig, ax = plt.subplots(figsize=(6, 3))
    nb["draw_zonal_panel"](ax, lines, draw_legend=False, headroom=0.0)
    handles = [plt.Line2D([0], [0], color=ln["color"]) for ln in lines]
    over_lines = ax.legend(handles, [ln["label"] for ln in lines], loc="upper center", ncol=1)             # the highest lines are at the top center
    top_before = ax.get_ylim()[1]
    steps = nb["extend_ylim_for_legend"](ax, over_lines, lines)
    assert steps > 0 and ax.get_ylim()[1] > top_before
    assert nb["extend_ylim_for_legend"](ax, over_lines, lines) == 0                                         # nothing touches it any more
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 3))
    nb["draw_zonal_panel"](ax, lines, draw_legend=False, headroom=3.0)
    empty = ax.legend(handles, [ln["label"] for ln in lines], loc="upper right", ncol=1)
    top_before = ax.get_ylim()[1]
    assert nb["extend_ylim_for_legend"](ax, empty, lines) == 0 and ax.get_ylim()[1] == top_before
    plt.close(fig)


@pytest.mark.parametrize("ncol_legend", [1, 3])
def test_zonal_legend_is_aligned_with_the_colorbar_and_touches_no_line(nb, ncol_legend):
    """The upper right corner of the zonal legend is at the right edge of the bias colorbar (with its labels), the legend has the asked number of columns and one
    entry per source (the band is not an entry of its own), and no line or band reaches into it."""
    import matplotlib.pyplot as plt
    lat = np.arange(-59.5, 60.0, 1.0)
    obs = xr.DataArray(np.tile(30.0 + 20.0 * np.cos(np.deg2rad(lat))[:, None], (1, LON.size)), dims=("lat", "lon"), coords={"lat": lat, "lon": LON})
    biases = [obs * 0.0 + 1.0, obs * 0.0 - 2.0]
    levels, bias_levels = [0, 10, 20, 30, 40, 50], [-4, -2, 0, 2, 4]
    lines = zonal_lines(nb)
    fig = nb["plot_obs_and_bias_maps"](obs, biases, ["(a) ERA5", "(c) A", "(d) B"], levels, bias_levels, nb["get_cmap"]("YlGnBu"), nb["get_cmap"]("BrBG"), "value", "Model - ERA5 (unit)",
                                       zonal_lines=lines, zonal_title="(b) Zonal mean", zonal_ylabel="unit", ncol=2, zonal_slot=1, figwidth=10, zonal_legend_ncol=ncol_legend)
    renderer = fig.canvas.get_renderer()
    ax_z = [ax for ax in fig.axes if ax.get_title(loc="left") == "(b) Zonal mean"][0]
    cax = [ax for ax in fig.axes if ax.get_ylabel() == "Model - ERA5 (unit)"][0]
    legend = ax_z.get_legend()
    assert abs(legend.get_window_extent(renderer).x1 - cax.get_tightbbox(renderer).x1) < 2.0
    texts = legend.get_texts()
    assert [t.get_text() for t in texts] == [ln["label"] for ln in lines]
    assert len({round(t.get_window_extent(renderer).x0) for t in texts}) == ncol_legend
    assert nb["extend_ylim_for_legend"](ax_z, legend, lines) == 0
    plt.close(fig)
