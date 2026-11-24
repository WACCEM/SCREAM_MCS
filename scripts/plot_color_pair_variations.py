#!/usr/bin/env python
"""Ten variations of source colors for the SCREAM / E3SM evaluation figures, on synthetic data that mimic the real plots.

The evaluation compares one observation (OBS) with three PAIRS of simulations: SCREAM 3-km CTL / TUNE, SCREAM 13-km CTL / TUNE and E3SM 25-km / 100-km. The two
simulations of a pair should be in the same color family (the first, CTL or 25-km, in the base tone, the second in a deeper tone) and different pairs in distinct
families, so that a reader sees at once which lines belong together. OBS stays black in the line plots and is dimgray in the box plots (a black box hides its
own black median line).

For every variation (the list VARIATIONS) one figure with the plotting recipes of ``Notebooks/plot_tropical_mcs_trackstats_all_sources.ipynb``:

  (a) grouped notched box-whisker plot of a lifetime maximum (CCS area, logarithmic axis) for Land and Ocean, whiskers at the 5th / 95th percentile, black medians,
      white mean markers (``sns.boxplot``);
  (b), (c) composite life-cycle lines for land and ocean without shading, the 22-26 h duration bin solid and the 10-14 h bin dashed (OBS line width 4, the others 3);
  (d) joint KDE of the lifetime against the total rain volume with the marginal KDEs and the regression lines: OBS as filled gray contours, the simulations as
      colored contour lines at the same levels.

The legend of every figure names the colors ("3-km CTL (deepskyblue)"). All variations use the same synthetic data, so only the colors differ. A last figure, the
overview sheet, lists the ten variations as swatches with the lightness L* of every color and the CIEDE2000 color differences (about 10 and more is easy to tell
apart, below 5 is hard) within each pair, between the families and to the OBS colors.

Example:
    python plot_color_pair_variations.py --outdir /pscratch/sd/f/feng045/SCREAM-decadal/figures_color_test
"""

import argparse
import itertools
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.colors as mcolors
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from scipy.stats import linregress
from skimage.color import deltaE_ciede2000, rgb2lab

# ---- The sources: key, label, pair (the pair of a source is the group whose two members share a color family) ---------------------------------------
OBS = ('obs', 'OBS')
PAIRS = [('3-km', ('scream3_ctl', '3-km CTL'), ('scream3_tune', '3-km TUNE')),
         ('13-km', ('scream13_ctl', '13-km CTL'), ('scream13_tune', '13-km TUNE')),
         ('E3SM', ('e3sm25', '25-km'), ('e3sm100', '100-km'))]
# OBS color in the line plots and in the box plot (the box fill; a black fill hides the black median)
OBS_LINE_COLOR = 'black'
OBS_BOX_COLOR = 'dimgray'
SURFACES = ['Land', 'Ocean']

# ---- The ten variations: three (base tone, deeper tone) pairs, in the order 3-km, 13-km, E3SM; names are matplotlib (CSS4) colors ----------------------------------
# families: the color family of each pair (for the titles)
VARIATIONS = [
    dict(families=('Blue', 'Red', 'Green'), pairs=(('deepskyblue', 'royalblue'), ('tomato', 'firebrick'), ('limegreen', 'forestgreen'))),
    dict(families=('Blue', 'Orange', 'Purple'), pairs=(('deepskyblue', 'royalblue'), ('orange', 'chocolate'), ('violet', 'darkviolet'))),
    dict(families=('Blue', 'Red', 'Purple'), pairs=(('lightskyblue', 'steelblue'), ('salmon', 'crimson'), ('mediumpurple', 'rebeccapurple'))),
    dict(families=('Blue', 'Magenta', 'Green'), pairs=(('skyblue', 'dodgerblue'), ('hotpink', 'mediumvioletred'), ('mediumseagreen', 'seagreen'))),
    dict(families=('Blue', 'Red', 'Purple'), pairs=(('deepskyblue', 'royalblue'), ('tomato', 'firebrick'), ('orchid', 'purple'))),
    dict(families=('Teal', 'Orange', 'Purple'), pairs=(('mediumturquoise', 'darkcyan'), ('orange', 'chocolate'), ('violet', 'darkviolet'))),
    dict(families=('Blue', 'Orange', 'Green'), pairs=(('deepskyblue', 'royalblue'), ('darkorange', 'sienna'), ('yellowgreen', 'seagreen'))),
    dict(families=('Blue', 'Magenta', 'Orange'), pairs=(('lightskyblue', 'steelblue'), ('orchid', 'mediumvioletred'), ('orange', 'chocolate'))),
    dict(families=('Blue', 'Green', 'Magenta'), pairs=(('deepskyblue', 'royalblue'), ('yellowgreen', 'seagreen'), ('hotpink', 'mediumvioletred'))),
    dict(families=('Purple', 'Red', 'Teal'), pairs=(('mediumpurple', 'rebeccapurple'), ('tomato', 'firebrick'), ('mediumturquoise', 'darkcyan'))),
]

