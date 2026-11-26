#!/usr/bin/env python
"""
Rebuild and verify the metadata of the SCREAM Cess2 (3 km TUNE) HEALPix input store of the MCS tracking,
SCREAMv1_1H_zoom9_20190801_20210306.zarr (Zarr version 2).

On 2026-09-01 and 09-02 the NERSC scratch purge removed the 15 metadata files of the store (.zgroup, .zattrs, .zmetadata and
.zarray + .zattrs of each of the 6 arrays); the data chunks are still there. This script makes the 15 files again and writes
them to a folder of your own. It never writes into the store.

Where each piece of the metadata comes from:
  shapes, dtypes, chunk shapes, compressor    the 16-byte Blosc header of the data chunks, the decoded `time` and `cell` chunks
                                              (checked against the new metadata below)
  compression level, shuffle of the fields    the writer, hackathon/healpix-remapping/src/zarr_tools.py (zstd, level 3, bit shuffle)
  time units                                  the decoded `time` chunk counts hours from 0; the first time is 2019-08-01 00:00
                                              (saved notebook printouts of the store)
  global and crs attributes                   the writer, src/remap_tools.py at commit f960333 (in effect when the chunks were
                                              written on 2026-01-14); the global ones equal the saved notebook printouts
  attributes of rlut, pr, max_reflectivity    the header dump of the source model files,
                                              SCREAMv1-cess2/run/1hi.INSTANT.nhours_x1_header.txt (pr equals the notebook printout)
  fill value NaN                              the unused rows of the last (partial) time chunk are NaN
NOT recoverable: whether the original files held other attributes than these, and the exact JSON text.

Modes (compute node for --verify and --check-chunks):
  python rebuild_zarr_metadata.py --build                        # write <outdir>/metadata/ and the test store <outdir>/overlay_test.zarr
  python rebuild_zarr_metadata.py --verify [--store <path>]      # open the test store (or a repaired copy) and compare it with
                                                                 # the Cess2 MCS pixel files
  python rebuild_zarr_metadata.py --check-chunks --store <path>  # decode every chunk of a store or of a copy of it

To repair a copy of the store (the trailing /. copies the hidden files; a * would skip them):
  cp -r <outdir>/metadata/. <copy of the store>/
"""
import argparse
import itertools
import json
import math
import os
import shutil
import struct
import sys
import tempfile
from multiprocessing import Pool

import numcodecs
import numpy as np
import pandas as pd

STORE = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/healpix/SCREAMv1_1H_zoom9_20190801_20210306.zarr'
OUTDIR = '/pscratch/sd/f/feng045/SCREAM-decadal/cess2/zarr_metadata_rebuild'
PIXEL_DIR = '/pscratch/sd/w/wcmca1/SCREAMv1-cess2/mcs/mcstracking/20190803.0000_20210306.0000'
CATALOG = '/global/homes/f/feng045/program/hackathon/catalog/NERSC/main.yaml'

FIRST_TIME = '2019-08-01 00:00:00'
ZOOM = 9
NCELL = 12 * 4 ** ZOOM                      # HEALPix cells of zoom 9
TIME_CHUNK, CELL_CHUNK = 24, 262144         # chunk shape of the three fields
CELL_COORD_CHUNK = 196608                   # chunk length of the cell coordinate (16 chunks)
ARRAYS = ['time', 'cell', 'crs', 'pr', 'rlut', 'max_reflectivity']
METADATA_FILES = ['.zgroup', '.zattrs', '.zmetadata'] + [f'{a}/{f}' for a in ARRAYS for f in ('.zarray', '.zattrs')]

# Attributes of the three fields (source: header dump of the model files)
FIELD_ATTRS = {
    'rlut': {'units': 'W/m2', 'long_name': 'MISSING', 'standard_name': 'toa_outgoing_longwave_flux', 'cell_methods': 'time: point'},
    'pr': {'units': 'm/s', 'long_name': 'MISSING', 'standard_name': 'MISSING', 'cell_methods': 'time: point'},
    'max_reflectivity': {'units': '1', 'long_name': 'MISSING', 'standard_name': 'MISSING', 'cell_methods': 'time: point'},
}
# Global and crs attributes (source: the writer; PyFLEXTRKR reads crs.healpix_nside)
GLOBAL_ATTRS = {'grid_mapping': 'crs', 'healpix_nest': True, 'healpix_npix': NCELL, 'healpix_nside': 2 ** ZOOM,
                'healpix_order': ZOOM, 'original_grid': 'unstructured', 'remapping_method': 'delaunay_triangulation'}
