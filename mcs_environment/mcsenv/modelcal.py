"""Time axes of models with a noleap calendar (SCREAM, E3SM): a contiguous axis without 29 February.

The files of these models, and the MCS tracks made from them, carry calendar dates without 29 February: the hour after 28 February 23:00 is
1 March 00:00. Plain arithmetic on epoch seconds (a Gregorian axis) sees 25 h between those two hours, so "24 h before 1 March" would land on a
29 February that does not exist in the model, and a track that crosses the leap day would look 24 h longer than it is.

For a noleap source the extraction therefore does all time arithmetic (nominal times, nearest snapshots, durations) on the *model axis*: epoch
seconds with every completed 29 February removed (``to_model_axis``), and converts back to the calendar labels of the files only for the output
(``to_labels``). For a standard calendar (ERA5, observations) both functions are the identity. A noleap source whose track file contains
29 February labels is inconsistent and is refused (``leap_day_labels_present``).
"""

from __future__ import annotations

import numpy as np

from .fileindex import days_from_civil

# Epoch-second labels of the leap days between 1600 and 2400: start of 29 February, start of the following 1 March, and the model-axis time of
# that 1 March (its label minus one day for every leap day that has completed, including this one)
_YEARS = np.arange(1600, 2401)
_LEAP_YEARS = _YEARS[((_YEARS % 4 == 0) & (_YEARS % 100 != 0)) | (_YEARS % 400 == 0)]
_FEB29 = days_from_civil(_LEAP_YEARS, 2, 29) * 86400
_MARCH1 = _FEB29 + 86400
_MARCH1_ON_MODEL_AXIS = _MARCH1 - 86400 * (np.arange(_LEAP_YEARS.size) + 1)


def to_model_axis(label_s, calendar):
    """Epoch seconds on the contiguous model axis.

    Args:
        label_s: epoch seconds of calendar labels (array or scalar, int); for ``noleap`` no label may lie on a 29 February.
        calendar: ``"noleap"`` (every completed 29 February is removed) or ``"standard"`` (identity).

    Returns:
        int64 array on the model axis.
    """
    t = np.asarray(label_s, dtype=np.int64)
    if calendar != "noleap":
        return t
    return t - 86400 * np.searchsorted(_MARCH1, t, side="right")


def to_labels(axis_s, calendar):
    """Calendar labels (epoch seconds) of times on the model axis; the inverse of ``to_model_axis``.

    Args:
        axis_s: epoch seconds on the model axis (array or scalar, int).
        calendar: ``"noleap"`` or ``"standard"`` (identity).

    Returns:
        int64 array of calendar labels.
    """
    x = np.asarray(axis_s, dtype=np.int64)
    if calendar != "noleap":
        return x
    return x + 86400 * np.searchsorted(_MARCH1_ON_MODEL_AXIS, x, side="right")


def leap_day_labels_present(label_s):
    """True when any label lies on a 29 February (impossible in a noleap calendar).

    Args:
        label_s: epoch seconds of calendar labels.

    Returns:
        bool.
    """
    t = np.asarray(label_s, dtype=np.int64).ravel()
    position = np.searchsorted(_FEB29, t, side="right") - 1
    return bool(np.any((position >= 0) & (t < _MARCH1[np.clip(position, 0, _MARCH1.size - 1)])))

