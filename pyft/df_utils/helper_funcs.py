"""Some useful functions for working with DataFrames that are used
multiple times in different places.
"""
from typing import Optional, Union, List

import pandas as pd
from pyft.geo_utils import haversine_distance


def convert_speed(meters_per_sec: Optional[Union[float, pd.Series]]) -> Optional[Union[float, pd.Series]]:
    """Converts meters/second to km/hour."""
    if meters_per_sec is not None:
        return meters_per_sec * 3.6
    else:
        return None

def get_lap_durations(laps: pd.DataFrame, points: pd.DataFrame) -> pd.Series:
    """Get durations of laps (or splits)."""
    start_times = laps['start_time']
    return start_times - start_times.shift(-1, fill_value=points.iloc[-1]['time'])


def get_lap_distances(points: pd.DataFrame) -> pd.Series:
    """Get approximate lap distances."""
    first = points[['cumul_distance_2d', 'lap']].groupby('lap').first()
    return first - first.shift(-1, fill_value=points.iloc[-1]['cumul_distance_2d'])

def get_lap_means(cols: List[str], points: pd.DataFrame, groupby: str = 'lap') -> pd.DataFrame:
    """Get mean heart rate, cadence, km/hr and miles/hr for lap (or split)."""
    if groupby not in cols:
        cols.append(groupby)
    return points[cols].groupby(groupby).mean()
