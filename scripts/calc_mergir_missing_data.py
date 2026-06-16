"""
Calculate number of valid Tb data within a month from Combined Tb+IMERG 10km 30-minute data.
"""
__author__ = "Zhe.Feng@pnnl.gov"

import argparse
import calendar
import datetime
import glob
import os
import sys

import numpy as np
import pytz
import xarray as xr

DATADIR_TMPL = "/pscratch/sd/w/wcmca1/GPM/IR_IMERG_Combined_V07B/{year}/"
OUTDIR = "/pscratch/sd/w/wcmca1/GPM/IR_IMERG_Combined_V07B/stats"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compute monthly valid Tb data counts from Combined Tb+IMERG 10km 30-minute files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("year",  help="4-digit year (e.g. 2000)")
    parser.add_argument("month", help="2-digit month (e.g. 01)")
    return parser.parse_args()


def main():
    args = parse_args()
    year  = args.year
    month = args.month.zfill(2)

    datadir = DATADIR_TMPL.format(year=year)
    datafiles = sorted(glob.glob(os.path.join(datadir, f"merg_{year}{month}????_10km-pixel.nc")))
    if not datafiles:
        sys.exit(f"ERROR: No files found in {datadir} for {year}-{month}")
    print(f"Number of files: {len(datafiles)}")

    os.makedirs(OUTDIR, exist_ok=True)
    outfile = os.path.join(OUTDIR, f"merg_monthly_validcount_{year}{month}.nc")

    # Lazy load
    ds = xr.open_mfdataset(datafiles, concat_dim="time", combine='nested')
    ntimes = ds.sizes["time"]

    # Round minutes to nearest 30 to tolerate slight timestamp offsets
    rounded_min = (ds.time.dt.minute / 30).round().astype(int) * 30 % 60
    t00idx = np.where(rounded_min.values == 0)[0]
    t30idx = np.where(rounded_min.values == 30)[0]
    ntimes00 = len(t00idx)
    ntimes30 = len(t30idx)

    # Count valid (> 0) data at each sub-hour group, summed over time
    count00 = (ds.Tb.isel(time=t00idx) > 0).sum(dim="time")
    count30 = (ds.Tb.isel(time=t30idx) > 0).sum(dim="time") if ntimes30 > 0 else xr.zeros_like(count00)

    # Epoch time for the month
    epoch = np.array(
        [calendar.timegm(datetime.datetime(int(year), int(month), 1, 0, 0, 0, tzinfo=pytz.UTC).timetuple())],
        dtype=np.int64,
    )

    dsout = xr.Dataset(
        {
            "count_00min":  (["time", "lat", "lon"], count00.expand_dims("time", axis=0).data),
            "count_30min":  (["time", "lat", "lon"], count30.expand_dims("time", axis=0).data),
            "ntimes_00min": (["time"], np.array([ntimes00])),
            "ntimes_30min": (["time"], np.array([ntimes30])),
            "ntimes":       (["time"], np.array([ntimes])),
        },
        coords={
            "lon":  (["lon"],  ds.lon.values),
            "lat":  (["lat"],  ds.lat.values),
            "time": (["time"], epoch),
        },
        attrs={
            "title":      "Valid data counts",
            "contact":    "Zhe Feng, zhe.feng@pnnl.gov",
            "created_on": str(datetime.datetime.now()),
        },
    )

    dsout.time.attrs.update({
        "long_name": "Epoch Time (since 1970-01-01T00:00:00)",
        "units":     "seconds since 1970-1-1 0:00:00 0:00",
    })
    dsout.lon.attrs.update({"long_name": "Longitude", "units": "degree"})
    dsout.lat.attrs.update({"long_name": "Latitude",  "units": "degree"})
    dsout.count_00min.attrs.update({"long_name": "Valid data count at 00 min", "units": "count"})
    dsout.count_30min.attrs.update({"long_name": "Valid data count at 30 min", "units": "count"})
    dsout.ntimes_00min.attrs.update({"long_name": "Number of times at 00 min", "units": "count"})
    dsout.ntimes_30min.attrs.update({"long_name": "Number of times at 30 min", "units": "count"})
    dsout.ntimes.attrs.update({"long_name": "Number of times in the month",   "units": "count"})

    comp = dict(zlib=True, complevel=5, _FillValue=np.float32("nan"), dtype="float32")
    encoding = {var: comp for var in dsout.data_vars}
    for coord in dsout.coords:
        encoding[coord] = {"zlib": True, "_FillValue": None}

    print(f"Writing output: {outfile}")
    dsout.to_netcdf(outfile, mode="w", format="NETCDF4", unlimited_dims="time", encoding=encoding)
    print("Done.")


if __name__ == "__main__":
    main()
