#!/usr/bin/env python
"""
Sensitivity of the cell echo-top height (ETH) to the vertical gap allowed inside an echo layer.

echotop_height / echotop_height_fast return the top of the LOWEST contiguous echo layer of a column; `gap` is
counted in vertical levels (np.diff(idxcld) > gap starts a new layer: gap=1 bridges nothing, gap=2 one missing
level). SCREAM has 128 levels (about 30-300 m apart), MRMS 33 (250 m, 500 m, 1000 m), so the same number of
levels is not the same physical gap. This script measures, on single frames, the maximum ETH of each Steiner
convective cell (the quantity of the cell track statistics, maxETH_10dbz) for

  gapN       echotop_height_fast with gap = N levels (N = 1 ... 16)
  inf        highest echo of the column (upper bound of any gap)
  mM         first layer where holes up to M metres are bridged (M = 250 ... 1000)
  mrms_gG    the SCREAM column sampled (nearest level) on the 33 MRMS levels, then gap = G levels:
             what MRMS would see of the same field
  thrT_g2    threshold T dBZ instead of 10 (gap = 2): which threshold of the model field gives a given ETH

and, for the columns with a composite reflectivity of at least 40 dBZ, the median / p90 reflectivity and the
fraction above 10 dBZ at fixed heights (profile_by_height.csv). The same script runs on an MRMS frame
(--config config_celltracking_3km_MRMS.yaml --base MRMS_Reflectivity_HRRR_ ...) for the reference.

It does not change PyFLEXTRKR. Usage:
    python test_echotop_gap.py --start 2020-06-13-220000 --nframes 12 --out-dir OUT
"""
import argparse
import os
import time
import numpy as np
import pandas as pd
import yaml
from scipy import ndimage

from pyflextrkr.idcells_reflectivity import get_composite_reflectivity_generic
from pyflextrkr.steiner_func import make_dilation_step_func, mod_steiner_classification, expand_conv_core
from pyflextrkr.echotop_func import echotop_height_fast
import xarray as xr

CFG = '/global/homes/f/feng045/program/scream/tracking/config_celltracking_3km_SCREAMv1-Cess2_CONUS_06.yaml'
INPUT = '/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/CONUS/gap_test/input/'
BASE = 'scream.diag_equiv_reflectivity.5min.INSTANT.nmins_x5.'
# heightAboveSea levels of the MRMS files (m)
MRMS_LEVELS = np.array([500, 750, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 2750, 3000, 3500, 4000, 4500, 5000, 5500,
                        6000, 6500, 7000, 7500, 8000, 8500, 9000, 10000, 11000, 12000, 13000, 14000, 15000, 16000,
                        17000, 18000, 19000], dtype=float)
GAPS = [1, 2, 3, 4, 5, 6, 8, 10, 16]
GAPS_M = [250, 500, 750, 1000]
INF = 10 ** 6


def eth_gap_metres(cmask, height, gap_m):
    """
    First-layer top (m) for columns: a new layer starts when the empty span between two echo levels is larger than
    gap_m. empty span = z[k] - z[last echo level] - (z[k] - z[k-1]), 0 for neighbouring levels.
    cmask, height: [nz, ncol], bottom-up. Returns [ncol] with NaN where no echo.
    """
    nz, ncol = cmask.shape
    last_z = np.full(ncol, np.nan)
    passed = np.zeros(ncol, dtype=bool)
    top = np.full(ncol, np.nan)
    for k in range(nz):
        c = cmask[k]
        zk = height[k]
        spacing = zk - height[k - 1] if k > 0 else np.zeros(ncol)
        has_last = ~np.isnan(last_z)
        too_big = has_last & c & ((zk - last_z - spacing) > gap_m)
        passed |= too_big
        inl = c & ~passed
        top = np.where(inl, zk, top)
        last_z = np.where(inl, zk, last_z)
    return top