# ---- Synthetic data: the same for every variation -------------------------------------------------------------------------------------------------
# Per source: (multiplier of the CCS area median, lifetime median [h], slope and offset of log10(rain volume) against ln(lifetime), amplitude of the life cycle)
SOURCE_PARAMS = {'obs': (1.00, 9.0, 0.95, 3.30, 1.00), 'scream3_ctl': (0.84, 8.0, 0.90, 3.40, 0.86), 'scream3_tune': (1.10, 9.8, 0.98, 3.35, 1.10),
                 'scream13_ctl': (1.25, 10.5, 1.00, 3.25, 1.24), 'scream13_tune': (1.42, 11.5, 1.05, 3.20, 1.38), 'e3sm25': (1.62, 12.0, 1.08, 3.10, 1.52),
                 'e3sm100': (1.90, 13.5, 1.15, 3.00, 1.70)}


def all_sources():
    """The sources in plotting order as a list of (key, label): OBS first, then the members of the three pairs."""
    return [OBS] + [member for _, first, second in PAIRS for member in (first, second)]


def make_synthetic(seed=0, n_box=3000, n_kde=1500):
    """Synthetic data of every source with the shapes of the real quantities.

    Args:
        seed: random seed (default 0).
        n_box: tracks per source and surface in the box-plot data (default 3000).
        n_kde: tracks per source in the joint-KDE data (default 1500).

    Returns:
        dict with ``box`` (DataFrame: source, surface, ccs_area in km2), ``lines`` (dict (key, surface, bin label) -> (time h, CCS area km2)) and
        ``kde`` (dict key -> (lifetime h, log10 rain volume)).
    """
    rng = np.random.default_rng(seed)
    rows, lines, kde = [], {}, {}
    # Loop over the sources: box-plot samples, life-cycle curves and joint-KDE samples
    for key, label in all_sources():
        area_mult, life_med, slope, offset, amp = SOURCE_PARAMS[key]
        # (a) CCS area: lognormal, ocean systems larger than land systems
        for surface, base in (('Land', 2.2e4), ('Ocean', 3.4e4)):
            rows.append(pd.DataFrame({'source': label, 'surface': surface, 'ccs_area': base * area_mult * rng.lognormal(0.0, 0.85, n_box)}))
        # (b, c) Composite life cycle: a skewed bump over the duration, with a little noise; the 22-26 h bin is larger than the 10-14 h bin
        for surface, scale in (('Land', 1.0), ('Ocean', 1.5)):
            for bin_label, duration, size in (('22-26 h', 24.0, 1.6e5), ('10-14 h', 12.0, 0.8e5)):
                t = np.linspace(0.0, duration, 49)
                x = t / duration
                y = size * scale * amp * (np.sin(np.pi * x) ** 1.2) * (1.0 + 0.25 * x) + 0.02 * size * rng.normal(0.0, 1.0, t.size)
                lines[(key, surface, bin_label)] = (t, np.maximum(y, 0.0))
        # (d) Lifetime and rain volume: correlated on the log scale
        lifetime = np.exp(rng.normal(np.log(life_med), 0.45, n_kde))
        kde[key] = (lifetime, offset + slope * np.log(lifetime) + rng.normal(0.0, 0.35, n_kde))
    return dict(box=pd.concat(rows, ignore_index=True), lines=lines, kde=kde)


