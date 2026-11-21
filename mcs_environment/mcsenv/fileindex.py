"""Which file and record holds which time: an index of the files of one stream that is independent of the file layout.

A *stream* is a set of files of one kind (for example the SCREAM 3-hourly ne30pg2 files). Files may hold one record or many (8 per day for 3-hourly
data, 24 for hourly data, a month of hourly data), may start at any time of the day (the SCREAM files start at 00:00 in October 1994 and at 03:00
later), may be empty or partly written, and may exist in several copies (``.nc~`` backups). ``FileIndex`` reads only the ``time`` variable of every
file once (in parallel), caches the result (re-reading only files whose size or modification time changed, which matters for a run that is still
writing) and then answers "which file and record holds the time T" by an exact lookup. Times are int64 seconds since 1970-01-01 UTC; the calendars
``noleap`` (SCREAM, E3SM) and ``standard`` (ERA5) are supported.
"""

from __future__ import annotations

import glob
import multiprocessing as mp
import os
import pickle
import re

import numpy as np

_CALENDARS = ("noleap", "365_day", "standard", "gregorian", "proleptic_gregorian")
_CACHE_VERSION = 2


def days_from_civil(year, month, day):
    """Days since 1970-01-01 of proleptic-Gregorian calendar dates (vectorised; every noleap date is also a valid Gregorian date).

    Args:
        year, month, day: integer arrays (or scalars) of the date.

    Returns:
        int64 array of the number of days since 1970-01-01.
    """
    # Howard Hinnant's days_from_civil: months are counted from March so that the leap day is the last day of the year
    y = np.asarray(year, dtype=np.int64) - (np.asarray(month) <= 2)
    m = np.asarray(month, dtype=np.int64)
    era = np.floor_divide(y, 400)
    yoe = y - era * 400
    doy = (153 * (m + np.where(m > 2, -3, 9)) + 2) // 5 + np.asarray(day, dtype=np.int64) - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def times_to_epoch_s(values, units, calendar="standard"):
    """Convert netCDF time values to int64 seconds since 1970-01-01 UTC (rounded to the second).

    Args:
        values: numeric time values of a file (array).
        units: CF units string, for example ``"days since 2009-01-01 00:00:00"``.
        calendar: CF calendar; ``noleap`` / ``365_day`` and ``standard`` / ``gregorian`` / ``proleptic_gregorian`` are supported (default ``standard``).

    Returns:
        int64 array of epoch seconds.
    """
    import cftime

    if calendar not in _CALENDARS:
        raise NotImplementedError(f"calendar '{calendar}' is not supported (supported: {_CALENDARS})")
    values = np.asarray(values, dtype=np.float64).ravel()
    if values.size == 0:
        return np.zeros(0, dtype=np.int64)
    # cftime gives calendar-aware dates; the date parts go through days_from_civil, the time of day is summed and rounded to the second
    dates = cftime.num2date(values, units, calendar=calendar, only_use_cftime_datetimes=True)
    year = np.array([d.year for d in dates])
    month = np.array([d.month for d in dates])
    day = np.array([d.day for d in dates])
    second_of_day = np.array([d.hour * 3600 + d.minute * 60 + d.second + round(d.microsecond / 1e6) for d in dates], dtype=np.int64)
    return days_from_civil(year, month, day) * 86400 + second_of_day


def calendar_kind(calendar_attribute):
    """``"noleap"`` or ``"standard"`` from the CF calendar attribute of a time variable.

    Args:
        calendar_attribute: CF calendar name (``noleap``, ``365_day``, ``standard``, ``gregorian``, ``proleptic_gregorian``).

    Returns:
        ``"noleap"`` or ``"standard"`` (an unknown calendar raises ``NotImplementedError``).
    """
    if calendar_attribute in ("noleap", "365_day"):
        return "noleap"
    if calendar_attribute in ("standard", "gregorian", "proleptic_gregorian"):
        return "standard"
    raise NotImplementedError(f"calendar '{calendar_attribute}' is not supported (supported: {_CALENDARS})")


