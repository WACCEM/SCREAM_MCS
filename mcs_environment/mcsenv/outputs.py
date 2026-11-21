"""Parquet output with units and attributes, and helpers to read it back.

The file is written with ``pyarrow`` (zstd). Every column carries its metadata (units, long name, source variables, conversion) in the Parquet
field metadata, and the file carries one JSON document (key ``mcs_env``) with everything needed to reproduce and interpret it: source, rules,
diameters, counts of samples and of missing frames, input index summary, code version. ``read_mcs_env`` returns a DataFrame with ``df.attrs``
filled from it.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Key of the file-level metadata document
META_KEY = b"mcs_env"


def timestamp_array(epoch_seconds):
    """Arrow timestamp array (milliseconds, UTC) from int64 epoch seconds (the type of the ``base_time`` column of the MCS track files).

    Args:
        epoch_seconds: int64 array of seconds since 1970-01-01 UTC.

    Returns:
        ``pyarrow`` array of type ``timestamp[ms, tz=UTC]``.
    """
    return pa.array(np.asarray(epoch_seconds, dtype=np.int64) * 1000, type=pa.int64()).cast(pa.timestamp("ms", tz="UTC"))


def write_mcs_env(path, columns, column_meta, file_meta, compression_level=3, row_group_size=1_000_000):
    """Write the output table with metadata, atomically (temporary file, then rename).

    Args:
        path: output ``.parquet`` file.
        columns: ordered dictionary column name -> ``pyarrow`` array (all of the same length).
        column_meta: dictionary column name -> dictionary of strings (units, long_name, ...); columns without an entry get no metadata.
        file_meta: JSON-serialisable dictionary stored under the key ``mcs_env``.
        compression_level: zstd level (default 3).
        row_group_size: rows per Parquet row group (default 1 million).

    Returns:
        None.
    """
    # Fields with their metadata, schema with the file metadata, then one table
    fields = [pa.field(name, array.type, metadata={k.encode(): str(v).encode() for k, v in column_meta.get(name, {}).items()} or None)
              for name, array in columns.items()]
    schema = pa.schema(fields, metadata={META_KEY: json.dumps(file_meta, default=str).encode()})
    table = pa.Table.from_arrays(list(columns.values()), schema=schema)
    # Write to a temporary name and rename, so that a stopped job never leaves a half-written file under the final name
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    pq.write_table(table, tmp, compression="zstd", compression_level=compression_level, row_group_size=row_group_size,
                   use_dictionary=[n for n, a in columns.items() if pa.types.is_dictionary(a.type) or pa.types.is_string(a.type)])
    os.replace(tmp, path)


def read_mcs_env(path, columns=None):
    """Read an output file into a DataFrame with the attributes restored.

    Args:
        path: ``.parquet`` file written by ``write_mcs_env``.
        columns: list of column names to read, or None for all (default None).

    Returns:
        DataFrame; ``df.attrs['mcs_env']`` is the file-level document, ``df.attrs['units']`` and ``df.attrs['long_name']`` map column to units / long name.
    """
    # Metadata first (cheap), then the data
    schema = pq.read_schema(path)
    df = pq.read_table(path, columns=columns).to_pandas()
    raw = (schema.metadata or {}).get(META_KEY)
    df.attrs["mcs_env"] = json.loads(raw) if raw else {}
    df.attrs["units"] = {f.name: f.metadata[b"units"].decode() for f in schema if f.metadata and b"units" in f.metadata}
    df.attrs["long_name"] = {f.name: f.metadata[b"long_name"].decode() for f in schema if f.metadata and b"long_name" in f.metadata}
    return df


def to_variable_frame(df, var):
    """One variable of an output table in the layout of the old per-variable files (for ``tools_mcs_stats.py``).

    Args:
        df: DataFrame of ``read_mcs_env`` (long format: one row per track, time and diameter).
        var: standard variable name (a column of ``df``).

    Returns:
        DataFrame with columns ``track_id`` (int64, unique per (period, local_track)), ``radius`` (the circle diameter in km, the column name that the
        old plotting functions filter on), ``time_offset_hours``, ``data_time`` and ``mean`` (the variable).
    """
    # A numeric period gives a readable id (period * 10**7 + local_track); other periods get consecutive numbers
    try:
        track_id = df["period"].astype(np.int64) * 10_000_000 + df["local_track"].astype(np.int64)
    except (ValueError, TypeError):
        track_id = pd.Series(pd.factorize(df["period"].astype(str) + "_" + df["local_track"].astype(str))[0], index=df.index)
    return pd.DataFrame({
        "track_id": track_id.to_numpy(),
        "radius": df["diameter_km"].to_numpy(),
        "time_offset_hours": df["time_offset_hours"].to_numpy(),
        "data_time": df["data_time"].to_numpy(),
        "mean": df[var].to_numpy(),
    })