# ---- Colors ------------------------------------------------------------------------------------------------------------------------------------------
def variation_colors(variation):
    """Colors of a variation.

    Args:
        variation: one entry of VARIATIONS.

    Returns:
        (line, box, names): dicts keyed by source label. ``line`` is the color in line plots and contours, ``box`` the box fill (OBS dimgray); ``names`` the text
        for the legends, the color name (OBS: black lines / dimgray box).
    """
    line, box, names = {OBS[1]: OBS_LINE_COLOR}, {OBS[1]: OBS_BOX_COLOR}, {OBS[1]: f'{OBS_LINE_COLOR} lines, {OBS_BOX_COLOR} box'}
    # The two members of every pair: base tone, deeper tone
    for (_, first, second), (c1, c2) in zip(PAIRS, variation['pairs']):
        for (_, label), color in ((first, c1), (second, c2)):
            line[label], box[label], names[label] = color, color, color
    return line, box, names


def lab_of(name):
    """CIELAB value of a matplotlib color name (D65, sRGB)."""
    return rgb2lab(np.array(mcolors.to_rgb(name))[np.newaxis, np.newaxis, :])[0, 0]


def color_metrics(variation):
    """Lightness and color differences of a variation.

    Args:
        variation: one entry of VARIATIONS.

    Returns:
        dict with ``L`` (color name -> L*), ``within`` (list of CIEDE2000 differences inside the three pairs), ``between`` (smallest difference between two colors of
        different pairs), ``to_black`` and ``to_dimgray`` (smallest difference of any simulation color to the OBS line / box color).
    """
    colors = [c for pair in variation['pairs'] for c in pair]
    lab = {c: lab_of(c) for c in colors + [OBS_LINE_COLOR, OBS_BOX_COLOR]}
    de = lambda a, b: float(deltaE_ciede2000(lab[a], lab[b]))                                      # noqa: E731
    within = [de(a, b) for a, b in variation['pairs']]
    between = min(de(a, b) for p, q in itertools.combinations(variation['pairs'], 2) for a in p for b in q)
    return dict(L={c: float(lab[c][0]) for c in colors}, within=within, between=between,
                to_black=min(de(c, OBS_LINE_COLOR) for c in colors), to_dimgray=min(de(c, OBS_BOX_COLOR) for c in colors))


# ---- The panels ----------------------------------------------------------------------------------------------------------------------------------------
def truncate_colormap(cmap, minval=0.0, maxval=1.0, n=256):
    """Part of a colormap, as a new colormap (the OBS contours of the joint KDE use Greys 0.15-0.72)."""
    return mcolors.LinearSegmentedColormap.from_list(f'trunc({cmap.name},{minval:.2f},{maxval:.2f})', cmap(np.linspace(minval, maxval, n)))


def plot_box_panel(ax, box, box_colors, fontsize=11):
    """Panel (a): grouped notched box-whisker plot of the CCS area, x = surface, one box per source, logarithmic y axis (the recipe of plot_boxplots)."""
    import seaborn as sns
    labels = [label for _, label in all_sources()]
    sns.boxplot(data=box, x='surface', y='ccs_area', hue='source', order=SURFACES, hue_order=labels, palette=box_colors, dodge=True, width=0.7, whis=[5, 95],
                showfliers=False, notch=True, medianprops=dict(color='k', linewidth=1, zorder=5), whiskerprops=dict(color='black', linewidth=1.2),
                capprops=dict(color='black', linewidth=1.2), showmeans=True,
                meanprops=dict(marker='o', markersize=6, markerfacecolor='whitesmoke', markeredgecolor='k', markeredgewidth=1.3, zorder=4), ax=ax)
    if ax.get_legend() is not None:
        ax.get_legend().remove()
    ax.set_yscale('log')
    ax.set_ylabel('CCS Area (km²)')
    ax.set_xlabel('')
    ax.set_title('(a) Max CCS Area', loc='left', fontweight='bold', fontsize=fontsize + 1)
    ax.grid(axis='y', ls='--', alpha=0.7)
    for lbl in ax.get_xticklabels():
        lbl.set_fontweight('bold')