CRS_ATTRS = {'grid_mapping_name': 'healpix', 'healpix_nside': 2 ** ZOOM, 'healpix_order': 'nest'}
# Times at which the rebuilt store is compared with the MCS pixel files: spread over the record, both sides of 29 February 2020
VERIFY_TIMES = ['2019-08-05 00:00', '2019-12-15 12:00', '2020-02-28 23:00', '2020-03-01 00:00', '2020-07-15 18:00',
                '2021-01-10 06:00', '2021-03-05 23:00']


def decode_chunk(path):
    """
    Decompress one Blosc chunk file.

    Args:
        path: str
            Chunk file.

    Returns:
        data: bytes
            Decompressed bytes of the chunk.
    """
    with open(path, 'rb') as stream:
        return numcodecs.Blosc().decode(stream.read())


def blosc_header(path):
    """
    Information that Blosc keeps in the first 16 bytes of a chunk.

    Args:
        path: str
            Chunk file.

    Returns:
        info: dict
            cname (compressor), typesize [bytes], shuffle (0 none, 1 byte, 2 bit), nbytes (decompressed size).
    """
    with open(path, 'rb') as stream:
        head = stream.read(16)
    flags = head[2]
    codecs = {0: 'blosclz', 1: 'lz4', 2: 'snappy', 3: 'zlib', 4: 'zstd'}
    return {'cname': codecs[flags >> 5], 'typesize': head[3], 'shuffle': 2 if flags & 0x4 else (1 if flags & 0x1 else 0),
            'nbytes': struct.unpack('<I', head[4:8])[0]}


def chunk_names(shape, chunks):
    """
    File names of all chunks of an array (Zarr version 2, separator '.').

    Args:
        shape: sequence of int
            Shape of the array.
        chunks: sequence of int
            Chunk shape.

    Returns:
        names: list of str
            One name per chunk, e.g. '0.0'; ['0'] for a scalar array.
    """
    if not shape:
        return ['0']
    ranges = [range(math.ceil(s / c)) for s, c in zip(shape, chunks)]
    return ['.'.join(str(i) for i in index) for index in itertools.product(*ranges)]


def inspect_store(store):
    """
    Read what the chunks themselves say about the arrays and check that every chunk file exists.

    Args:
        store: str
            Store folder.

    Returns:
        info: dict
            ntime, times (hours since the first time), layout (array -> (shape, chunks)).

    Raises:
        ValueError: a chunk file is missing or empty, or the chunks do not fit the expected layout.
    """
    # The time coordinate: one chunk of 64-bit integers, which gives the number of times
    hours = np.frombuffer(decode_chunk(f'{store}/time/0'), dtype='<i8')
    ntime = hours.size
    layout = {'time': ((ntime,), (ntime,)), 'cell': ((NCELL,), (CELL_COORD_CHUNK,)), 'crs': ((), ())}
    layout.update({name: ((ntime, NCELL), (TIME_CHUNK, CELL_CHUNK)) for name in FIELD_ATTRS})

    # Loop over the arrays: the chunk files on disk must be exactly those of the layout, none empty
    for name, (shape, chunks) in layout.items():
        expected = set(chunk_names(shape, chunks))
        found = {e.name: e.stat().st_size for e in os.scandir(f'{store}/{name}') if not e.name.startswith('.')}
        missing, extra = expected - set(found), set(found) - expected
        empty = [n for n, size in found.items() if size == 0]
        if missing or extra or empty:
            raise ValueError(f'{name}: {len(missing)} chunks missing, {len(extra)} unexpected, {len(empty)} empty')
    # The cell coordinate must be 0 .. NCELL-1
    cells = np.concatenate([np.frombuffer(decode_chunk(f'{store}/cell/{n}'), dtype='<i4') for n in sorted(chunk_names(*layout['cell']), key=int)])
    if not np.array_equal(cells, np.arange(NCELL)):
        raise ValueError('cell: the values are not 0 .. NCELL-1')
    return {'ntime': ntime, 'times': hours, 'layout': layout}


def template_dataset(info):
    """
    A lazy Dataset with the structure of the store (the fields hold no data).

    Args:
        info: dict
            Output of inspect_store.

    Returns:
        ds: xarray.Dataset
    """
    import dask.array as da
    import xarray as xr

    time = pd.Timestamp(FIRST_TIME) + pd.to_timedelta(info['times'], unit='h')
    shape = (info['ntime'], NCELL)
    fields = {name: (('time', 'cell'), da.zeros(shape, dtype='float32', chunks=(TIME_CHUNK, CELL_CHUNK)), attrs)
              for name, attrs in FIELD_ATTRS.items()}
    coords = {'time': time, 'cell': np.arange(NCELL, dtype='int32'), 'crs': xr.DataArray(np.int64(0), attrs=CRS_ATTRS)}
    return xr.Dataset(fields, coords=coords, attrs=GLOBAL_ATTRS)


