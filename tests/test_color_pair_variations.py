"""Tests of ``scripts/plot_color_pair_variations.py`` (the ten color variations for the SCREAM / E3SM source pairs): the color table, the synthetic data, the figures.

Run from the scream folder:  python -m pytest tests/test_color_pair_variations.py
"""

import importlib.util
from pathlib import Path

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
import pytest

matplotlib.use("Agg")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "plot_color_pair_variations.py"


@pytest.fixture(scope="module")
def cp():
    """The script as a module (the script is not a package)."""
    spec = importlib.util.spec_from_file_location("plot_color_pair_variations", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ten_variations_of_three_distinct_pairs(cp):
    """Ten variations, each with three (base, deeper) pairs of valid matplotlib colors, three different families, no color used twice and none equal to the OBS colors."""
    assert len(cp.VARIATIONS) == 10
    for i, v in enumerate(cp.VARIATIONS, 1):
        colors = [c for pair in v["pairs"] for c in pair]
        assert len(v["pairs"]) == 3 and all(len(p) == 2 for p in v["pairs"]) and len(v["families"]) == 3 and len(set(v["families"])) == 3, i
        assert all(mcolors.is_color_like(c) for c in colors), (i, colors)
        assert len(set(colors)) == 6 and not {cp.OBS_LINE_COLOR, cp.OBS_BOX_COLOR} & set(colors), (i, colors)
    # No two variations are the same set of pairs
    assert len({tuple(v["pairs"]) for v in cp.VARIATIONS}) == 10


def test_obs_is_black_in_lines_and_dimgray_in_boxes(cp):
    """Line colors and box colors of OBS differ (black / dimgray), every simulation has one color for both, the legend names are the color names."""
    line, box, names = cp.variation_colors(cp.VARIATIONS[0])
    labels = [label for _, label in cp.all_sources()]
    assert labels == ["OBS", "3-km CTL", "3-km TUNE", "13-km CTL", "13-km TUNE", "25-km", "100-km"]
    assert line["OBS"] == "black" and box["OBS"] == "dimgray" and "black lines" in names["OBS"] and "dimgray box" in names["OBS"]
    assert all(line[k] == box[k] == names[k] for k in labels[1:])
    # The first member of a pair is the base tone (lighter), the second the deeper tone
    for first, second in cp.VARIATIONS[0]["pairs"]:
        assert cp.lab_of(first)[0] > cp.lab_of(second)[0]


def test_color_metrics_are_sensible(cp):
    """L* in a range that is neither black nor white, positive color differences; a color against itself would be 0, against another family clearly different."""
    for v in cp.VARIATIONS:
        m = cp.color_metrics(v)
        assert all(25 < L < 95 for L in m["L"].values())
        assert min(m["within"]) > 10 and m["between"] > 15 and m["to_black"] > 25 and m["to_dimgray"] > 15, m
    assert cp.lab_of("black")[0] == pytest.approx(0.0, abs=0.01) and cp.lab_of("white")[0] == pytest.approx(100.0, abs=0.01)


def test_synthetic_data_have_the_shapes_of_the_real_quantities(cp):
    """Seven sources in the box data, the two duration bins of both surfaces in the lines, correlated lifetime and rain volume; the same seed gives the same data."""
    data = cp.make_synthetic(seed=3, n_box=200, n_kde=300)
    assert set(data["box"]["source"]) == {label for _, label in cp.all_sources()} and len(data["box"]) == 7 * 2 * 200
    assert (data["box"]["ccs_area"] > 0).all()
    assert len(data["lines"]) == 7 * 2 * 2 and all(t.size == y.size == 49 and (y >= 0).all() for t, y in data["lines"].values())
    lifetime, volume = data["kde"]["obs"]
    assert lifetime.size == 300 and np.corrcoef(np.log(lifetime), volume)[0, 1] > 0.5
    again = cp.make_synthetic(seed=3, n_box=200, n_kde=300)
    assert np.array_equal(again["kde"]["e3sm100"][0], data["kde"]["e3sm100"][0])


def test_figure_legend_names_every_color_and_the_files_are_24_bit(cp, tmp_path):
    """The legend of a variation figure carries the name of every color, the PNG of the figure and of the overview have no alpha channel."""
    import matplotlib.pyplot as plt
    from PIL import Image
    data = cp.make_synthetic(seed=1, n_box=150, n_kde=250)
    variation = cp.VARIATIONS[1]
    fig = cp.build_variation_figure(2, variation, data)
    legend_text = " ".join(t.get_text() for t in fig.legends[0].get_texts())
    for color in [c for pair in variation["pairs"] for c in pair] + ["black", "dimgray"]:
        assert color in legend_text, color
    assert "Variation 2" in fig._suptitle.get_text() and len(fig.axes) == 6               # box, two line panels, joint + two marginals
    plt.close(fig)
    path = cp.plot_variation(2, variation, data, str(tmp_path), dpi=40)
    overview = cp.plot_overview(str(tmp_path), dpi=40)
    assert Path(path).name == "color_variation_02.png" and Path(overview).name == "color_variations_overview.png"
    assert Image.open(path).mode == "RGB" and Image.open(overview).mode == "RGB"
