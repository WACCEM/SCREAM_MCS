#!/usr/bin/env python
"""How well do the humidity conversions of ``mcsenv.derive`` reproduce the fields that E3SM stores?

The SCREAM environment files hold relative humidity and temperature at 850 hPa but no specific humidity, so ``q850`` is derived (``q_from_rh``). The E3SM
ne120 hourly files (h1) hold all three (``T850``, ``RH850``, ``Q850``; also ``T700``, ``RH700``, ``Q700``), which allows the conversions to be checked
against the model's own values. The model interpolates T, RH and Q to the pressure level independently, so a difference of a few percent is expected
and is not an error of the formula; this script measures it on several times of the record (cells whose level lies above the ground only).

Example:  python validate_humidity_formulas.py
"""

import os
import sys

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import netCDF4  # noqa: E402
import numpy as np  # noqa: E402

from mcsenv.derive import q_from_rh, rh_from_q  # noqa: E402

RUN = "/pscratch/sd/p/plma/e3sm_scratch/v3/E3SMv3_ne120/run/E3SMv3_ne120.eam.h1.{day}-00000.nc"
# Days spread over the record and records (hours) of the day
TIMES = [("2009-02-10", 0), ("2009-06-15", 12), ("2009-10-20", 6), ("2010-03-05", 18), ("2010-08-11", 3), ("2011-01-25", 15), ("2011-07-04", 21)]


def main():
    """Print the relative error of q850 from (T850, RH850) and the RH700 difference from (T700, Q700) for several times."""
    print(f"{'time':>16s} | {'q850 from T,RH vs Q850: mean':>29s} {'rms':>7s} {'p99|err|':>9s} | {'RH700 from T,Q vs RH700: bias':>30s} {'rms':>7s} (%-points)")
    rel_all, drh_all = [], []
    for day, hour in TIMES:
        with netCDF4.Dataset(RUN.format(day=day)) as ds:
            g = lambda v: np.asarray(ds.variables[v][hour, :], dtype=np.float64)  # noqa: E731
            ps, t850, rh850, q850, t700, rh700, q700 = (g(v) for v in ("PS", "T850", "RH850", "Q850", "T700", "RH700", "Q700"))
        # Cells whose level lies above the ground (the models extrapolate below it)
        ok8, ok7 = ps > 87000.0, ps > 77000.0
        rel = (q_from_rh(rh850[ok8] / 100.0, t850[ok8], 85000.0) - q850[ok8]) / q850[ok8]
        drh = 100.0 * rh_from_q(q700[ok7], t700[ok7], 70000.0) - rh700[ok7]
        rel_all.append(rel), drh_all.append(drh)
        print(f"{day + ' ' + str(hour).zfill(2) + 'Z':>16s} | {100 * rel.mean():+28.2f} % {100 * np.sqrt((rel ** 2).mean()):6.2f}% {100 * np.percentile(np.abs(rel), 99):8.1f}% | "
              f"{drh.mean():+29.2f} {np.sqrt((drh ** 2).mean()):7.2f}")
    rel, drh = np.concatenate(rel_all), np.concatenate(drh_all)
    print(f"{'all times':>16s} | {100 * rel.mean():+28.2f} % {100 * np.sqrt((rel ** 2).mean()):6.2f}% {100 * np.percentile(np.abs(rel), 99):8.1f}% | "
          f"{drh.mean():+29.2f} {np.sqrt((drh ** 2).mean()):7.2f}")


if __name__ == "__main__":
    main()