def plot_line_panel(ax, lines, line_colors, surface, letter):
    """Panels (b), (c): composite life-cycle lines of one surface for all sources, 22-26 h bin solid and 10-14 h bin dashed, no shading."""
    for key, label in all_sources():
        for bin_label, ls in (('22-26 h', '-'), ('10-14 h', '--')):
            t, y = lines[(key, surface, bin_label)]
            ax.plot(t, y, color=line_colors[label], linestyle=ls, linewidth=4 if key == OBS[0] else 3, zorder=5 if key == OBS[0] else 3)
    ax.set_title(f'({letter}) {surface}', loc='left', fontweight='bold', fontsize=12)
    ax.set_xlabel('Relative time (h)')
    ax.set_ylabel('CCS Area (km²)' if letter == 'b' else '')
    ax.set_xlim(0, 26)
    ax.grid(ls=':', alpha=0.6)


def plot_joint_kde_panel(fig, outer_spec, kde, line_colors, levels=(0.1, 0.2, 0.4, 0.6, 0.8, 1.0)):
    """Panel (d): joint KDE of the lifetime against log10 of the total rain volume with marginal KDEs and regression lines (the recipe of jointKDE_MxN):
    OBS as filled gray contours, every simulation as colored contour lines at the same levels."""
    import seaborn as sns
    inner = gridspec.GridSpecFromSubplotSpec(2, 2, subplot_spec=outer_spec, width_ratios=[4, 1], height_ratios=[1, 4], wspace=0.04, hspace=0.04)
    ax_joint, ax_x, ax_y = fig.add_subplot(inner[1, 0]), fig.add_subplot(inner[0, 0]), fig.add_subplot(inner[1, 1])
    cmap = truncate_colormap(plt.get_cmap('Greys'), 0.15, 0.72)
    # OBS: filled contours and dark marginal lines
    x_o, y_o = kde[OBS[0]]
    sns.kdeplot(x=x_o, y=y_o, levels=list(levels), fill=True, cmap=cmap, alpha=0.88, ax=ax_joint)
    sns.kdeplot(x=x_o, ax=ax_x, color=OBS_LINE_COLOR, lw=3.4, fill=False)
    sns.kdeplot(y=y_o, ax=ax_y, color=OBS_LINE_COLOR, lw=3.4, fill=False)
    fit = linregress(x_o, y_o)
    xs = np.linspace(x_o.min(), x_o.max(), 100)
    ax_joint.plot(xs, fit.slope * xs + fit.intercept, color=OBS_LINE_COLOR, lw=2.0, zorder=5)
    # The simulations: contour lines at the same levels, marginals and regression lines
    for key, label in all_sources()[1:]:
        x_m, y_m = kde[key]
        sns.kdeplot(x=x_m, y=y_m, color=line_colors[label], levels=list(levels), linewidths=2.0, fill=False, ax=ax_joint)
        sns.kdeplot(x=x_m, ax=ax_x, color=line_colors[label], lw=2.0, fill=False)
        sns.kdeplot(y=y_m, ax=ax_y, color=line_colors[label], lw=2.0, fill=False)
        fit = linregress(x_m, y_m)
        xs = np.linspace(x_m.min(), x_m.max(), 100)
        ax_joint.plot(xs, fit.slope * xs + fit.intercept, color=line_colors[label], lw=1.4, zorder=6)
    # Axes: shared limits, labels, the rain volume as powers of ten
    xlim, ylim = (0, 32), (3.2, 8.0)
    ax_joint.set(xlim=xlim, ylim=ylim, xlabel='Lifetime (h)', ylabel='Total rain volume (mm h⁻¹ km²)')
    ax_joint.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f'$10^{{{v:g}}}$'))
    ax_joint.grid(ls=':', alpha=0.55)
    ax_x.set_xlim(xlim)
    ax_y.set_ylim(ylim)
    for ax_m in (ax_x, ax_y):
        ax_m.set(xlabel=None, ylabel=None)
        ax_m.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
        ax_m.grid(ls=':', alpha=0.4)
    for spine in ('top', 'right', 'left'):
        ax_x.spines[spine].set_visible(False)
    for spine in ('top', 'right', 'bottom'):
        ax_y.spines[spine].set_visible(False)
    ax_x.set_title('(d) Lifetime vs rain volume', loc='left', fontweight='bold', fontsize=12)


