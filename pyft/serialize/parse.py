from abc import ABC
from datetime import datetime, timedelta
from typing import Optional, Callable, Tuple, Generator

import fitdecode
import lxml.etree
import numpy as np
import pandas as pd
import pytz
import gpxpy
from gpxpy import gpx
from pyft.config import Config
from pyft.geo_utils import haversine_distance
import logging

# logging.getLogger().setLevel(logging.INFO)

MILE = 1609.344  # metres in a mile


class GarminMixin:
    GARMIN_TYPES = {
        'hiking': 'hike',
        'running': 'run',
        'walking': 'walk'
    }


class BaseParser:
    ACTIVITY_TYPES = {'run', 'walk', 'hike'}

    # The DataFrame that is passed to infer_points_data must contain all of these columns
    INITIAL_COL_NAMES = (
        'point_no', 'track_no', 'segment_no',
        'latitude', 'longitude', 'elevation',
        'time', 'hr', 'cadence'
    )

    def __init__(self, fpath: str, config: Config):
        logging.debug(f'Parsing {fpath} using {type(self).__name__}.')
        self.config = config
        self._parse(fpath)

    def infer_points_data(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if missing := set(self.INITIAL_COL_NAMES).difference(df.columns):
            raise ValueError(f'DataFrame is missing the following columns: {missing}.')
        df = df.copy()
        prev_lat = df['latitude'].shift()
        prev_lon = df['longitude'].shift()
        df['step_length_2d'] = self.distance_2d(df['latitude'], df['longitude'], prev_lat, prev_lon)
        df['cumul_distance_2d'] = df['step_length_2d'].fillna(0).cumsum()
        df['km'] = (df['cumul_distance_2d'] // 1000).astype(int)
        df['mile'] = (df['cumul_distance_2d'] // MILE).astype(int)
        df['run_time'] = df['time'] - df.iloc[0]['time']
        logging.debug(f'Average step length (distance): {df["step_length_2d"].mean()}')
        # step_time = df['time'] - df['time'].shift()
        # logging.info(f'Average step length (time): {step_time.mean()}s')

        # Calculate speed / pace
        prev_time = df['time'].shift(self.config.speed_measure_interval)
        prev_cumul_distance = df['cumul_distance_2d'].shift(self.config.speed_measure_interval)
        interval_distance = df['cumul_distance_2d'] - prev_cumul_distance
        df['km_pace'] = (1000 / interval_distance) * (df['time'] - prev_time)
        df['mile_pace'] = (MILE / df['step_length_2d']) * (df['time'] - prev_time)
        df['kmph'] = (3600 / df['km_pace'].dt.total_seconds())
        df['mph'] = df['kmph'] / (MILE / 1000)
        return df

    def distance_2d(self, lat1: pd.Series, lon1: pd.Series, lat2: pd.Series, lon2: pd.Series) -> np.ndarray:
        return haversine_distance(lat1, lon1, lat2, lon2)

    def _parse(self, fpath: str):
        raise NotImplementedError('Child of BaseParser must implement a _parse method.')

    @property
    def points(self) -> pd.DataFrame:
        """Return a DataFrame with limited information on points (as
        described in INITIAL_COL_NAMES). The infer_points_data can be
        called on the resulting DataFrame to generate more data.
        """
        raise NotImplementedError('Child of BaseParser must implement a points property.')

    @property
    def date_time(self) -> datetime:
        raise NotImplementedError('Child of BaseParser must implement a date_time property.')

    @property
    def metadata(self) -> dict:
        raise NotImplementedError('Child of BaseParser must implement a metadata property.')

    @property
    def activity_type(self) -> str:
        raise NotImplementedError('Child of BaseParser must implement an activity_type property.')


class GPXParser(BaseParser, GarminMixin):
    NAMESPACES = {'garmin_tpe': 'http://www.garmin.com/xmlschemas/TrackPointExtension/v1'}

    # TODO: Move these to a separate file.
    # Also, unless we make them comprehensive, we should include a mechanism for Pyft to "learn" from
    # users manually setting an activity type on an activity with an unknown type.
    STRAVA_TYPES = {
        '4': 'hike',
        '9': 'run',
        '10': 'walk',
    }

    def _parse(self, fpath: str):
        with open(fpath) as f:
            self.gpx = gpxpy.parse(f)

    def _get_try_func(self, func: Callable[[gpx.GPXTrackPoint, gpx.GPXTrackPoint], float]) \
            -> Callable[[gpx.GPXTrackPoint, gpx.GPXTrackPoint], Optional[float]]:
        def _try_func(p1: gpx.GPXTrackPoint, p2: gpx.GPXTrackPoint) -> Optional[float]:
            try:
                return func(p1, p2)
            except AttributeError:
                return np.nan

        return _try_func

    def _get_hr(self, elem: lxml.etree._Element) -> Optional[int]:
        try:
            return int(elem.find('garmin_tpe:hr', self.NAMESPACES).text)
        except AttributeError:
            # "text" attribute not found, so presumably None
            return None

    def _get_cad(self, elem: lxml.etree._Element) -> Optional[int]:
        try:
            return int(elem.find('garmin_tpe:cad', self.NAMESPACES).text)
        except AttributeError:
            return None

    def _get_garmin_tpe(self, point: gpx.GPXTrackPoint) -> lxml.etree._Element:
        for ext in point.extensions:
            if ext.tag.startswith(f'{{{self.NAMESPACES["garmin_tpe"]}}}'):
                return ext

    def _iter_points(self) -> Generator[Tuple[
                                            int,
                                            int,
                                            int,
                                            float,
                                            float, Optional[float],
                                            datetime,
                                            Optional[int],
                                            Optional[int]
                                        ], None, None]:
        for point, track_no, segment_no, point_no in self.gpx.walk():
            ext = self._get_garmin_tpe(point)
            hr = self._get_hr(ext)
            cad = self._get_cad(ext)

            # Convert tz from "SimpleTZ" used by gpxpy)
            time = point.time.replace(tzinfo=pytz.FixedOffset(point.time.tzinfo.offset))
            yield (
                point_no, track_no, segment_no,
                point.latitude, point.longitude, point.elevation,
                time, hr, cad
            )

    @property
    def points(self) -> pd.DataFrame:
        """Return a DataFrame with limited information on points (as
        described in INITIAL_COL_NAMES). The infer_points_data can be
        called on the resulting DataFrame to generate more data.
        """
        df = pd.DataFrame(self._iter_points(), columns=self.INITIAL_COL_NAMES)
        df = self.infer_points_data(df)
        return df

    @property
    def date_time(self) -> datetime:
        try:
            return self.gpx.time.replace(tzinfo=pytz.FixedOffset(self.gpx.time.tzinfo.offset))
        except AttributeError:
            return self.gpx.time

    @property
    def metadata(self) -> dict:
        """Return (selected) metadata for GPX object."""
        return {
            'name': self.gpx.name,
            'description': self.gpx.description,
            'date_time': self.date_time,
            'activity_type': self.activity_type
        }

    @property
    def activity_type(self) -> str:
        activity_type = 'unknown'
        track_type = self.gpx.tracks[0].type
        if track_type in self.ACTIVITY_TYPES:
            activity_type = track_type
        elif self.gpx.creator.startswith('StravaGPX'):
            activity_type = self.STRAVA_TYPES.get(track_type, activity_type)
        elif self.gpx.creator.startswith('Garmin Connect'):
            activity_type = self.GARMIN_TYPES.get(track_type, activity_type)
        return activity_type


class FITParser(BaseParser, GarminMixin):

    MANDATORY_FIELDS = (
        'position_lat',
        'position_long',
        'timestamp'
    )

    OPTIONAL_FIELDS = (
        'altitude',
        'heart_rate',
        'cadence'
    )

    LATLON_TO_DECIMAL = (2 ** 32) / 360

    def __init__(self, *args, **kwargs):
        self._point = -1
        self._points_data = []
        self._backfill = []
        super().__init__(*args, **kwargs)

    def get_point_no(self) -> int:
        self._point += 1
        return self._point

    def _add_point(
        self,
        lat: Optional[float],
        lon: Optional[float],
        elev: Optional[float],
        timestamp: Optional[datetime],
        heart_rate: Optional[int],
        cadence: Optional[int]
    ):
        data = {
            'point_no': self.get_point_no(),
            'track_no': 0,
            'segment_no': 0,
            'latitude': None,
            'longitude': None,
            'elevation': elev,
            'time': timestamp,
            'hr': heart_rate,
            'cadence': cadence
        }
        # https://gis.stackexchange.com/questions/122186/convert-garmin-or-iphone-weird-gps-coordinates
        if (lat is not None):
            data['latitude'] = lat / self.LATLON_TO_DECIMAL
        if (lon is not None):
            data['longitude'] = lon / self.LATLON_TO_DECIMAL

        # Sometimes, the .FIT file will report elevation without reporting lat/lon data. In this case, we store
        # whatever data we find, and once we subsequently receive lat/lon data we "backfill" the missing data with that.
        if (lat is None) or (lon is None):
            self._backfill.append(data)
        else:
            if self._backfill:
                for to_add in self._backfill:
                    for k in data:
                        if (to_add[k] is None) and (data[k] is not None):
                            to_add[k] = data[k]
                    self._points_data.append(to_add)
                self._backfill = []
            self._points_data.append(data)

    def _parse(self, fpath: str):
        self._metadata = {
            'name': None,
            'date_time': None,
            'description': None,
            'activity_type': None
        }
        with fitdecode.FitReader(fpath) as fit:
            for frame in fit:
                if isinstance(frame, fitdecode.FitDataMessage):
                    if (self._metadata['date_time'] is None) and frame.has_field('timestamp'):
                        self._metadata['date_time'] = frame.get_value('timestamp')
                    #if (self._metadata['name'] is None) and frame.has_field('name'):
                    #    self._metadata['name'] = frame.get_value('name')
                    if (self._metadata['activity_type'] is None) and frame.has_field('sport'):
                        self._metadata['activity_type'] = self.GARMIN_TYPES.get(frame.get_value('sport'))
                    if frame.has_field('timestamp') and frame.has_field('altitude'):
                        self._add_point(
                            frame.get_value('position_lat', fallback=None),
                            frame.get_value('position_long', fallback=None),
                            frame.get_value('altitude'),
                            frame.get_value('timestamp'),
                            frame.get_value('heart_rate', fallback=None),
                            frame.get_value('cadence', fallback=None)
                        )
                    elif frame.has_field('timestamp') and frame.has_field('altitude'):
                        # Sometimes the .FIT file seems to report the altitude only, not lat/lon.
                        # In these cases, we wait to receive the position data in the next frame and
                        # "backfill" it.
                        to_backfill = (
                            frame.get_value('timestamp', fallback=None),
                            frame.get_value('altitude', fallback=None),
                            frame.get_value('heart_rate', fallback=None),
                            frame.get_value('cadence', fallback=None)
                        )
        self._points = self.infer_points_data(pd.DataFrame(self._points_data, columns=self.INITIAL_COL_NAMES))
        #print(self._points.iloc[0])

    @property
    def metadata(self) -> dict:
        return self._metadata

    @property
    def activity_type(self) -> str:
        return self._metadata['activity_type']

    @property
    def points(self) -> pd.DataFrame:
        return self._points

    @property
    def date_time(self) -> datetime:
        return self._metadata['date_time']


def parser_factory(fpath: str, config: Config) -> BaseParser:
    lower = fpath.lower()
    if lower.endswith('.gpx'):
        parser = GPXParser(fpath, config)
    elif lower.endswith('.fit'):
        parser = FITParser(fpath, config)
    else:
        raise ValueError(f'No suitable parser found for file "{fpath}".')
    return parser