def build(store, outdir):
    """
    Write the 15 metadata files to <outdir>/metadata/ and a test store that links to the original chunks.

    xarray writes the metadata of a template Dataset (compute=False writes no field data), so the xarray conventions of
    the original files are reproduced. The result is checked against the chunks of the original store.

    Args:
        store: str
            Original store (read only).
        outdir: str
            Output folder.

    Raises:
        ValueError: the new metadata does not agree with the chunks of the store.
    """
    info = inspect_store(store)
    print(f"chunks complete: {info['ntime']} times, {NCELL} cells")
    os.makedirs(outdir, exist_ok=True)
    lz4 = numcodecs.Blosc(cname='lz4', clevel=5, shuffle=1)
    zstd = numcodecs.Blosc(cname='zstd', clevel=3, shuffle=2)
    encoding = {name: {'compressors': zstd, 'chunks': (TIME_CHUNK, CELL_CHUNK), 'dtype': 'float32'} for name in FIELD_ATTRS}
    encoding['cell'] = {'compressors': lz4, 'chunks': (CELL_COORD_CHUNK,), 'dtype': 'int32'}
    encoding['time'] = {'compressors': lz4, 'chunks': (info['ntime'],), 'dtype': 'int64',
                        'units': f'hours since {FIRST_TIME}', 'calendar': 'proleptic_gregorian'}
    encoding['crs'] = {'compressors': None, 'dtype': 'int64'}

    meta_dir = os.path.join(outdir, 'metadata')
    with tempfile.TemporaryDirectory(dir=outdir) as tmp:
        template = os.path.join(tmp, 'template.zarr')
        template_dataset(info).to_zarr(template, mode='w', zarr_format=2, consolidated=True, compute=False, encoding=encoding)
        with open(f'{template}/.zmetadata') as stream:
            meta = json.load(stream)['metadata']

        # The new metadata must describe the chunks that exist: data type, chunk shape and compressor against the Blosc headers
        for name, (shape, chunks) in info['layout'].items():
            zarray = meta[f'{name}/.zarray']
            if tuple(zarray['shape']) != shape or tuple(zarray['chunks']) != chunks:
                raise ValueError(f"{name}: shape / chunks {zarray['shape']} {zarray['chunks']} differ from {shape} {chunks}")
            first = f'{store}/{name}/{chunk_names(shape, chunks)[0]}'
            itemsize = np.dtype(zarray['dtype']).itemsize
            if zarray['compressor'] is None:
                if os.path.getsize(first) != itemsize:
                    raise ValueError(f'{name}: the uncompressed chunk has {os.path.getsize(first)} bytes, expected {itemsize}')
                continue
            head, comp = blosc_header(first), zarray['compressor']
            expected = (head['cname'], head['shuffle'], head['typesize'], head['nbytes'])
            described = (comp['cname'], comp['shuffle'], itemsize, int(np.prod(chunks)) * itemsize)
            if expected != described:
                raise ValueError(f'{name}: chunk header {expected} (compressor, shuffle, type size, bytes) but metadata {described}')

        # The time coordinate that xarray just encoded must hold the same integers as the original chunk (checks the time units)
        if decode_chunk(f'{template}/time/0') != decode_chunk(f'{store}/time/0'):
            raise ValueError('time: the values encoded with the new metadata differ from the original chunk')
        # The scalar crs holds 0 (zarr does not write a chunk that equals the fill value, so the template may have no file)
        if open(f'{store}/crs/0', 'rb').read() != np.int64(0).tobytes():
            raise ValueError('crs: the original chunk is not the 64-bit integer 0')

        # Keep the metadata files only
        if os.path.isdir(meta_dir):
            shutil.rmtree(meta_dir)
        for rel in METADATA_FILES:
            os.makedirs(os.path.dirname(os.path.join(meta_dir, rel)), exist_ok=True)
            shutil.copyfile(os.path.join(template, rel), os.path.join(meta_dir, rel))
    print(f'wrote {len(METADATA_FILES)} metadata files to {meta_dir}')
    build_overlay(store, meta_dir, os.path.join(outdir, 'overlay_test.zarr'), info)