def sample_levels(dbz, height, levels):
    """Nearest-level sampling of columns [nz, ncol] to the given heights -> [len(levels), ncol]."""
    out = np.full((levels.size, dbz.shape[1]), np.nan, dtype=np.float32)
    cols = np.arange(dbz.shape[1])
    for j, h in enumerate(levels):
        idx = np.nanargmin(np.abs(height - h), axis=0)
        out[j] = dbz[idx, cols]
    return out


def eth_columns_fast(dbz, height, thresh, gap):
    """
    echotop_height_fast on a set of columns dbz [nz, ncol] (height [nz] or [nz, ncol]). The function squeezes
    singleton dimensions, so the columns are laid out as a [ncol/2, 2] grid (ncol padded to an even number).
    """
    nz, ncol = dbz.shape
    pad = ncol % 2
    if pad:
        dbz = np.concatenate([dbz, np.full((nz, 1), np.nan, dtype=dbz.dtype)], axis=1)
        if height.ndim == 2:
            height = np.concatenate([height, height[:, -1:]], axis=1)
    n2 = dbz.shape[1] // 2
    d3 = xr.DataArray(dbz.reshape(nz, n2, 2), dims=('z', 'y', 'x'))
    h = height if height.ndim == 1 else height.reshape(nz, n2, 2)
    e = echotop_height_fast(d3, h, 'z', (n2, 2), thresh, gap, 0).reshape(-1)
    return e[:ncol]


