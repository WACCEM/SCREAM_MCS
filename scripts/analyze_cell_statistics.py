#!/usr/bin/env python
"""
Example script to read and analyze cell statistics from Parquet file.

This demonstrates how to work with the output from compute_cell_statistics.py

Usage:
    python analyze_cell_statistics.py <parquet_file>
"""

import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def load_and_explore(parquet_file):
    """Load Parquet file and show basic exploration."""
    print(f"Loading: {parquet_file}")
    df = pd.read_parquet(parquet_file)
    
    print(f"\nDataFrame shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(f"\nData types:\n{df.dtypes}")
    
    print(f"\n{'='*70}")
    print("BASIC STATISTICS")
    print('='*70)
    print(f"Total cells: {len(df):,}")
    print(f"Time range: {df['time'].min()} to {df['time'].max()}")
    print(f"Number of snapshots: {df['filename'].nunique()}")
    
    # Cells per snapshot
    cells_per_snapshot = df.groupby('filename').size()
    print(f"\nCells per snapshot:")
    print(f"  Mean: {cells_per_snapshot.mean():.1f}")
    print(f"  Median: {cells_per_snapshot.median():.0f}")
    print(f"  Std: {cells_per_snapshot.std():.1f}")
    print(f"  Min: {cells_per_snapshot.min()}")
    print(f"  Max: {cells_per_snapshot.max()}")
    
    # Cell area statistics
    print(f"\nCell area (km²):")
    print(f"  Mean: {df['area'].mean():.2f}")
    print(f"  Median: {df['area'].median():.2f}")
    print(f"  25th percentile: {df['area'].quantile(0.25):.2f}")
    print(f"  75th percentile: {df['area'].quantile(0.75):.2f}")
    print(f"  Max: {df['area'].max():.2f}")
    
    # Reflectivity statistics
    print(f"\nComposite reflectivity (dBZ):")
    print(f"  Mean: {df['max_dbz_comp'].mean():.2f}")
    print(f"  Median: {df['max_dbz_comp'].median():.2f}")
    print(f"  Max: {df['max_dbz_comp'].max():.2f}")
    
    print(f"\nLow-level reflectivity (dBZ):")
    print(f"  Mean: {df['max_dbz_lowlevel'].mean():.2f}")
    print(f"  Median: {df['max_dbz_lowlevel'].median():.2f}")
    print(f"  Max: {df['max_dbz_lowlevel'].max():.2f}")
    
    # Echo-top statistics (convert to km for readability)
    print(f"\nEcho-top heights (km):")
    for threshold in [10, 20, 30, 40, 50]:
        col = f'max_echotop{threshold}'
        if col in df.columns:
            echotop_km = df[col]
            print(f"  {threshold} dBZ - Mean: {echotop_km.mean():.2f}, "
                  f"Median: {echotop_km.median():.2f}, "
                  f"Max: {echotop_km.max():.2f}")
    
    return df


def example_queries(df):
    """Demonstrate some useful queries."""
    print(f"\n{'='*70}")
    print("EXAMPLE QUERIES")
    print('='*70)
    
    # Large cells
    large_cells = df[df['area'] > 1000]
    print(f"\n1. Cells larger than 1000 km²: {len(large_cells):,}")
    if len(large_cells) > 0:
        print(f"   Largest cell: {large_cells['area'].max():.2f} km²")
    
    # Intense cells
    intense_cells = df[df['max_dbz_comp'] > 60]
    print(f"\n2. Cells with max reflectivity > 60 dBZ: {len(intense_cells):,}")
    if len(intense_cells) > 0:
        print(f"   Most intense: {intense_cells['max_dbz_comp'].max():.2f} dBZ")
    
    # High echo-tops
    if 'max_echotop40' in df.columns:
        high_echotop = df[df['max_echotop40'] > 10]  # > 10 km
        print(f"\n3. Cells with 40 dBZ echo-top > 10 km: {len(high_echotop):,}")
        if len(high_echotop) > 0:
            print(f"   Highest: {high_echotop['max_echotop40'].max():.2f} km")
    
    # Time-based analysis
    df_with_hour = df.copy()
    df_with_hour['hour'] = df_with_hour['time'].dt.hour
    cells_by_hour = df_with_hour.groupby('hour').size()
    print(f"\n4. Cells by hour of day:")
    print(f"   Peak hour: {cells_by_hour.idxmax()} UTC ({cells_by_hour.max()} cells)")
    print(f"   Minimum hour: {cells_by_hour.idxmin()} UTC ({cells_by_hour.min()} cells)")
    
    # Geographic distribution
    print(f"\n5. Geographic extent:")
    print(f"   Longitude: {df['center_lon'].min():.2f}° to {df['center_lon'].max():.2f}°")
    print(f"   Latitude: {df['center_lat'].min():.2f}° to {df['center_lat'].max():.2f}°")


def example_filtering(df):
    """Demonstrate filtering and subsetting."""
    print(f"\n{'='*70}")
    print("EXAMPLE FILTERING")
    print('='*70)
    
    # Filter by multiple criteria
    strong_large = df[
        (df['area'] > 500) & 
        (df['max_dbz_comp'] > 50)
    ]
    print(f"\n1. Strong (>50 dBZ) and large (>500 km²) cells: {len(strong_large):,}")
    
    # Filter by time
    if len(df) > 0:
        mid_time = df['time'].min() + (df['time'].max() - df['time'].min()) / 2
        recent = df[df['time'] > mid_time]
        print(f"\n2. Cells in second half of time period: {len(recent):,}")
    
    # Filter by location (example: select region)
    region = df[
        (df['center_lon'] > 260) & (df['center_lon'] < 270) &
        (df['center_lat'] > 35) & (df['center_lat'] < 40)
    ]
    print(f"\n3. Cells in specific region (260-270°E, 35-40°N): {len(region):,}")


def example_aggregations(df):
    """Demonstrate aggregation operations."""
    print(f"\n{'='*70}")
    print("EXAMPLE AGGREGATIONS")
    print('='*70)
    
    # Statistics by time
    df_time = df.copy()
    df_time['date'] = df_time['time'].dt.date
    daily_stats = df_time.groupby('date').agg({
        'cell_id': 'count',
        'area': ['mean', 'max'],
        'max_dbz_comp': ['mean', 'max']
    })
    print(f"\n1. Daily statistics (first 5 days):")
    print(daily_stats.head())
    
    # Binned statistics
    print(f"\n2. Statistics by cell size category:")
    df_binned = df.copy()
    df_binned['size_category'] = pd.cut(
        df_binned['area'], 
        bins=[0, 100, 500, 1000, np.inf],
        labels=['Small (<100)', 'Medium (100-500)', 'Large (500-1000)', 'Very Large (>1000)']
    )
    size_stats = df_binned.groupby('size_category', observed=True).agg({
        'cell_id': 'count',
        'max_dbz_comp': 'mean',
        'max_echotop40': lambda x: x.mean() / 1000  # Convert to km
    })
    size_stats.columns = ['Count', 'Mean Max dBZ', 'Mean 40dBZ Echo-top (km)']
    print(size_stats)


def main():
    """Main function."""
    if len(sys.argv) < 2:
        print("Usage: python analyze_cell_statistics.py <parquet_file>")
        sys.exit(1)
    
    parquet_file = sys.argv[1]
    
    # Load and explore
    df = load_and_explore(parquet_file)
    
    if len(df) == 0:
        print("\nNo data to analyze!")
        return
    
    # Run example analyses
    example_queries(df)
    example_filtering(df)
    example_aggregations(df)
    
    print(f"\n{'='*70}")
    print("To work with this data in Python:")
    print('='*70)
    print("""
import pandas as pd

# Load the data
df = pd.read_parquet('cell_statistics.parquet')

# Example: Get all cells from a specific time
timestamp = pd.Timestamp('2020-04-01 12:00:00')
cells_at_time = df[df['time'] == timestamp]

# Example: Find largest cell
largest = df.loc[df['area'].idxmax()]

# Example: Filter strong cells
strong = df[df['max_dbz_comp'] > 55]

# Example: Daily mean area
daily_mean = df.groupby(df['time'].dt.date)['area'].mean()

# Example: Export to CSV for specific date
df[df['time'].dt.date == pd.Timestamp('2020-04-01').date()].to_csv('cells_20200401.csv')
    """)


if __name__ == '__main__':
    main()