def build_overlay(store, meta_dir, overlay, info):
    """
    A test store: the new metadata files and symbolic links to the original chunk files.

    Args:
        store: str
            Original store.
        meta_dir: str
            Folder of the new metadata files.
        overlay: str
            Test store to make (replaced if it exists).
        info: dict
            Output of inspect_store.
    """
    if os.path.isdir(overlay):
        shutil.rmtree(overlay)           # removes the links and metadata copies only, never what the links point to
    shutil.copytree(meta_dir, overlay)
    nlinks = 0
    # Loop over the arrays and their chunks: one link per chunk
    for name, (shape, chunks) in info['layout'].items():
        for chunk in chunk_names(shape, chunks):
            os.symlink(f'{store}/{name}/{chunk}', f'{overlay}/{name}/{chunk}')
            nlinks += 1
    print(f'test store {overlay}: {nlinks} links to the original chunks')


def open_through_catalog(overlay, workdir):
    """
    Open the test store the way PyFLEXTRKR does: the intake catalog entry `scream_cess2` with zoom 9 and 1H, with the
    path of a scratch copy of the catalog pointed at the test store.

    Args:
        overlay: str
            Test store.
        workdir: str
            Folder of the scratch catalog.

    Returns:
        ds: xarray.Dataset
    """
    import intake
    import yaml

    with open(CATALOG) as stream:
        entry = yaml.safe_load(stream)['sources']['scream_cess2']
    entry['args']['urlpath'] = overlay
    path = os.path.join(workdir, 'catalog_test.yaml')
    with open(path, 'w') as stream:
        yaml.safe_dump({'sources': {'scream_cess2': entry}}, stream)
    return intake.open_catalog(path)['scream_cess2'](zoom=ZOOM, time='1H').to_dask()


def compare_with_pixels(ds, when, offset_hours=0):
    """
    Remap one time of the store to the 0.1 degree grid as PyFLEXTRKR does (idclouds_tbpf: nearest HEALPix cell, nested order,
    Tb from OLR, rain rate x 3.6e6) and compare it with the Cess2 MCS pixel file of that time.

    Args:
        ds: xarray.Dataset
            Rebuilt store (open_through_catalog).
        when: str
            Time of the pixel file.
        offset_hours: int (default: 0)
            Compare with the store this many hours later (a wrong time, to show that the test can fail).

    Returns:
        result: dict
            Share of pixels that agree and the largest difference, for Tb and precipitation.
    """
    import healpix as hp
    import netCDF4
    from pyflextrkr.ftfunctions import olr_to_tb

    stamp = pd.Timestamp(when)
    with netCDF4.Dataset(f'{PIXEL_DIR}/mcstrack_{stamp:%Y%m%d_%H%M%S}.nc') as pixel:
        lat, lon = np.asarray(pixel['lat'][:]), np.asarray(pixel['lon'][:])
        pix_tb = np.ma.filled(np.ma.asarray(pixel['tb'][0], dtype=float), np.nan)
        pix_rain = np.ma.filled(np.ma.asarray(pixel['precipitation'][0], dtype=float), np.nan)
    cells = hp.ang2pix(int(ds['crs'].attrs['healpix_nside']), *np.meshgrid(lon, lat), nest=True, lonlat=True)
    step = ds[['rlut', 'pr']].sel(time=stamp + pd.Timedelta(hours=offset_hours)).load()
    tb = olr_to_tb(step['rlut'].values[cells])
    rain = step['pr'].values[cells] * 3600000.0

    out = {'time': when}
    # Loop over the two fields: pixels that are finite in both, agreement within 0.01 K / 0.001 mm/h (float32 rounding)
    for name, new, old, tolerance in [('tb', tb, pix_tb, 0.01), ('rain', rain, pix_rain, 0.001)]:
        both = np.isfinite(new) & np.isfinite(old)
        difference = np.abs(new[both] - old[both])
        out[f'{name}_agree_pct'] = 100.0 * np.mean(difference <= tolerance)
        out[f'{name}_max_diff'] = float(difference.max())
        out[f'{name}_pixels'] = int(both.sum())
    return out


