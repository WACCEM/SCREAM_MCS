"""
Calculate monthly & annual climatological mean MCS precipitation statistics from monthly data.
"""
__author__ = "Zhe.Feng@pnnl.gov"

import argparse
import glob
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import xarray as xr


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compute monthly climatological MCS precipitation statistics.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--indir", required=True,
                        help="Directory containing monthly mcs_rainmap_YYYYMM*.nc files")
    parser.add_argument("--outdir", required=True,
                        help="Output directory for climatology file")
    parser.add_argument("--start-date", required=True, metavar="YYYY-MM",
                        help="First year-month to include (e.g. 2001-01)")
    parser.add_argument("--end-date", required=True, metavar="YYYY-MM",
                        help="Last year-month to include (e.g. 2020-12)")
    return parser.parse_args()


def collect_files(indir, start_date, end_date):
    date_range = pd.date_range(start=start_date, end=end_date, freq="MS")
    mcsfiles = []
    for dt in date_range:
        matches = sorted(glob.glob(os.path.join(indir, f"mcs_rainmap_{dt:%Y%m}*.nc")))
        mcsfiles.extend(matches)
    if not mcsfiles:
        sys.exit(f"ERROR: No files found in {indir} for {start_date:%Y-%m} to {end_date:%Y-%m}")
    print(f"Number of input files: {len(mcsfiles)}")
    return mcsfiles