def selftest():
    """gap_m = (G - 1) * dz must equal the level gap G on a uniform grid."""
    rng = np.random.default_rng(1)
    nz, ncol, dz = 60, 4000, 100.0
    cm = rng.random((nz, ncol)) < 0.55
    h = np.repeat((np.arange(nz) * dz + 300.0)[:, None], ncol, axis=1)
    dbz = np.where(cm, 20.0, -10.0).astype(np.float32)
    for g in (1, 2, 3, 5):
        a = eth_columns_fast(dbz, h, 10.0, g)
        b = eth_gap_metres(cm, h, (g - 1) * dz)
        assert np.allclose(a, b, equal_nan=True), f'selftest failed for gap {g}'
    print('selftest: metre gap == level gap on a uniform grid')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default=CFG)
    p.add_argument('--input-dir', default=INPUT)
    p.add_argument('--base', default=BASE, help='file name characters before the time')
    p.add_argument('--start', default='2020-06-13-220000', help='first frame, the time string of the file name')
    p.add_argument('--extra-thresh', type=float, nargs='*', default=[-10, -5, 0, 5],
                   help='other ETH thresholds [dBZ] (gap = 2)')
    p.add_argument('--nframes', type=int, default=12)
    p.add_argument('--thresh', type=float, default=10.0, help='reflectivity threshold of the ETH [dBZ]')
    p.add_argument('--out-dir', required=True)
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    cfg = yaml.safe_load(open(args.config))
    cfg['input_format'] = 'netcdf'
    selftest()

    BASEN = args.base
    names = sorted(f for f in os.listdir(args.input_dir) if f.startswith(BASEN) and f.endswith('.nc'))
    names = [n for n in names if n[len(BASEN):-3] >= args.start][:args.nframes]
    print(f'{len(names)} frames from {names[0]}')

    bkg_bin, conv_rad_bin = make_dilation_step_func(
        cfg['mindBZuse'], cfg['dBZforMaxConvRadius'], cfg['bkg_refl_increment'], cfg['conv_rad_increment'],
        cfg['conv_rad_start'], cfg['maxConvRadius'])
    types_steiner = {'NO_SURF_ECHO': 1, 'WEAK_ECHO': 2, 'STRATIFORM': 3, 'CONVECTIVE': 4}
    dx, dy = cfg['dx'], cfg['dy']
    pix_km2 = (dx / 1000.) * (dy / 1000.)

    rows, examples, prof_rows = [], [], []
    for n in names:
        t0 = time.time()
        comp = get_composite_reflectivity_generic(args.input_dir + n, cfg)
        refl = comp['refl']
        dbz3d = comp['dbz3d_filt']
        height = np.asarray(comp['height'])           # [nz, ny, nx] (or [nz] for MRMS), bottom-up, m
        ny, nx = refl.shape
        height_1d = height.ndim == 1
        if height_1d:
            height = np.broadcast_to(height[:, None, None], (height.size, ny, nx))
        st = mod_steiner_classification(
            types_steiner, refl, comp['mask_goodvalues'], dx, dy, bkg_rad=cfg['bkgrndRadius'] * 1000,
            minZdiff=cfg['minZdiff'], absConvThres=cfg['absConvThres'], truncZconvThres=cfg['truncZconvThres'],
            weakEchoThres=cfg['weakEchoThres'], bkg_bin=bkg_bin, conv_rad_bin=conv_rad_bin,
            min_corearea=cfg.get('min_corearea', 0), min_cellarea=cfg.get('min_cellarea', 0),
            remove_smallcores=cfg.get('remove_smallcores', True), remove_smallcells=cfg.get('remove_smallcells', False),
            return_diag=False, convolve_method=cfg.get('convolve_method', 'ndimage'),
            dilate_method=cfg.get('dilate_method', 'orig'))
        core_expand, _ = expand_conv_core(st['score_dilate'], np.array(cfg['radii_expand']), dx, dy, min_corenpix=0)
        ids = np.unique(core_expand)
        ids = ids[ids > 0]
        if ids.size == 0:
            print(f'{n}: no cells')
            continue

        eth = {}
        for g in GAPS + [INF]:
            e = echotop_height_fast(dbz3d, height[:, 0, 0] if height_1d else height, cfg['z_dimname'], (ny, nx),
                                    args.thresh, g, 0)
            eth['inf' if g == INF else f'gap{g}'] = e / 1000.

        # columns with echo: custom metre gap and the MRMS-like sampling on compressed columns
        dbz_np = np.asarray(dbz3d.values if hasattr(dbz3d, 'values') else dbz3d).squeeze()
        cm = dbz_np > args.thresh
        colmask = cm.any(axis=0)
        zc, dc, cmc = height[:, colmask], dbz_np[:, colmask], cm[:, colmask]
        for m in GAPS_M:
            e = np.full((ny, nx), np.nan, dtype=np.float32)
            e[colmask] = eth_gap_metres(cmc, zc, m) / 1000.
            eth[f'm{m}'] = e
        if not height_1d:
            dm = sample_levels(dc, zc, MRMS_LEVELS)
            for g in (1, 2):
                e = np.full((ny, nx), np.nan, dtype=np.float32)
                e[colmask] = eth_columns_fast(dm, MRMS_LEVELS, args.thresh, g) / 1000.
                eth[f'mrms_g{g}'] = e
        # other thresholds, gap 2 levels (columns with any echo above the lowest threshold)
        for t in args.extra_thresh:
            cmt = dbz_np > t
            col_t = cmt.any(axis=0)
            e = np.full((ny, nx), np.nan, dtype=np.float32)
            hz = height[:, 0, 0] if height_1d else height[:, col_t]
            e[col_t] = eth_columns_fast(dbz_np[:, col_t], hz, t, 2) / 1000.
            eth[f'thr{t:g}_g2'] = e
        # reflectivity at fixed heights in columns with composite >= 40 dBZ
        strong = np.nanmax(dbz_np, axis=0) >= 40
        zs = height[:, strong]
        ds_ = dbz_np[:, strong]
        for hk in range(1, 17):
            idx = np.nanargmin(np.abs(zs - hk * 1000.), axis=0)
            v = ds_[idx, np.arange(ds_.shape[1])]
            prof_rows.append({'frame': n[len(BASEN):-3], 'height_km': hk, 'ncol': v.size, 'median': np.nanmedian(v),
                              'p90': np.nanpercentile(v, 90), 'frac_gt10': float(np.mean(v > 10))})

        # per-cell maximum, as in trackstats_func (max over the expanded cell mask)
        npix = ndimage.sum(np.ones_like(core_expand), core_expand, index=ids)
        mxdbz = ndimage.maximum(np.nan_to_num(refl, nan=-99), core_expand, index=ids)
        rec = {'frame': n[len(BASEN):-3], 'cell': ids, 'npix': npix,
               'diameter_km': 2 * np.sqrt(npix * pix_km2 / np.pi), 'max_dbz': mxdbz}
        for k, e in eth.items():
            rec[k] = ndimage.maximum(np.nan_to_num(e, nan=-1), core_expand, index=ids)
        df = pd.DataFrame(rec)
        for k in eth:
            df.loc[df[k] < 0, k] = np.nan
        rows.append(df)

        # fraction of cell columns whose first layer ends below 8 km, per variant
        incell = core_expand > 0
        frac = {k: float(np.nanmean(e[incell & ~np.isnan(eth['inf'])] < 8.0)) for k, e in eth.items()}
        print(f'{n[len(BASEN):-3]}: {ids.size} cells, {incell.sum()} cell columns, {time.time() - t0:.0f} s; '
              f'ETH<8km: gap1 {frac["gap1"]:.2f}, inf {frac["inf"]:.2f}', flush=True)

        # example columns: first layer ends low, highest echo is high
        if len(examples) < 6:
            diff = np.where(incell, eth['inf'] - eth['gap1'], 0.0)
            diff = np.nan_to_num(diff, nan=0.0)
            for iy, ix in zip(*np.unravel_index(np.argsort(diff, axis=None)[::-1][:400:100], diff.shape)):
                examples.append({'frame': n[len(BASEN):-3], 'iy': int(iy), 'ix': int(ix), 'z_m': height[:, iy, ix].copy(),
                                 'dbz': dbz_np[:, iy, ix].copy(), 'gap1': eth['gap1'][iy, ix], 'inf': eth['inf'][iy, ix],
                                 'gap2': eth['gap2'][iy, ix],
                                 'mrms_g1': eth['mrms_g1'][iy, ix] if 'mrms_g1' in eth else np.nan})
        del comp, dbz3d, dbz_np, height, cm

    cells = pd.concat(rows, ignore_index=True)
    cells.to_csv(os.path.join(args.out_dir, 'echotop_gap_cells.csv'), index=False)
    pd.DataFrame(prof_rows).groupby('height_km')[['median', 'p90', 'frac_gt10', 'ncol']].mean().to_csv(
        os.path.join(args.out_dir, 'profile_by_height.csv'))
    variants = [c for c in cells.columns if c.startswith(('gap', 'inf', 'm', 'thr')) and c != 'max_dbz']
    sub = cells[cells.diameter_km >= 10]
    summ = pd.DataFrame({
        'median': sub[variants].median(), 'p25': sub[variants].quantile(.25), 'p75': sub[variants].quantile(.75),
        'p90': sub[variants].quantile(.90), 'mean': sub[variants].mean(), 'ncells': sub[variants].count()})
    bins = [10, 15, 20, 25, 30, 40]
    sub = sub.assign(dbin=pd.cut(sub.diameter_km, bins))
    binned = sub.groupby('dbin', observed=True)[variants].median()
    summ.to_csv(os.path.join(args.out_dir, 'echotop_gap_summary.csv'))
    binned.to_csv(os.path.join(args.out_dir, 'echotop_gap_binned_by_diameter.csv'))
    pd.to_pickle(examples, os.path.join(args.out_dir, 'echotop_gap_examples.pkl'))
    print('\nReflectivity at fixed heights in columns with composite >= 40 dBZ (mean over frames):')
    print(pd.read_csv(os.path.join(args.out_dir, 'profile_by_height.csv')).round(2).to_string(index=False))
    print('\nPer-cell maximum ETH10 (km), cells with diameter >= 10 km:')
    print(summ.round(2).to_string())
    print('\nMedian by diameter bin (km):')
    print(binned.round(1).T.to_string())


if __name__ == '__main__':
    main()