def build_variation_figure(index, variation, data):
    """Draw the figure of one variation (four panels, one legend with the color names, a title with the families).

    Args:
        index: 1-based number of the variation.
        variation: one entry of VARIATIONS.
        data: output of make_synthetic.

    Returns:
        the matplotlib Figure.
    """
    line_colors, box_colors, names = variation_colors(variation)
    fig = plt.figure(figsize=(22, 6.6))
    outer = gridspec.GridSpec(1, 4, figure=fig, width_ratios=[1.45, 1.0, 1.0, 1.55], wspace=0.30, left=0.045, right=0.99, top=0.88, bottom=0.24)
    plot_box_panel(fig.add_subplot(outer[0]), data['box'], box_colors)
    for spec, surface, letter in ((outer[1], 'Land', 'b'), (outer[2], 'Ocean', 'c')):
        plot_line_panel(fig.add_subplot(spec), data['lines'], line_colors, surface, letter)
    plot_joint_kde_panel(fig, outer[3], data['kde'], line_colors)
    # One legend for the figure: every source with the name of its color, then the line styles of the life-cycle panels
    handles = [Line2D([0], [0], color=line_colors[label], lw=4 if key == OBS[0] else 3) for key, label in all_sources()]
    texts = [f'{label} ({names[label]})' for _, label in all_sources()]
    handles += [Line2D([0], [0], color='0.35', lw=3, ls='-'), Line2D([0], [0], color='0.35', lw=3, ls='--'), Patch(facecolor=matplotlib.cm.Greys(0.5), edgecolor='dimgray')]
    texts += ['22-26 h bin (solid)', '10-14 h bin (dashed)', 'OBS joint KDE: gray fill']
    fig.legend(handles, texts, loc='lower center', ncol=5, frameon=True, fontsize=12, bbox_to_anchor=(0.5, 0.0))
    families = ' / '.join(f'{f} ({a}, {b})' for f, (a, b) in zip(variation['families'], variation['pairs']))
    fig.suptitle(f'Variation {index}: 3-km, 13-km, E3SM pairs in {families}', fontsize=15, fontweight='bold', y=0.985)
    return fig


def plot_variation(index, variation, data, outdir, dpi=150):
    """Make and save the figure of one variation as a 24-bit PNG.

    Args:
        index: 1-based number of the variation.
        variation: one entry of VARIATIONS.
        data: output of make_synthetic.
        outdir: output folder.
        dpi: resolution (default 150).

    Returns:
        path of the saved PNG.
    """
    from PIL import Image
    fig = build_variation_figure(index, variation, data)
    path = os.path.join(outdir, f'color_variation_{index:02d}.png')
    fig.savefig(path, dpi=dpi, facecolor='white')
    plt.close(fig)
    Image.open(path).convert('RGB').save(path)
    return path


