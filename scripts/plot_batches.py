"""
Run many plotting frames (e.g. one month of 5-minute data, 8,900 frames) on a Dask LocalCluster in batches.

Why: a dictionary of tracks given to dask.delayed(func)(file, track_dict, ...) is copied into every task, and
every worker deserializes its own copy for every frame (564 MB per frame for the May 2025 MCS + multi-cell tracks,
2 GB for the May 2025 cell tracks), which fills the workers' memory ("Unmanaged memory use is high", "Worker is
at 80% memory usage. Pausing worker"); all tasks of a month are also submitted to the scheduler at once.
Here the frames are processed in batches of consecutive times. For every batch only the tracks that are active
between its first and last frame are selected (subset_fn), they are sent once to every worker
(client.scatter, broadcast) and released before the next batch starts.

Used by plot_subset_cell_mcs_tracks_terrain.py and plot_subset_cell_tracks_terrain.py (--batch_size).
"""
import gc
import time
import ctypes
import numpy as np
import dask
from dask.distributed import Client, LocalCluster

# A track is still drawn this long after its end (the plotting scripts compare minutes); the batch window gets
# one more minute on both sides because those comparisons truncate to whole minutes
WINDOW_MARGIN = np.timedelta64(60, 's')


def release_memory():
    """
    Collect garbage and give the freed heap back to the OS. After a frame (arrays of 15-50 MB for the 1059 x 1799
    grid) glibc keeps the freed memory and the process grows by about 12 MB per frame (a worker: 1 GB after 15 frames,
    3 GB after 70 frames, "Unmanaged memory use is high"); with malloc_trim(0) after every frame it stays at its first value.
    """
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass     # not glibc


def default_batch_size(n_workers):
    """4 batches' worth of frames per worker: the idle time at the end of a batch (the slowest frame) stays small."""
    return 4 * int(n_workers)


def make_cluster(n_workers, tmp_dir="./"):
    """LocalCluster with one thread per worker (spawned processes; Dask's default MALLOC_TRIM_THRESHOLD_ applies)."""
    dask.config.set({'temporary-directory': tmp_dir})
    cluster = LocalCluster(n_workers=n_workers, threads_per_worker=1)
    client = Client(cluster)
    return cluster, client


def frame_times(basetimes):
    """Epoch seconds (UTC) of the frames -> numpy datetime64[s]."""
    return np.asarray(basetimes, dtype='float64').astype('int64').astype('datetime64[s]')


def subset_track_dict(track_dict, t_first, t_last):
    """
    The cell tracks (get_track_stats of the plotting scripts) that overlap the window of a batch: started at or
    before its last frame and ended less than dt_thres before its first frame. The arrays are loaded here, once,
    so that the workers neither read the stats file nor loop over all tracks of the period for every frame.
    Without start/end times in the dictionary it is returned unchanged.
    """
    start, end = track_dict.get('start_bt'), track_dict.get('end_bt')
    if start is None or end is None:
        return track_dict
    dt = np.timedelta64(int(track_dict['dt_thres'].total_seconds()), 's')
    keep = np.where((start <= t_last + WINDOW_MARGIN) & (end + dt + WINDOW_MARGIN >= t_first))[0]
    out = {k: v for k, v in track_dict.items() if k not in ('start_bt', 'end_bt')}
    out['ntracks'] = len(keep)
    for k in ('lifetime', 'cell_bt', 'cell_lon', 'cell_lat'):
        out[k] = track_dict[k].isel(tracks=keep).load()
    # time columns after the longest track of the batch hold nothing (the stats file has the columns of the
    # longest track of the whole period), so they are not sent to the workers
    if len(keep) > 0:
        valid = ~np.isnat(out['cell_bt'].values).all(axis=0)
        ncol = int(valid.nonzero()[0].max()) + 1 if valid.any() else 1
        for k in ('cell_bt', 'cell_lon', 'cell_lat'):
            out[k] = out[k].isel(times=slice(0, ncol))
    return out


def _safe_call(_func, _args, _common, **shared):
    """One frame; a failure is returned, not raised, so that the other frames of the run go on."""
    try:
        _func(*_args, **_common, **shared)
        return (_args[0], True, "")
    except Exception as e:
        return (_args[0], False, f"{type(e).__name__}: {e}")
    finally:
        release_memory()


def _run_batch(client, work_func, batch_items, shared, common):
    # The object goes in a list: scatter() of a dict scatters its entries under their own names ("lifetime", "ntracks",
    # ...), which collide with those of the previous batch ("Key lost during replication"). hash=False: a key of its own
    # for every scatter (the default key is the hash of the data, which is the same for equal data).
    futures_shared = {k: client.scatter([v], broadcast=True, hash=False)[0] for k, v in shared.items()}
    try:
        futures = [client.submit(_safe_call, work_func, args, common, pure=False, **futures_shared)
                   for args in batch_items]
        return client.gather(futures)
    finally:
        client.cancel(list(futures_shared.values()))


def run_in_batches(client, work_func, items, times, subset_fn, batch_size, common=None):
    """
    Args:
        client: dask.distributed.Client
        work_func: function(*item, **common, **shared) that makes one frame
        items: list of tuples, the positional arguments of every frame (the first one is its file name)
        times: numpy datetime64 array, time of every frame (sorted)
        subset_fn: function(t_first, t_last) -> dict of the objects shared by the frames of a batch (keyword
            arguments of work_func), e.g. {'track_dict': ..., 'mcs_dict': ...}
        batch_size: frames per batch
        common: dict, small keyword arguments of every frame

    Returns:
        failed: list of (file, message) of the frames that failed
    """
    common = common or {}
    n = len(items)
    nbatch = int(np.ceil(n / batch_size))
    failed = []
    t_run = time.time()
    print(f"{n} frames in {nbatch} batches of {batch_size}", flush=True)
    for ib in range(nbatch):
        i0, i1 = ib * batch_size, min((ib + 1) * batch_size, n)
        t_batch = time.time()
        shared = subset_fn(times[i0], times[i1 - 1])
        t_subset = time.time() - t_batch
        try:
            results = _run_batch(client, work_func, items[i0:i1], shared, common)
        except Exception as e:
            # e.g. a worker was killed and the scattered data are lost: once more with a fresh scatter
            print(f"batch {ib + 1}: {type(e).__name__}: {str(e)[:150]}, retrying once", flush=True)
            try:
                results = _run_batch(client, work_func, items[i0:i1], shared, common)
            except Exception as e2:
                results = [(a[0], False, f"batch failed: {type(e2).__name__}: {str(e2)[:150]}") for a in items[i0:i1]]
        bad = [(f, msg) for f, ok, msg in results if not ok]
        failed.extend(bad)
        print(f"batch {ib + 1}/{nbatch}: frames {i0 + 1}-{i1} of {n} in {time.time() - t_batch:.0f} s "
              f"(selecting the tracks {t_subset:.0f} s), {len(bad)} failed, elapsed {(time.time() - t_run) / 60:.1f} min", flush=True)
        del shared
    for f, msg in failed[:20]:
        print(f"FAILED {f}: {msg}", flush=True)
    if len(failed) > 20:
        print(f"... and {len(failed) - 20} more failed frames", flush=True)
    print(f"{n - len(failed)} of {n} frames done in {(time.time() - t_run) / 60:.1f} min", flush=True)
    return failed
