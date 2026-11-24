"""Months and time axes: which month a file covers, and the time coordinate of the monthly output files.

The model files (noleap calendar) are stamped with the END of the averaging window and carry ``time_bnds``; the first bound is the first day of
the month the file is named for. ERA5 files (standard calendar) have no bounds and a ``time`` that is the first hour of the month (monthly
files) or every hour of the month (hourly files). ``check_file_month`` accepts both and refuses a file that covers another month.
"""

from __future__ import annotations

import cftime
import netCDF4
import numpy as np

# Units of the time axis of all monthly output files
TIME_UNITS = "days since 1850-01-01 00:00:00"
CALENDARS = ("noleap", "standard")


def month_range(start, end):
    """List of (year, month) from ``start`` to ``end`` inclusive.

    Args:
        start, end: ``(year, month)`` tuples.

    Returns:
        list of (year, month) tuples.
    """
    out, (y, m) = [], start
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_month(text):
    """``"YYYY-MM"`` (or a YAML value that prints like it) as a (year, month) tuple.

    Args:
        text: string such as ``"1995-01"``.

    Returns:
        (year, month) tuple. Raises ``ValueError`` for anything else.
    """
    try:
        year, month = str(text).strip().split("-")[:2]
        y, m = int(year), int(month)
    except ValueError:
        raise ValueError(f"'{text}' is not a month YYYY-MM") from None
    if not 1 <= m <= 12:
        raise ValueError(f"'{text}' is not a month YYYY-MM")
    return y, m


def month_start(year, month, calendar):
    """First instant of a month as a cftime object of the calendar (``noleap`` or ``standard``)."""
    return cftime.datetime(year, month, 1, calendar="noleap" if calendar == "noleap" else "standard")


def next_month(year, month):
    """(year, month) of the following month."""
    return (year + 1, 1) if month == 12 else (year, month + 1)


def days_in_month(year, month, calendar):
    """Number of days of a month in the calendar (``noleap``: February has 28 days)."""
    t0 = month_start(year, month, calendar)
    t1 = month_start(*next_month(year, month), calendar)
    return int(round((t1 - t0).total_seconds() / 86400.0))


def time_axis_values(year, month, calendar):
    """Time coordinate of one month: the mid-point of the month and its bounds, in days since 1850-01-01.

    Args:
        year, month: the month.
        calendar: ``"noleap"`` or ``"standard"``.

    Returns:
        (mid, bounds): float and a list of two floats, in ``TIME_UNITS`` of that calendar.
    """
    cal = "noleap" if calendar == "noleap" else "standard"
    b0 = netCDF4.date2num(month_start(year, month, calendar), TIME_UNITS, cal)
    b1 = netCDF4.date2num(month_start(*next_month(year, month), calendar), TIME_UNITS, cal)
    return float(0.5 * (b0 + b1)), [float(b0), float(b1)]


def _decode(values, ds, var="time"):
    """Decode time values with the units and calendar attributes of a file's time variable (list of cftime / datetime objects)."""
    tv = ds[var]
    return netCDF4.num2date(values, tv.units, getattr(tv, "calendar", "standard"), only_use_cftime_datetimes=False, only_use_python_datetimes=False)


def check_file_month(ds, year, month, calendar):
    """Verify that an open file covers a given month, and return the number of time records.

    Rules: with a ``time_bnds`` variable, the first bound must be the first day of the month and the last bound the first day of the next
    month; without it, every ``time`` value must lie inside the month. This catches the off-by-one month that file names of averaged output
    can hide.

    Args:
        ds: open ``netCDF4.Dataset``.
        year, month: the month the file should cover.
        calendar: calendar of the dataset (``"noleap"`` or ``"standard"``).

    Returns:
        number of time records (int). Raises ``ValueError`` when the file covers another month or has no record.
    """
    n_rec = len(ds.dimensions["time"])
    if n_rec == 0:
        raise ValueError(f"{ds.filepath()}: the file has no time record (an empty file)")
    if "time_bnds" in ds.variables:
        # Averaged output: the bounds are the averaging window
        b = np.asarray(ds["time_bnds"][:], dtype=np.float64)
        start, end = _decode(b[0, 0], ds), _decode(b[-1, 1], ds)
        if (start.year, start.month, start.day) != (year, month, 1):
            raise ValueError(f"{ds.filepath()}: the averaging window starts {start}, not {year}-{month:02d}-01")
        ny, nm = next_month(year, month)
        if (end.year, end.month, end.day) != (ny, nm, 1):
            raise ValueError(f"{ds.filepath()}: the averaging window ends {end}, expected the start of {ny}-{nm:02d}")
    else:
        # Instantaneous records: all of them must lie inside the month
        t = np.asarray(ds["time"][:], dtype=np.float64)
        first, last = _decode(t.min(), ds), _decode(t.max(), ds)
        if (first.year, first.month) != (year, month) or (last.year, last.month) != (year, month):
            raise ValueError(f"{ds.filepath()}: records from {first} to {last} are not inside {year}-{month:02d}")
    return n_rec