def main():
    args = parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m")
    end_date   = datetime.strptime(args.end_date,   "%Y-%m")

    os.makedirs(args.outdir, exist_ok=True)

    mcsfiles = collect_files(args.indir, start_date, end_date)

    # Lazy load
    ds = xr.open_mfdataset(mcsfiles, combine="nested", concat_dim="time", data_vars="minimal", compat="no_conflicts")

    # ---- Monthly climatology ----
    ntimes_month = ds["ntimes"].groupby("time.month").sum()

    # Precipitation rates: input is mm (monthly total) → mm/day
    totpcp_month  = 24 * ds["precipitation"].groupby("time.month").sum("time")  / ntimes_month
    mcspcp_month  = 24 * ds["mcs_precipitation"].groupby("time.month").sum("time") / ntimes_month
    mcsfrac_month = 100 * mcspcp_month / totpcp_month
    # Precipitation frequency and intensity
    mcspcpcount_month     = ds["mcs_precipitation_count"].groupby("time.month").sum("time")
    mcspcpfreq_month      = 100 * mcspcpcount_month / ntimes_month
    mcspcpintensity_month = (ds["mcs_precipitation"].groupby("time.month").sum("time")
                             / mcspcpcount_month)

    # Cloud frequency
    mcscloudcount_month = ds["mcs_cloud_count"].groupby("time.month").sum("time")
    mcscloudfreq_month  = 100 * mcscloudcount_month / ntimes_month

    # ---- Interannual std of annual means ----
    ntimes_year           = ds["ntimes"].groupby("time.year").sum("time")
    totpcp_annual         = 24 * ds["precipitation"].groupby("time.year").sum("time") / ntimes_year
    mcspcp_annual         = 24 * ds["mcs_precipitation"].groupby("time.year").sum("time") / ntimes_year
    mcsfrac_annual        = 100 * mcspcp_annual / totpcp_annual
    mcspcpcount_year      = ds["mcs_precipitation_count"].groupby("time.year").sum("time")
    mcspcpfreq_annual     = 100 * mcspcpcount_year / ntimes_year
    mcspcpint_annual      = (ds["mcs_precipitation"].groupby("time.year").sum("time")
                             / mcspcpcount_year)
    mcscloudcount_year    = ds["mcs_cloud_count"].groupby("time.year").sum("time")
    mcscloudfreq_annual   = 100 * mcscloudcount_year / ntimes_year

    totpcp_std       = totpcp_annual.std(dim="year")
    mcspcp_std       = mcspcp_annual.std(dim="year")
    mcsfrac_std      = mcsfrac_annual.std(dim="year")
    mcspcpfreq_std   = mcspcpfreq_annual.std(dim="year")
    mcspcpint_std    = mcspcpint_annual.std(dim="year")
    mcscloudfreq_std = mcscloudfreq_annual.std(dim="year")

    # ---- Build output dataset ----
    dim_names_3d = ["time", "lat", "lon"]
    dim_names_2d = ["lat", "lon"]
    dsout = xr.Dataset(
        {
            "precipitation":               (dim_names_3d, totpcp_month.data),
            "mcs_precipitation":           (dim_names_3d, mcspcp_month.data),
            "mcs_precipitation_frac":      (dim_names_3d, mcsfrac_month.data),
            "mcs_precipitation_freq":      (dim_names_3d, mcspcpfreq_month.data),
            "mcs_precipitation_intensity": (dim_names_3d, mcspcpintensity_month.data),
            "mcs_cloud_freq":              (dim_names_3d, mcscloudfreq_month.data),
            "precipitation_std":               (dim_names_2d, totpcp_std.data),
            "mcs_precipitation_std":           (dim_names_2d, mcspcp_std.data),
            "mcs_precipitation_frac_std":      (dim_names_2d, mcsfrac_std.data),
            "mcs_precipitation_freq_std":      (dim_names_2d, mcspcpfreq_std.data),
            "mcs_precipitation_intensity_std": (dim_names_2d, mcspcpint_std.data),
            "mcs_cloud_freq_std":              (dim_names_2d, mcscloudfreq_std.data),
        },
        coords={
            "time":  (["time"], pd.date_range("2000-01", periods=12, freq="MS")),
            "month": (["time"], np.arange(1, 13)),
            "lat":   (["lat"],  ds.lat.values),
            "lon":   (["lon"],  ds.lon.values),
        },
        attrs={
            "title":      "MCS precipitation climatology statistics",
            "contact":    "Zhe Feng, zhe.feng@pnnl.gov",
            "start_date": f"{start_date:%Y-%m}",
            "end_date":   f"{end_date:%Y-%m}",
            "created_on": pd.Timestamp.now().isoformat(),
            "created_by": __file__,
        },
    )

    # Coordinate attributes
    dsout.time.attrs.update({"long_name": "Calendar month (representative year 2000)"})
    dsout.month.attrs.update({"long_name": "Month number (1=Jan … 12=Dec)", "units": "1"})
    dsout.lat.attrs.update(ds.lat.attrs)
    dsout.lon.attrs.update(ds.lon.attrs)

    # Variable attributes
    dsout.precipitation.attrs.update({
        "long_name": "Total precipitation", "units": "mm/day"})
    dsout.mcs_precipitation.attrs.update({
        "long_name": "MCS precipitation", "units": "mm/day"})
    dsout.mcs_precipitation_frac.attrs.update({
        "long_name": "MCS precipitation fraction", "units": "%"})
    dsout.mcs_precipitation_freq.attrs.update({
        "long_name": "MCS precipitation frequency", "units": "%"})
    dsout.mcs_precipitation_intensity.attrs.update({
        "long_name": "MCS precipitation intensity", "units": "mm/hour"})
    dsout.mcs_cloud_freq.attrs.update({
        "long_name": "MCS cloud frequency", "units": "%"})
    dsout.precipitation_std.attrs.update({
        "long_name": "Total precipitation interannual std of annual means", "units": "mm/day"})
    dsout.mcs_precipitation_std.attrs.update({
        "long_name": "MCS precipitation interannual std of annual means", "units": "mm/day"})
    dsout.mcs_precipitation_frac_std.attrs.update({
        "long_name": "MCS precipitation fraction interannual std of annual means", "units": "%"})
    dsout.mcs_precipitation_freq_std.attrs.update({
        "long_name": "MCS precipitation frequency interannual std of annual means", "units": "%"})
    dsout.mcs_precipitation_intensity_std.attrs.update({
        "long_name": "MCS precipitation intensity interannual std of annual means", "units": "mm/hour"})
    dsout.mcs_cloud_freq_std.attrs.update({
        "long_name": "MCS cloud frequency interannual std of annual means", "units": "%"})

    # ---- Write output ----
    outfile = os.path.join(
        args.outdir,
        f"mcs_rainmap_monthly_climo_{start_date:%Y%m}_{end_date:%Y%m}.nc",
    )
    comp = dict(zlib=True, complevel=5, _FillValue=np.float32("nan"), dtype="float32")
    encoding = {var: comp for var in dsout.data_vars}
    # Coordinate variables should not have _FillValue
    for coord in dsout.coords:
        encoding[coord] = {"zlib": True, "_FillValue": None}

    dsout.to_netcdf(outfile, mode="w", format="NETCDF4", encoding=encoding)
    print(f"Output saved: {outfile}")


if __name__ == "__main__":
    main()
