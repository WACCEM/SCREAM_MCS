"""MCS track files and the sample table (nominal relative times and circle centres), built without Python loops over tracks.

Every track gets one row per nominal sample time ``t0 + k * step`` with ``t0`` the first time of the track (the MCS start) and ``k`` an integer:

* ``k = -24 h / step ... -1`` (pre-start): the circle stays at the start position;
* ``k = 0 ... floor((tn - t0) / step)`` (in-track): the circle is at the track centroid of that time.

``time_offset_hours = k * step`` is therefore the same grid for every track (time 0 exists for every track), which is what a composite by time
since initiation needs. The track point of a sample is the valid point nearest to the nominal time (ties go to the earlier point), clamped to the
track, so a gap or a NaN position uses the nearest existing point and the pre-start rows use the start position. Times are int64 seconds since
1970-01-01 UTC throughout.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# Multiplier that turns (track index, time in s) into one sortable int64 key; larger than any epoch second used (2**33 s is year 2242)
_KEY_SPAN = 1 << 33


def load_tracks(path, periods=None, start_date=None, end_date=None, lat_col="meanlat", lon_col="meanlon"):
    """Read the columns of an MCS track Parquet file that the extraction needs.

    Args:
        path: MCS track Parquet file (``mcs_tracks_final_combined_*.parquet``: one row per track hour, keys ``period`` and ``local_track``).
        periods: list of ``period`` values (year strings or ints) to read, or None for all (default None).
        start_date, end_date: keep only tracks whose first time lies in [start_date, end_date] (anything ``pandas.Timestamp`` accepts, UTC); default None.
        lat_col, lon_col: names of the track centre columns (default ``meanlat`` and ``meanlon``).

    Returns:
        DataFrame with columns ``period`` (str), ``local_track`` (int64), ``t`` (int64 epoch seconds), ``lat``, ``lon`` (float64), sorted by
        (period, local_track, t).
    """
    # Step 1: read only the needed columns, and only the requested periods (Parquet row filter)
    columns = ["period", "local_track", "base_time", lat_col, lon_col]
    filters = None if periods is None else [("period", "in", [str(p) for p in periods])]
    table = pq.read_table(path, columns=columns, filters=filters)
    # Step 2: plain numpy columns; the time becomes integer seconds (the tz of the file is UTC)
    seconds = np.asarray(table.column("base_time").to_numpy(zero_copy_only=False), dtype="datetime64[s]").astype(np.int64)
    out = pd.DataFrame({
        "period": np.asarray(table.column("period").to_pylist(), dtype=object),
        "local_track": np.asarray(table.column("local_track").to_numpy(zero_copy_only=False), dtype=np.int64),
        "t": seconds,
        "lat": np.asarray(table.column(lat_col).to_numpy(zero_copy_only=False), dtype=np.float64),
        "lon": np.asarray(table.column(lon_col).to_numpy(zero_copy_only=False), dtype=np.float64),
    })
    out = out.sort_values(["period", "local_track", "t"], kind="stable").reset_index(drop=True)
    # Step 3: optional selection of tracks by the time of their first row
    if start_date is not None or end_date is not None:
        first_t = out.groupby(["period", "local_track"], sort=False)["t"].transform("min")
        keep = np.ones(len(out), dtype=bool)
        if start_date is not None:
            keep &= first_t.to_numpy() >= _to_epoch_s(start_date)
        if end_date is not None:
            keep &= first_t.to_numpy() <= _to_epoch_s(end_date)
        out = out[keep].reset_index(drop=True)
    return out


def _to_epoch_s(value):
    """Epoch seconds (UTC) of a timestamp-like value (``pandas.Timestamp`` input, naive values are taken as UTC)."""
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.timestamp())


@dataclass
class Samples:
    """The sample table: one entry per (track, nominal time); all arrays have the length ``n`` and are ordered by (track, offset).

    Attributes:
        period: ``period`` of the track (object array of str).
        local_track: ``local_track`` of the track (int64).
        k: step index of the sample (int32; negative = before the MCS start).
        time_offset_hours: nominal offset from the track start in hours, ``k * step`` (float32).
        data_time: nominal time, ``t0 + k * step`` (int64 epoch seconds).
        track_time: time of the track point used as circle centre (int64 epoch seconds; the start time for the pre-start rows).
        track_dt_hours: ``clamp(data_time to the track) - track_time`` in hours: 0 unless the track has no valid point at the nominal time.
        center_lat, center_lon: circle centre (the track ``lat`` and ``lon`` at ``track_time``, longitude as in the track file).
        step_s: sample step in seconds.
        n_tracks, n_tracks_skipped: tracks read and tracks without any valid position (they have no samples).
        n_rows_dropped: track rows with a NaN position.
    """

    period: np.ndarray
    local_track: np.ndarray
    k: np.ndarray
    time_offset_hours: np.ndarray
    data_time: np.ndarray
    track_time: np.ndarray
    track_dt_hours: np.ndarray
    center_lat: np.ndarray
    center_lon: np.ndarray
    step_s: int
    n_tracks: int
    n_tracks_skipped: int
    n_rows_dropped: int

    def __len__(self):
        """Number of samples."""
        return int(self.data_time.size)


def build_samples(tracks, step_hours, pre_start_hours=24.0):
    """Vectorised sample table of all tracks (see the module docstring for the rules).

    Args:
        tracks: DataFrame of ``load_tracks`` (sorted by period, local_track, t; one row per track time; NaN positions allowed).
        step_hours: sample step in hours (a multiple of the track step, 1 h; for example 1, 3 or 6).
        pre_start_hours: hours before the track start that get rows (default 24; must be a multiple of the step).

    Returns:
        ``Samples`` with one entry per (track, nominal time).
    """
    # Step 1: arrays, step in seconds, and the number of pre-start steps
    step_s = int(round(float(step_hours) * 3600))
    pre_s = int(round(float(pre_start_hours) * 3600))
    if step_s <= 0 or pre_s < 0 or pre_s % step_s:
        raise ValueError(f"pre_start_hours ({pre_start_hours}) must be a multiple of step_hours ({step_hours})")
    k_pre = pre_s // step_s
    period = tracks["period"].to_numpy(dtype=object)
    local = tracks["local_track"].to_numpy(dtype=np.int64)
    t = tracks["t"].to_numpy(dtype=np.int64)
    lat = tracks["lat"].to_numpy(dtype=np.float64)
    lon = tracks["lon"].to_numpy(dtype=np.float64)
    n_rows = t.size
    if n_rows == 0:
        empty = np.zeros(0)
        return Samples(np.zeros(0, dtype=object), empty.astype(np.int64), empty.astype(np.int32), empty.astype(np.float32), empty.astype(np.int64),
                       empty.astype(np.int64), empty.astype(np.float32), empty, empty, step_s, 0, 0, 0)
    # Step 2: track boundaries (rows of one track are contiguous), and the checks on the order and on the uniqueness of the track keys
    new = np.empty(n_rows, dtype=bool)
    new[0] = True
    new[1:] = (period[1:] != period[:-1]) | (local[1:] != local[:-1])
    track_of_row = np.cumsum(new) - 1
    first_row = np.flatnonzero(new)
    last_row = np.r_[first_row[1:], n_rows] - 1
    n_tracks = first_row.size
    if (np.diff(t)[~new[1:]] <= 0).any():
        raise ValueError("track rows must be strictly increasing in time within a track")
    if not pd.MultiIndex.from_arrays([period[first_row], local[first_row]]).is_unique:
        raise ValueError("rows of one (period, local_track) are not contiguous")
    t0, tn = t[first_row], t[last_row]
    # Step 3: valid positions only (a NaN position cannot be a circle centre); per track the slice of the valid arrays
    ok = np.isfinite(lat) & np.isfinite(lon)
    v_time, v_lat, v_lon, v_track = t[ok], lat[ok], lon[ok], track_of_row[ok]
    n_valid = np.bincount(v_track, minlength=n_tracks)
    v_first = np.cumsum(n_valid) - n_valid
    keep = np.flatnonzero(n_valid > 0)
    # Step 4: rows per track, k = -k_pre ... floor((tn - t0) / step), laid out without a loop over tracks
    k_end = (tn - t0) // step_s
    per_track = (k_pre + k_end + 1)[keep]
    total = int(per_track.sum())
    sample_track = np.repeat(keep, per_track)
    offset_of_track = np.cumsum(per_track) - per_track
    k = np.arange(total, dtype=np.int64) - np.repeat(offset_of_track, per_track) - k_pre
    data_time = t0[sample_track] + k * step_s
    # Step 5: the circle centre is the valid track point nearest to the nominal time clamped to the track (ties -> earlier point); the search runs
    # on one sorted key (track index * span + time) so that all tracks are handled by a single searchsorted
    clamped = np.clip(data_time, t0[sample_track], tn[sample_track])
    key_valid = v_track.astype(np.int64) * _KEY_SPAN + v_time
    position = np.searchsorted(key_valid, sample_track.astype(np.int64) * _KEY_SPAN + clamped, side="left")
    lo = v_first[sample_track]
    hi = lo + n_valid[sample_track] - 1
    right, left = np.clip(position, lo, hi), np.clip(position - 1, lo, hi)
    use_left = np.abs(clamped - v_time[left]) <= np.abs(v_time[right] - clamped)
    matched = np.where(use_left, left, right)
    track_time = v_time[matched]
    return Samples(
        period=period[first_row][sample_track],
        local_track=local[first_row][sample_track],
        k=k.astype(np.int32),
        time_offset_hours=(k * (step_s / 3600.0)).astype(np.float32),
        data_time=data_time,
        track_time=track_time,
        track_dt_hours=((clamped - track_time) / 3600.0).astype(np.float32),
        center_lat=v_lat[matched],
        center_lon=v_lon[matched],
        step_s=step_s,
        n_tracks=int(n_tracks),
        n_tracks_skipped=int(n_tracks - keep.size),
        n_rows_dropped=int((~ok).sum()),
    )