def scan_file(path, time_var="time"):
    """Read the time axis of one file.

    Args:
        path: netCDF file.
        time_var: name of the time variable (default ``time``).

    Returns:
        (times_s, error, calendar): int64 epoch seconds of the records (empty for a file without records), None, and the calendar kind (``noleap`` or
        ``standard``); or (None, message, None) for a file that cannot be read.
    """
    import netCDF4

    try:
        with netCDF4.Dataset(path) as ds:
            var = ds.variables[time_var]
            calendar = getattr(var, "calendar", "standard")
            return times_to_epoch_s(var[:], var.units, calendar), None, calendar_kind(calendar)
    except Exception as exc:  # unreadable or partly written files must not stop the index (they become missing frames)
        return None, f"{type(exc).__name__}: {exc}", None


def _scan_job(args):
    """Pool worker: ``scan_file`` of one path; returns (path, times, error, calendar) so that results can be matched."""
    path, time_var = args
    return (path,) + scan_file(path, time_var)


def nearest_time(axis_s, query_s, step_s):
    """Nearest time of an axis for every query time, accepting only a shift within half a step.

    Args:
        axis_s: sorted int64 array of the available times (epoch seconds).
        query_s: int64 array of the wanted times.
        step_s: nominal step of the axis in seconds; a match needs ``-step/2 <= axis - query < step/2`` (ties go to the earlier time).

    Returns:
        (index, shift_s): index into ``axis_s`` of the match, -1 where nothing lies within half a step (missing frame, record end), and the
        shift ``axis - query`` in seconds of the nearest time (also where it was rejected).
    """
    axis = np.asarray(axis_s, dtype=np.int64)
    query = np.asarray(query_s, dtype=np.int64)
    if axis.size == 0:
        return np.full(query.shape, -1, dtype=np.int64), np.zeros(query.shape, dtype=np.int64)
    # First axis time at or after the query, and its predecessor; the nearer one wins, a tie goes to the earlier time
    position = np.searchsorted(axis, query, side="left")
    right, left = np.clip(position, 0, axis.size - 1), np.clip(position - 1, 0, axis.size - 1)
    choose_left = np.abs(query - axis[left]) <= np.abs(axis[right] - query)
    chosen = np.where(choose_left, left, right)
    shift = axis[chosen] - query
    accepted = (2 * shift >= -int(step_s)) & (2 * shift < int(step_s))
    return np.where(accepted, chosen, -1), shift


