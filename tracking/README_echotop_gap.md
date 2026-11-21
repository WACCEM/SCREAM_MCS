# Echo-top gap and the SCREAM cell ETH (2026-10-11)

Question: the SCREAM convective-cell lifetime-maximum 10-dBZ echo-top height (ETH) is about 5 km below MRMS
(`.../figures/CellTrackStats/BinnedETH10dBZ_vs_CellDiameter_Jun_SCREAM_vs_MRMS_SE.png`). SCREAM has 128 vertical levels (30-300 m apart),
MRMS 33 (250 m, 500 m, 1 km), and `echotop_gap` is counted in levels: does a larger gap give a taller, more MRMS-like ETH?

## Answer: no. The gap changes the cell ETH by less than 0.2 km; the reflectivity above 8 km is what differs.

Per-cell maximum 10-dBZ ETH (the quantity of `maxETH_10dbz` in the cell track statistics, maximum over the expanded cell mask), SCREAM 2020-06-13 22:00-22:55Z,
12 frames, 10,120 cells with a diameter of at least 10 km, input of the 3-km cell tracking (`sfc_dz_min` 50 m):

| variant | median (km) | 25-75 % | 90 % |
|---|---|---|---|
| gap 1 level (today) | 8.29 | 6.7 - 9.2 | 9.9 |
| gap 2 | 8.32 | 6.8 - 9.2 | 9.9 |
| gap 4 | 8.35 | 6.8 - 9.3 | 10.0 |
| gap 16 | 8.44 | 6.9 - 9.3 | 10.1 |
| no limit (highest echo of the column) | 8.47 | 7.0 - 9.3 | 10.2 |
| holes up to 250 / 500 / 1000 m bridged | 8.33 / 8.35 / 8.37 | | 9.9 - 10.0 |
| sampled on the 33 MRMS levels, gap 1 / 2 | 8.0 / 8.5 | 6.5 - 9.0 | 10.0 |
| threshold -10 / -5 / 0 / 5 dBZ (gap 2) | 11.1 / 10.6 / 9.7 / 8.9 | 8.3 - 12.6 (-10 dBZ) | 13.5 / 13.3 / 13.1 / 12.4 |
| **MRMS, 10 dBZ, 2025-06-13 22:00-22:05Z** (2 frames, 999 cells) | **12.0** | 9.0 - 13.0 | 15.0 |

- Even with no gap limit at all the median rises by 0.2 km. The first layer is the lowest contiguous layer, and in the SCREAM columns of cells the 10-dBZ echo is
  one layer up to where it ends (`echotop_gap_examples.png` shows the columns with the largest difference: a 10-dBZ layer of a few hundred metres next to the surface and echo
  above a weak-echo region of 1 km or more, which no gap in this range bridges; the cell maximum is taken over many columns and is not affected). Gap 1 to 16, hole sizes in metres
  and MRMS-like sampling give the same result.
- MRMS is not sensitive to the gap either (12.0 km for every gap 1 to 16).
- The difference is in the reflectivity itself (`echotop_gap_profiles.png`), columns with a composite reflectivity of at least 40 dBZ:

| height | median dBZ SCREAM / MRMS | fraction above 10 dBZ SCREAM / MRMS |
|---|---|---|
| 6 km | 23.9 / 34.9 | 0.85 / 0.99 |
| 8 km | 9.9 / 27.6 | 0.50 / 0.98 |
| 10 km | -1.5 / 20.9 | 0.03 / 0.86 |
| 12 km | -18 / 14.0 | 0.01 / 0.61 |
| 14 km | -37 (floor) / (no value) | 0.00 / 0.30 |

  In SCREAM the reflectivity of strong columns drops by 33 dB between 4 and 10 km (31 to -1.5 dBZ), in MRMS by 20 dB (41 to 21 dBZ). In the whole SCREAM frame of 22:00Z no column has a 10-dBZ echo
  above 14.8 km (99.9th percentile 13.6 km).
- The only variant that closes most of the difference is a lower threshold: -10 dBZ gives 11.1 km against 12.0 km of MRMS at 10 dBZ. That is a statement about the reflectivity
  profile (the model's upper-level reflectivity is 20-30 dB lower than the MRMS 3-D mosaic; part of the MRMS value is probably radar beam broadening and vertical interpolation between
  elevation scans, part is the model's ice reflectivity), not a gap setting.

## Recommendation
- The SCREAM MCS config uses `echotop_gap: 8` (chosen by the user; the MRMS MCS config uses 2). By the numbers above that value is as good as any other from 1 to 16.
- For a like-for-like comparison with MRMS keep `echotop_gap` of the MRMS config of the same pipeline (cell tracking 1, MCS 2). Any value from 1 to 16 changes the SCREAM cell ETH by at most 0.2 km, which is
  3-4 % of the difference to MRMS; a metre-based gap option in `echotop_func.py` would not change this, so it is not proposed.
- For a like-for-like ETH comparison use the same dBZ level in a different way: compare ETH at 20 / 30 dBZ in both data sets (the gap is irrelevant there as well), or compare the
  reflectivity profiles (CFAD) directly; if a single "equivalent" SCREAM threshold is wanted, -10 to -5 dBZ matches the MRMS 10-dBZ ETH median in this case. One hour of one
  day (SCREAM 2020, MRMS 2025) is a small sample: the lifetime-maximum tracks of the whole June are the comparison to repeat before quoting a threshold.
- Not run: the full cell tracking of the 24 h with several gap values (planned) because the per-frame result shows no sensitivity; the frames and the tracking inputs are on CFS
  (`gap_test/input`, 288 frames 2020-06-13 12Z - 2020-06-14 11:55Z).

## Files
- `test_echotop_gap.py`: the screening (does not change PyFLEXTRKR), `plot_echotop_gap.py`: the figures.
- Output: `/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/CONUS/gap_test/screening/` (per-cell CSV, summary, profiles), figures in
  `.../figures/CellTrackStats/EchoTopGap/`.
- The echo-top is read from files on the zstash sub-folder; scratch OST 61 (`scratch-OST003d`) is down: files on it (101 of the 38,328 listed on 2020-10-11, listed in
  `gap_test/lists/`) hang on read. `lfs getstripe -i FILE` gives the OST index without touching the data.