def verify(outdir, store=None):
    """
    Open a store (directly and through the catalog) and compare it with the MCS pixel files.

    Args:
        outdir: str
            Output folder: the scratch copy of the catalog and the table of the comparison are written there.
        store: str (default: None = the test store <outdir>/overlay_test.zarr)
            Store to verify, e.g. a repaired copy (read only).

    Returns:
        ok: bool
            True if every time agrees in at least 99.9 % of the pixels and the wrong-time control does not.
    """
    import xarray as xr

    store = store or os.path.join(outdir, 'overlay_test.zarr')
    print(f'store: {store}')
    direct = xr.open_zarr(store, consolidated=True)
    ds = open_through_catalog(store, outdir)
    print(ds)
    times = pd.DatetimeIndex(ds['time'].values)
    gaps = [(str(times[i]), str(times[i + 1])) for i in np.flatnonzero(np.diff(times.values) != np.timedelta64(1, 'h'))]
    print(f'times: {times[0]} .. {times[-1]}; steps that are not 1 h: {gaps}')
    print(f'direct open and catalog open have the same variables and shapes: '
          f'{ {k: direct[k].shape for k in direct.data_vars} == {k: ds[k].shape for k in ds.data_vars} }')

    # Loop over the test times, then the control: the same pixel file against the store one hour later
    rows = [compare_with_pixels(ds, when) for when in VERIFY_TIMES]
    control = compare_with_pixels(ds, VERIFY_TIMES[4], offset_hours=1)
    table = pd.DataFrame(rows + [{**control, 'time': control['time'] + ' (control: store +1 h)'}])
    print(table.to_string(index=False, float_format=lambda v: f'{v:.4f}'))
    table.to_csv(os.path.join(outdir, 'verify_pixels.csv'), index=False)
    agree = all(r['tb_agree_pct'] >= 99.9 and r['rain_agree_pct'] >= 99.9 for r in rows)
    ok = bool(agree and control['tb_agree_pct'] < 50)
    print('VERIFIED' if ok else 'NOT VERIFIED')
    return ok


def check_one_chunk(job):
    """
    Decode one chunk and compare its decompressed size with the expected one.

    Args:
        job: tuple
            (path, expected number of bytes, True if the chunk is Blosc-compressed).

    Returns:
        problem: str or None
            Description of the problem, None if the chunk is fine.
        size: int
            Size of the chunk file [bytes].
    """
    path, nbytes, compressed = job
    try:
        data = decode_chunk(path) if compressed else open(path, 'rb').read()
        size = os.path.getsize(path)
    except Exception as err:                                    # any read or decode error is a bad chunk
        return f'{path}: {type(err).__name__}: {err}', 0
    return (None if len(data) == nbytes else f'{path}: {len(data)} bytes, expected {nbytes}'), size


def check_chunks(store, workers):
    """
    Decode every chunk of a store (the original or a copy).

    Args:
        store: str
            Store folder (the metadata files are not needed).
        workers: int
            Parallel processes.

    Returns:
        ok: bool
            True if all chunks decode to the expected size.
    """
    info = inspect_store(store)
    itemsize = {'time': 8, 'cell': 4, 'crs': 8, **{name: 4 for name in FIELD_ATTRS}}
    jobs = [(f'{store}/{name}/{chunk}', int(np.prod(chunks)) * itemsize[name], name != 'crs')
            for name, (shape, chunks) in info['layout'].items() for chunk in chunk_names(shape, chunks)]
    with Pool(workers) as pool:
        results = pool.map(check_one_chunk, jobs, chunksize=8)
    problems = [p for p, _ in results if p]
    print(f'{store}: {len(jobs)} chunks decoded, {sum(s for _, s in results) / 1e9:.1f} GB on disk, {len(problems)} bad')
    for problem in problems[:20]:
        print('  ', problem)
    return not problems


def main(argv=None):
    """
    Run the chosen mode.

    Args:
        argv: list of str (default: None = sys.argv[1:])
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build', action='store_true', help='write the metadata files and the test store')
    mode.add_argument('--verify', action='store_true', help='compare the test store with the MCS pixel files')
    mode.add_argument('--check-chunks', action='store_true', help='decode every chunk of --store')
    p.add_argument('--store', default=None,
                   help=f'store to read (default: --verify the test store of --outdir; otherwise {STORE})')
    p.add_argument('--outdir', default=OUTDIR, help='output folder, never inside the store (default: %(default)s)')
    p.add_argument('--workers', type=int, default=32, help='processes of --check-chunks (default: %(default)s)')
    args = p.parse_args(argv)

    # The output folder must not be the store or lie inside it
    store = args.store or STORE
    if os.path.realpath(args.outdir).startswith(os.path.realpath(store)):
        sys.exit('ERROR: --outdir must not be inside the store')
    if args.build:
        build(store, args.outdir)
    elif args.verify:
        sys.exit(0 if verify(args.outdir, args.store) else 1)
    else:
        sys.exit(0 if check_chunks(store, args.workers) else 1)


if __name__ == '__main__':
    main()
