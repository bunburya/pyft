"""Configuration.  Just a shell for testing at the moment.

TODO:  Implement proper configuration using ConfigParser.
"""
import json
import os
import configparser
from typing import Any, Dict, Optional

import appdirs

DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

class Config:

    def __init__(self, ini_fpath: str,
                 activity_graphs_fpath: Optional[str] = None,
                 overview_graphs_fpath: Optional[str] = None,
                 **kwargs):
        parser = configparser.ConfigParser()
        parser.read(ini_fpath)
        if parser['general']['data_dir'] is None:
            self.data_dir = appdirs.user_data_dir(appname='pyft')
        else:
            self.data_dir = parser['general']['data_dir']

        self.user_name = parser['general']['user_name']

        self.distance_unit = parser['general']['distance_unit']

        self.match_center_threshold = parser['general'].getfloat('match_center_threshold')
        self.match_length_threshold = parser['general'].getfloat('match_length_threshold')
        self.tight_match_threshold = parser['general'].getfloat('tight_match_threshold')

        self.default_activity_name_format = parser['general']['default_activity_name_format']

        self.week_start = parser['general']['week_start'].capitalize()
        week_start_i = DAYS_OF_WEEK.index(self.week_start)
        self.days_of_week = DAYS_OF_WEEK[week_start_i:] + DAYS_OF_WEEK[:week_start_i]

        for k in kwargs:
            setattr(self, k, kwargs[k])

        self.thumbnail_dir = os.path.join(self.data_dir, 'thumbnails')
        self.gpx_file_dir = os.path.join(self.data_dir, 'gpx_files')
        self.db_file = os.path.join(self.data_dir, 'pyft.db')

        for _dir in (self.data_dir, self.thumbnail_dir, self.gpx_file_dir):
            if not os.path.exists(_dir):
                os.makedirs(_dir)

        if activity_graphs_fpath is not None:
            try:
                with open(activity_graphs_fpath) as f:
                    self.activity_graphs = json.load(f)
            except (FileNotFoundError, json.decoder.JSONDecodeError):
                self.activity_graphs = []
        else:
            self.activity_graphs = []

        if overview_graphs_fpath is not None:
            try:
                with open(overview_graphs_fpath) as f:
                    self.overview_graphs = json.load(f)
            except (FileNotFoundError, json.decoder.JSONDecodeError):
                self.overview_graphs = []
        else:
            self.overview_graphs = []

        #print(self.activity_graphs)

    def config_to_file(self, fpath):
        # TODO
        pass