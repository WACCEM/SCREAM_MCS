#!/usr/bin/env python
"""
Figures of the echo-top gap screening (test_echotop_gap.py output).

    python plot_echotop_gap.py --scream 'DIR/scream_22*' --mrms DIR/mrms_2025061322 --out-dir FIGDIR

1. echotop_gap_variants.png   per-cell maximum 10-dBZ ETH of SCREAM for every gap / threshold variant
                              (dot = median, bar = 25-75 %, tick = 90 %), MRMS median as a reference line
2. echotop_gap_profiles.png   reflectivity at fixed heights in columns with a composite >= 40 dBZ (SCREAM vs MRMS):
                              median, 90th percentile, fraction above 10 dBZ
3. echotop_gap_examples.png   reflectivity profiles of SCREAM columns whose first layer ends low while echo exists
                              above (what the gap could bridge), with the ETH of gap 1 and "no limit"
"""
import argparse
import glob
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

C_S, C_M, INK, GRID = '#d95f02', '#1b3a8a', '#222222', '#e3e3e3'


def load(dirs, name):
    return pd.concat([pd.read_csv(os.path.join(d, name)) for d in dirs], ignore_index=True)


def style(ax):
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scream', required=True, help='glob of the SCREAM screening output directories')
    p.add_argument('--mrms', default=None, help='MRMS screening output directory (optional)')
    p.add_argument('--out-dir', required=True)
    p.add_argument('--min-diameter', type=float, default=10.0)
    args = p.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    sdirs = [d for d in sorted(glob.glob(args.scream)) if os.path.isdir(d)]
    cells = load(sdirs, 'echotop_gap_cells.csv')
    cells = cells[cells.diameter_km >= args.min_diameter]
    mcells = None
    if args.mrms and os.path.exists(os.path.join(args.mrms, 'echotop_gap_cells.csv')):
        mcells = load([args.mrms], 'echotop_gap_cells.csv')
        mcells = mcells[mcells.diameter_km >= args.min_diameter]

    # ---- 1. variants
    groups = [('echo-layer gap (levels)', [f'gap{g}' for g in (1, 2, 3, 4, 5, 6, 8, 10, 16)] + ['inf']),
              ('echo-layer gap (m)', ['m250', 'm500', 'm750', 'm1000']),
              ('sampled on the 33 MRMS levels', ['mrms_g1', 'mrms_g2']),
              ('threshold (gap 2 levels)', ['thr-10_g2', 'thr-5_g2', 'thr0_g2', 'thr5_g2'])]
    labels = {'inf': 'no limit', 'mrms_g1': 'gap 1', 'mrms_g2': 'gap 2', 'm250': '250 m', 'm500': '500 m', 'm750': '750 m',
              'm1000': '1000 m', 'thr-10_g2': '-10 dBZ', 'thr-5_g2': '-5 dBZ', 'thr0_g2': '0 dBZ', 'thr5_g2': '5 dBZ'}
    rows = []
    for gname, vs in groups:
        for v in vs:
            rows.append((gname, v, labels.get(v, v.replace('gap', 'gap '))))
    fig, ax = plt.subplots(figsize=(8.0, 7.6))
    y = 0
    ticks, tl, gl = [], [], []
    last = None
    for gname, v, lab in rows:
        if gname != last:
            y += 0.8
            gl.append((y - 0.2, gname))
            last = gname
        q = cells[v].dropna()
        ax.plot([q.quantile(.25), q.quantile(.75)], [y, y], color=C_S, lw=2.2, solid_capstyle='butt', alpha=.6)
        ax.plot(q.median(), y, 'o', color=C_S, ms=6)
        ax.plot(q.quantile(.9), y, '|', color=C_S, ms=9, mew=1.6)
        ticks.append(y)
        tl.append(lab)
        y += 1
    ax.set_yticks(ticks)
    ax.set_yticklabels(tl, fontsize=9)
    for yy, g in gl:
        ax.text(0.005, yy, g, transform=ax.get_yaxis_transform(), ha='left', va='bottom', fontsize=9, fontweight='bold',
                color=INK)
    if mcells is not None:
        m = mcells['gap1'].dropna()
        ax.axvline(m.median(), color=C_M, lw=1.6)
        ax.text(m.median() + 0.15, 0.6, f'MRMS 2025-06-13 22Z\nmedian {m.median():.1f} km\n(n={m.size})', color=C_M,
                fontsize=9, ha='left', va='bottom', transform=ax.get_xaxis_transform())
    ax.set_xlabel('Maximum 10-dBZ echo-top height of a cell (km): dot = median, bar = 25-75 %, tick = 90 %')
    fig.suptitle(f'SCREAM 2020-06-13 22:00-22:55Z, {cells.frame.nunique()} frames, {len(cells)} cells '
                 f'(diameter >= {args.min_diameter:g} km); blue line: MRMS median', fontsize=10)
    style(ax)
    ax.set_xlim(4, 15)
    ax.set_ylim(y + 0.3, -0.2)
    fig.subplots_adjust(left=0.12, right=0.97, top=0.94, bottom=0.08)
    fig.savefig(os.path.join(args.out_dir, 'echotop_gap_variants.png'), dpi=170)
    plt.close(fig)

    # ---- 2. profiles in strong columns
    prof = {'SCREAM': pd.concat([pd.read_csv(os.path.join(d, 'profile_by_height.csv')) for d in sdirs]).groupby('height_km').mean()}
    if args.mrms and os.path.exists(os.path.join(args.mrms, 'profile_by_height.csv')):
        prof['MRMS'] = pd.read_csv(os.path.join(args.mrms, 'profile_by_height.csv')).set_index('height_km')
    fig, axs = plt.subplots(1, 3, figsize=(10, 4.4), sharey=True)
    for (ds, pr), c in zip(prof.items(), (C_S, C_M)):
        axs[0].plot(pr['median'], pr.index, '-o', color=c, ms=3.5, label=ds)
        axs[1].plot(pr['p90'], pr.index, '-o', color=c, ms=3.5, label=ds)
        axs[2].plot(pr['frac_gt10'], pr.index, '-o', color=c, ms=3.5, label=ds)
    axs[0].axvline(10, color=INK, lw=0.8, ls=':')
    axs[1].axvline(10, color=INK, lw=0.8, ls=':')
    axs[0].set_xlabel('Median reflectivity (dBZ)')
    axs[1].set_xlabel('90th percentile reflectivity (dBZ)')
    axs[2].set_xlabel('Fraction of columns above 10 dBZ')
    axs[0].set_ylabel('Height (km)')
    axs[0].set_xlim(-40, 60)
    axs[1].set_xlim(-40, 60)
    for a in axs:
        style(a)
    axs[0].legend(frameon=False, loc='upper right')
    fig.suptitle('Columns with a composite reflectivity >= 40 dBZ (SCREAM: 12 frames, 2020-06-13 22Z; '
                 'MRMS: 2 frames, 2025-06-13 22Z)', fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, 'echotop_gap_profiles.png'), dpi=170)
    plt.close(fig)

    # ---- 3. example columns
    ex = []
    for d in sdirs:
        ex += pd.read_pickle(os.path.join(d, 'echotop_gap_examples.pkl'))
    ex = sorted(ex, key=lambda e: -(e['inf'] - e['gap1']))[:6]
    if ex:
        fig, axs = plt.subplots(1, len(ex), figsize=(2.3 * len(ex), 4.4), sharey=True)
        axs = np.atleast_1d(axs)
        for a, e in zip(axs, ex):
            o = np.argsort(e['z_m'])
            a.plot(e['dbz'][o], e['z_m'][o] / 1000., color=INK, lw=1.4)
            a.axvline(10, color=INK, lw=0.8, ls=':')
            a.axhline(e['gap1'], color=C_S, lw=1.4, label='ETH gap 1')
            a.axhline(e['inf'], color=C_M, lw=1.4, ls='--', label='highest echo')
            a.set_xlim(-40, 70)
            a.set_title(f"{e['frame'][-6:-2]}Z ({e['iy']},{e['ix']})", fontsize=9)
            a.set_xlabel('dBZ')
            style(a)
        axs[0].set_ylabel('Height (km)')
        axs[0].legend(frameon=False, fontsize=8, loc='upper right')
        axs[0].set_ylim(0, 16)
        fig.suptitle('SCREAM columns where the first echo layer ends far below the highest echo (largest differences)',
                     fontsize=10)
        fig.tight_layout()
        fig.savefig(os.path.join(args.out_dir, 'echotop_gap_examples.png'), dpi=170)
        plt.close(fig)
    print('figures in', args.out_dir)


if __name__ == '__main__':
    main()