class FileIndex:
    """Index of the records of one stream: sorted unique times with the file and record of each.

    Attributes:
        times_s: sorted unique int64 epoch seconds of all records.
        paths: object array, the file of each time.
        recs: int32 array, the record index of each time inside its file.
        step_s: typical step of the axis in seconds (median of the differences).
        files: all matched files (sorted).
        empty_files: files without any record.
        unreadable: dictionary path -> error message of files that could not be read.
        n_duplicates: number of times that were found in more than one file (the file modified last is kept).
        calendar: ``"noleap"`` or ``"standard"``, the calendar of the files (None when no file could be read); files of one stream must agree.
    """

    def __init__(self, files, file_times, file_mtimes, unreadable=None, calendars=None):
        """Build the index from the per-file time axes (use ``FileIndex.build``).

        Args:
            files: list of file paths.
            file_times: list of int64 arrays, the times of each file (same order).
            file_mtimes: list of modification times of the files (decides which copy is kept for a duplicate time).
            unreadable: dictionary path -> error of files that could not be read (default None).
            calendars: list of calendar kinds of the files (None for unreadable files; default None = standard).
        """
        self.files = list(files)
        kinds = {c for c in (calendars or []) if c}
        if len(kinds) > 1:
            raise ValueError(f"the files of one stream use different calendars: {sorted(kinds)}")
        self.calendar = next(iter(kinds)) if kinds else ("standard" if calendars is None else None)
        self.unreadable = dict(unreadable or {})
        self.empty_files = [f for f, t in zip(files, file_times) if t is not None and t.size == 0]
        # One row per record of every readable file; for a time found twice the file with the later modification time (then the later name) wins
        counts = [0 if t is None else t.size for t in file_times]
        if sum(counts) == 0:
            self.times_s = np.zeros(0, dtype=np.int64)
            self.paths = np.zeros(0, dtype=object)
            self.recs = np.zeros(0, dtype=np.int32)
            self.step_s = 0
            self.n_duplicates = 0
            return
        times = np.concatenate([t for t in file_times if t is not None and t.size])
        file_id = np.repeat(np.arange(len(files)), counts)
        rec = np.concatenate([np.arange(c, dtype=np.int32) for c in counts if c])
        mtime = np.asarray(file_mtimes, dtype=np.float64)[file_id]
        order = np.lexsort((file_id, mtime, times))
        times, file_id, rec = times[order], file_id[order], rec[order]
        last_of_time = np.r_[times[1:] != times[:-1], True]
        self.n_duplicates = int((~last_of_time).sum())
        self.times_s = times[last_of_time]
        self.paths = np.asarray(self.files, dtype=object)[file_id[last_of_time]]
        self.recs = rec[last_of_time]
        self.step_s = int(np.median(np.diff(self.times_s))) if self.times_s.size > 1 else 0

    @classmethod
    def build(cls, root, pattern, time_var="time", nproc=1, cache_path=None, log=None):
        """Scan (or load from the cache) the files ``root/pattern`` of a stream.

        Args:
            root: directory of the files.
            pattern: glob pattern below ``root``, for example ``"*.INSTANT.nhours_x3.????-??-??-?????.nc"`` or ``"*/e5.oper.an.pl.128_133_q.*.nc"``.
            time_var: name of the time variable (default ``time``).
            nproc: processes used for scanning files (default 1; the scan is serial then).
            cache_path: pickle file that stores the per-file time axes between runs (default None = no cache). Files whose size and modification time
                are unchanged are not read again.
            log: function that prints a message (default None = silent).

        Returns:
            ``FileIndex``.
        """
        # Step 1: the files of the stream and their size and modification time
        files = sorted(glob.glob(os.path.join(root, pattern), recursive=True))
        if not files:
            raise FileNotFoundError(f"no files match {os.path.join(root, pattern)}")
        stat = {f: (os.stat(f).st_mtime, os.stat(f).st_size) for f in files}
        # Step 2: the cache of earlier scans (entry: path -> (mtime, size, times or None, error))
        cache = {}
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as handle:
                    stored = pickle.load(handle)
                if stored.get("version") == _CACHE_VERSION and stored.get("time_var") == time_var:
                    cache = stored["files"]
            except Exception:  # an unreadable cache is simply rebuilt
                cache = {}
        todo = [f for f in files if f not in cache or tuple(cache[f][:2]) != stat[f]]
        if log:
            log(f"  index {root}: {len(files)} files, {len(files) - len(todo)} from cache, {len(todo)} to scan")
        # Step 3: scan the new or changed files (processes: the netCDF library is not thread-safe)
        if todo:
            jobs = [(f, time_var) for f in todo]
            if nproc > 1 and len(todo) > 8:
                with mp.get_context("fork").Pool(min(nproc, len(todo))) as pool:
                    results = pool.map(_scan_job, jobs, chunksize=max(1, len(jobs) // (4 * nproc)))
            else:
                results = [_scan_job(j) for j in jobs]
            for path, times, error, calendar in results:
                cache[path] = (stat[path][0], stat[path][1], times, error, calendar)
            if cache_path:
                os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
                tmp = f"{cache_path}.tmp{os.getpid()}"
                with open(tmp, "wb") as handle:
                    pickle.dump({"version": _CACHE_VERSION, "time_var": time_var, "files": cache}, handle, protocol=4)
                os.replace(tmp, cache_path)
        # Step 4: the index of the files that exist now
        unreadable = {f: cache[f][3] for f in files if cache[f][3]}
        index = cls(files, [cache[f][2] for f in files], [stat[f][0] for f in files], unreadable, [cache[f][4] for f in files])
        if log:
            log(f"  index {root}: {index.times_s.size} times, step {index.step_s} s, calendar {index.calendar}, {len(index.empty_files)} empty and "
                f"{len(index.unreadable)} unreadable files, {index.n_duplicates} duplicate times")
        return index

    def lookup(self, query_s):
        """File and record of exact times.

        Args:
            query_s: int64 array of wanted times (epoch seconds).

        Returns:
            (paths, recs): object array of file paths and int32 array of records; ``''`` and -1 where the time is not in the stream.
        """
        query = np.asarray(query_s, dtype=np.int64)
        position = np.clip(np.searchsorted(self.times_s, query), 0, max(self.times_s.size - 1, 0))
        found = (self.times_s.size > 0) & (self.times_s[position] == query) if self.times_s.size else np.zeros(query.shape, dtype=bool)
        paths = np.where(found, self.paths[position] if self.times_s.size else "", "").astype(object)
        return paths, np.where(found, self.recs[position] if self.times_s.size else -1, -1).astype(np.int32)
