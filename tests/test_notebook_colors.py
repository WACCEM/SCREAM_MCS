"""Tests that the evaluation notebooks take their source colors from one color dictionary and that the dictionaries agree.

Every notebook with the SCREAM / E3SM / OBS sources has a dictionary ``COLORS`` in its configuration cell, its ``SOURCES`` take their colors from it, and the colors of
the same source are the same in all notebooks (so a figure of one notebook can be read next to a figure of another). OBS is black in the line plots; in the box-whisker
plots of the track-statistics notebook it is dimgray (``BOX_COLORS``).

Run from the scream folder:  python -m pytest tests/test_notebook_colors.py
"""

import json
from pathlib import Path

import matplotlib.colors as mcolors
import pytest

NOTEBOOKS = Path(__file__).resolve().parents[1] / "Notebooks"
# notebook -> {key of its COLORS: the standard name of the source}
STANDARD = {
    "plot_tropical_mcs_trackstats_all_sources": {"obs": "obs", "scream3_ctl": "3km_ctl", "scream3_tune": "3km_tune", "scream13_ctl": "13km_ctl", "scream13_tune": "13km_tune",
                                                 "e3sm25": "25km", "e3sm100": "100km"},
    "plot_global_mcs_climo_rainmap_scream_e3sm_obs": {"obs": "obs", "scream3_ctl": "3km_ctl", "scream3_tune": "3km_tune", "scream13_ctl": "13km_ctl", "scream13_tune": "13km_tune",
                                                      "e3sm25": "25km", "e3sm100": "100km"},
    "plot_global_env_climo_scream_e3sm_obs": {"obs": "obs", "scream3_ctl": "3km_ctl", "scream3_tune": "3km_tune", "scream13_ctl": "13km_ctl", "scream13_tune": "13km_tune",
                                              "e3sm25": "25km", "e3sm100": "100km"},
    "analyze_mcs_env_composites_land_ocean": {"obs": "obs", "3km_CTL": "3km_ctl", "3km_TUNE": "3km_tune", "13km_CTL": "13km_ctl", "13km_TUNE": "13km_tune", "25km": "25km", "100km": "100km"},
    "plot_mcs_heavyrain_sensitivity_e3sm": {"obs": "obs", "ne120": "25km", "ne30": "100km"},
}


def config_namespace(name):
    """The namespace after running the configuration cell of a notebook (the cell that says 'CONFIGURATION (the only cell to edit)')."""
    data = json.loads((NOTEBOOKS / f"{name}.ipynb").read_text())
    cells = [c for c in data["cells"] if c["cell_type"] == "code" and "CONFIGURATION (the only cell to edit)" in "".join(c["source"])]
    assert len(cells) == 1, name
    ns = {"__name__": "config"}
    exec(compile("".join(cells[0]["source"]), name, "exec"), ns)
    return ns


@pytest.fixture(scope="module")
def configs():
    """name -> configuration namespace of every notebook."""
    return {name: config_namespace(name) for name in STANDARD}


def test_every_notebook_has_a_dictionary_of_valid_colors_for_its_sources(configs):
    """COLORS has a valid matplotlib color for every key listed for the notebook, and the sources of the notebook take theirs from it."""
    for name, ns in configs.items():
        colors = ns["COLORS"]
        assert set(STANDARD[name]) <= set(colors) and all(mcolors.is_color_like(c) for c in colors.values()), name
        sources = ns.get("SOURCES") or {"obs": ns["OBS"], **ns["MODELS"]}
        for key, cfg in sources.items():
            assert cfg["color"] == colors[key], (name, key)


def test_the_same_source_has_the_same_color_in_every_notebook(configs):
    """Compared by the standard name of the source: OBS black, and every simulation the same color in all notebooks."""
    by_standard = {}
    for name, ns in configs.items():
        for key, standard in STANDARD[name].items():
            by_standard.setdefault(standard, {})[name] = ns["COLORS"][key]
    for standard, per_notebook in by_standard.items():
        assert len(set(per_notebook.values())) == 1, (standard, per_notebook)
    assert set(by_standard["obs"].values()) == {"black"}
    # The colors of a pair of simulations are different, the pairs are different from each other
    palette = {s: next(iter(v.values())) for s, v in by_standard.items()}
    assert len(set(palette.values())) == len(palette)


def test_obs_is_dimgray_only_in_the_boxes_of_the_track_statistics_notebook(configs):
    """BOX_COLORS differs from COLORS only for OBS (dimgray), the label-keyed color dictionaries of the notebook follow."""
    ns = configs["plot_tropical_mcs_trackstats_all_sources"]
    assert ns["COLORS"]["obs"] == "black" and ns["BOX_COLORS"]["obs"] == "dimgray"
    assert {k for k in ns["COLORS"] if ns["COLORS"][k] != ns["BOX_COLORS"][k]} == {"obs"}
    assert ns["SOURCE_COLORS"]["OBS"] == "black" and ns["SOURCE_COLORS_BOX"]["OBS"] == "dimgray"
    assert all(ns["SOURCE_COLORS"][label] == ns["SOURCE_COLORS_BOX"][label] for label in ns["SOURCE_ORDER"] if label != "OBS")
