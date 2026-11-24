"""Tests of the zonal-mean panel of ``Notebooks/plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb``: one legend entry for the OBS line and its band, the legend placed at the
right edge of the bias colorbar with the asked number of columns, the fixed upper y limit, and the per-variable settings of the configuration cell.

The notebook is self-contained, so the tests run its cells tagged ``config`` / ``functions`` (imports, configuration, function definitions: no cell that reads data)
and call the functions on small synthetic fields.

Run from the scream folder:  python -m pytest tests/test_rainmap_notebook.py
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
NOTEBOOK = Path(os.environ.get("RAINMAP_NOTEBOOK", Path(__file__).resolve().parents[1] / "Notebooks" / "plot_global_mcs_climo_rainmap_scream_e3sm_obs.ipynb"))
LAT = np.arange(-59.5, 60.0, 1.0)
LON = np.arange(-179.5, 180.0, 1.0)


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


def zonal_lines(with_band=True):
    """Seven synthetic zonal-mean lines on 2 degree bins like the notebook's sources; the first (OBS) has an interquartile band."""
    centers = np.arange(-59.0, 60.0, 2.0)
    labels = [("OBS (2007-2017)", "black"), ("3-km CTL (1995-2005)", "tomato"), ("3-km TUNE (2019-08 to 2021-02)", "firebrick"), ("13-km CTL (1995-2005)", "deepskyblue"),
              ("13-km TUNE (1995-2005)", "royalblue"), ("25-km (2009-2011)", "forestgreen"), ("100-km (2009-2020)", "limegreen")]
    lines = []
    for k, (label, color) in enumerate(labels):
        values = 30.0 - 0.006 * centers ** 2 + 1.5 * k
        line = dict(lat=centers, values=values, label=label, color=color, linewidth=3.0 if k == 0 else 1.8, linestyle="-")
        if k == 0 and with_band:
            line.update(band=(values - 1.5, values + 1.5), band_color="gray", band_alpha=0.35)
        lines.append(line)
    return lines


def make_figure(nb, ncol_legend, zonal_ymax=None, lines=None):
    """plot_obs_and_bias_maps on synthetic fields: the observation, two biases and the zonal-mean panel right of the observation.

    Returns:
        (fig, ax_zonal, colorbar axes of the bias, the lines).
    """
    lines = lines or zonal_lines()
    obs = xr.DataArray(np.tile(30.0 + 20.0 * np.cos(np.deg2rad(LAT))[:, None], (1, LON.size)), dims=("lat", "lon"), coords={"lat": LAT, "lon": LON})
    fig = nb["plot_obs_and_bias_maps"](obs, [obs * 0.0 + 1.0, obs * 0.0 - 2.0], ["(a) OBS", "(c) A", "(d) B"], [0, 10, 20, 30, 40, 50], [-4, -2, 0, 2, 4],
                                       nb["get_cmap"]("YlGnBu"), nb["get_cmap"]("BrBG"), "value", "Model - OBS (unit)", zonal_lines=lines, zonal_title="(b) Zonal mean",
                                       zonal_ylabel="unit", ncol=2, zonal_slot=1, figwidth=10, zonal_legend_ncol=ncol_legend, zonal_ymax=zonal_ymax)
    ax_z = [ax for ax in fig.axes if ax.get_title(loc="left") == "(b) Zonal mean"][0]
    cax = [ax for ax in fig.axes if ax.get_ylabel() == "Model - OBS (unit)"][0]
    return fig, ax_z, cax, lines


def test_draw_zonal_panel_one_entry_for_the_obs_line_and_its_band(nb):
    """A line with a band is one entry (the tuple band + line) labelled like the line; the other sources are plain lines; no band, no tuple."""
    import matplotlib.pyplot as plt
    lines = zonal_lines()
    fig, ax = plt.subplots()
    handles, labels = nb["draw_zonal_panel"](ax, lines, legend_ncol=1)
    assert labels == [ln["label"] for ln in lines] and labels[0] == "OBS (2007-2017)"
    assert isinstance(handles[0], tuple) and len(handles[0]) == 2 and not any(isinstance(h, tuple) for h in handles[1:])
    assert [t.get_text() for t in ax.get_legend().get_texts()] == labels
    plt.close(fig)
    fig, ax = plt.subplots()
    handles, _ = nb["draw_zonal_panel"](ax, zonal_lines(with_band=False))
    assert not any(isinstance(h, tuple) for h in handles)
    plt.close(fig)


def test_draw_zonal_panel_upper_y_limit(nb):
    """ylim_top sets the upper limit exactly; without it the limit is the highest line (band) plus the headroom; a quantity that is never negative starts at 0."""
    import matplotlib.pyplot as plt
    lines = zonal_lines()
    top_data = max(np.nanmax(ln["values"]) for ln in lines)
    top_band = np.nanmax(lines[0]["band"][1])
    fig, ax = plt.subplots()
    nb["draw_zonal_panel"](ax, lines, ylim_top=100.0, draw_legend=False)
    assert ax.get_ylim() == (0.0, 100.0)
    plt.close(fig)
    fig, ax = plt.subplots()
    nb["draw_zonal_panel"](ax, lines, headroom=0.25, draw_legend=False)
    top = max(top_data, top_band)
    assert ax.get_ylim()[0] == 0.0 and np.isclose(ax.get_ylim()[1], top * 1.25)
    plt.close(fig)