def plot_overview(outdir, dpi=150):
    """The overview sheet: one row per variation with the seven colors as swatches (name and L* inside), and the color differences (CIEDE2000) in the last columns.

    Returns:
        path of the saved PNG.
    """
    from PIL import Image
    labels = [label for _, label in all_sources()]
    fig, ax = plt.subplots(figsize=(20, 0.95 * len(VARIATIONS) + 1.8))
    ax.set_xlim(0, 24.5)
    ax.set_ylim(-0.4, len(VARIATIONS) + 0.9)
    ax.invert_yaxis()
    ax.axis('off')
    for j, label in enumerate(labels):
        ax.text(3.0 + 1.9 * j + 0.85, -0.05, label, ha='center', va='bottom', fontsize=11, fontweight='bold')
    for j, text in enumerate(['within pairs\n(3-km | 13-km | E3SM)', 'between\nfamilies', 'to OBS\nblack | dimgray']):
        ax.text([16.9, 19.5, 21.7][j] + 0.9, -0.05, text, ha='center', va='bottom', fontsize=10, fontweight='bold')
    # One row per variation
    for i, variation in enumerate(VARIATIONS):
        line, box, names = variation_colors(variation)
        m = color_metrics(variation)
        ax.text(0.0, i + 0.45, f'{i + 1}', fontsize=15, fontweight='bold', va='center')
        ax.text(0.55, i + 0.45, '\n'.join(variation['families']), fontsize=10, va='center')
        for j, label in enumerate(labels):
            color = line[label] if label != 'OBS' else OBS_LINE_COLOR
            ax.add_patch(Rectangle((3.0 + 1.9 * j, i + 0.05), 1.7, 0.8, facecolor=color, edgecolor='k', linewidth=0.8))
            lightness = m['L'].get(color)
            text = color if label != 'OBS' else 'black / dimgray'
            if label != 'OBS':
                text += f'\nL*={lightness:.0f}'
            light_text = (lightness if lightness is not None else 0.0) > 60
            ax.text(3.0 + 1.9 * j + 0.85, i + 0.45, text, ha='center', va='center', fontsize=8.5, color='k' if light_text else 'w')
        ax.text(16.9 + 0.9, i + 0.45, ' | '.join(f'{v:.0f}' for v in m['within']), ha='center', va='center', fontsize=11)
        ax.text(19.5 + 0.9, i + 0.45, f"{m['between']:.0f}", ha='center', va='center', fontsize=11)
        ax.text(21.7 + 0.9, i + 0.45, f"{m['to_black']:.0f} | {m['to_dimgray']:.0f}", ha='center', va='center', fontsize=11)
    fig.suptitle('Ten color variations: three pairs of simulations (base tone, deeper tone of one family) and OBS (black lines, dimgray box)', fontsize=14, fontweight='bold', y=0.995)
    path = os.path.join(outdir, 'color_variations_overview.png')
    fig.savefig(path, dpi=dpi, facecolor='white', bbox_inches='tight')
    plt.close(fig)
    Image.open(path).convert('RGB').save(path)
    return path


def print_table():
    """Print the colors and the color differences of every variation."""
    print(f"{'#':>2s}  {'families':28s} {'3-km (base, deeper)':36s} {'13-km':36s} {'E3SM':36s} within-pair dE | between | to black | to dimgray")
    for i, v in enumerate(VARIATIONS, 1):
        m = color_metrics(v)
        pairs = [f'{a} ({m["L"][a]:.0f}), {b} ({m["L"][b]:.0f})' for a, b in v['pairs']]
        print(f"{i:2d}  {' / '.join(v['families']):28s} {pairs[0]:36s} {pairs[1]:36s} {pairs[2]:36s} "
              f"{' '.join(f'{x:4.0f}' for x in m['within'])} | {m['between']:5.0f} | {m['to_black']:5.0f} | {m['to_dimgray']:5.0f}")


def main():
    """Make the ten variation figures and the overview sheet."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--outdir', default='/pscratch/sd/f/feng045/SCREAM-decadal/figures_color_test', help='folder of the figures (created if missing)')
    ap.add_argument('--dpi', type=int, default=150, help='resolution of the PNG files')
    ap.add_argument('--seed', type=int, default=0, help='seed of the synthetic data')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    # The overview first (no data needed), then the table and the ten figures on the same synthetic data
    print('overview:', plot_overview(args.outdir, args.dpi))
    print_table()
    data = make_synthetic(args.seed)
    for i, variation in enumerate(VARIATIONS, 1):
        print('variation', i, plot_variation(i, variation, data, args.outdir, args.dpi))


if __name__ == '__main__':
    main()