def test_extend_ylim_for_legend_raises_the_limit_only_when_a_line_touches_the_legend(nb):
    """A legend over the lines needs a higher y limit (and then touches nothing); a legend over empty space needs none."""
    import matplotlib.pyplot as plt
    lines = zonal_lines()
    handles = [plt.Line2D([0], [0], color=ln["color"]) for ln in lines]
    fig, ax = plt.subplots(figsize=(6, 3))
    nb["draw_zonal_panel"](ax, lines, draw_legend=False, headroom=0.0)
    over_lines = ax.legend(handles, [ln["label"] for ln in lines], loc="upper center", ncol=1)
    top_before = ax.get_ylim()[1]
    assert nb["extend_ylim_for_legend"](ax, over_lines, lines) > 0 and ax.get_ylim()[1] > top_before
    assert nb["extend_ylim_for_legend"](ax, over_lines, lines) == 0
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 3))
    nb["draw_zonal_panel"](ax, lines, draw_legend=False, headroom=3.0)
    empty = ax.legend(handles, [ln["label"] for ln in lines], loc="upper right", ncol=1)
    top_before = ax.get_ylim()[1]
    assert nb["extend_ylim_for_legend"](ax, empty, lines) == 0 and ax.get_ylim()[1] == top_before
    plt.close(fig)


@pytest.mark.parametrize("ncol_legend", [1, 2, 3])
def test_zonal_legend_is_aligned_with_the_colorbar_and_touches_no_line(nb, ncol_legend):
    """The upper right corner of the zonal legend is at the right edge of the bias colorbar (with its labels), the legend has the asked number of columns and one entry
    per source (the OBS band is not an entry of its own), and no line or band reaches into it."""
    import matplotlib.pyplot as plt
    fig, ax_z, cax, lines = make_figure(nb, ncol_legend)
    renderer = fig.canvas.get_renderer()
    legend = ax_z.get_legend()
    assert abs(legend.get_window_extent(renderer).x1 - cax.get_tightbbox(renderer).x1) < 2.0
    texts = legend.get_texts()
    assert [t.get_text() for t in texts] == [ln["label"] for ln in lines]
    assert len({round(t.get_window_extent(renderer).x0) for t in texts}) == ncol_legend
    assert nb["extend_ylim_for_legend"](ax_z, legend, lines) == 0
    plt.close(fig)


def test_zonal_ymax_is_the_starting_limit(nb):
    """With zonal_ymax the y axis ends at that value when nothing touches the legend, and is raised above it when a line does; without it the limit follows the lines."""
    import matplotlib.pyplot as plt
    fig, ax_z, _, lines = make_figure(nb, 3, zonal_ymax=100.0)
    assert ax_z.get_ylim() == (0.0, 100.0)
    plt.close(fig)
    # Lines that reach 95 of 100 touch the legend at the top: the limit goes above 100 and the legend is free
    high = zonal_lines()
    for ln in high:
        ln["values"] = ln["values"] + 50.0
        if ln.get("band") is not None:
            ln["band"] = (ln["band"][0] + 50.0, ln["band"][1] + 50.0)
    fig, ax_z, _, _ = make_figure(nb, 3, zonal_ymax=100.0, lines=high)
    assert ax_z.get_ylim()[1] > 100.0
    assert nb["extend_ylim_for_legend"](ax_z, ax_z.get_legend(), high) == 0
    plt.close(fig)
    fig, ax_z, _, lines = make_figure(nb, 3)
    assert ax_z.get_ylim()[1] < 100.0
    plt.close(fig)


def test_configuration_of_the_zonal_panels(nb):
    """2 columns for the cloud frequency and the precipitation, 3 for the fraction, which starts at a y maximum of 100; every variable to plot has a legend setting, and the
    figure cell passes both settings to plot_obs_and_bias_maps and no longer gives the OBS band an entry of its own."""
    assert nb["zonal_legend_ncol_by_var"] == {"cloudfreq": 2, "mcspcp": 2, "pcpfrac": 3}
    assert nb["zonal_ymax_by_var"] == {"pcpfrac": 100.0}
    assert set(nb["VARIABLES_TO_PLOT"]) <= set(nb["zonal_legend_ncol_by_var"])
    assert nb["show_period_in_legend"] is True and nb["SOURCES"]["obs"]["label"] == "OBS" and nb["SOURCES"]["obs"]["period"] == "2007-2017"
    cells = json.loads(NOTEBOOK.read_text())["cells"]
    figure_cell = "".join([c["source"] for c in cells if c["cell_type"] == "code" and "letters = " in "".join(c["source"])][0])
    assert "zonal_legend_ncol_by_var.get(vkey" in figure_cell and "zonal_ymax=zonal_ymax_by_var.get(vkey)" in figure_cell and "band_label" not in figure_cell
