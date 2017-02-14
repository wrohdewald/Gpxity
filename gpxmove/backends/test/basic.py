# -*- coding: utf-8 -*-


# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
Tests for gpxmove.backends
"""

import unittest
import importlib
import os
import io
import datetime
import random
from inspect import getmembers, isclass, getmro
from pkgutil import get_data

import gpxpy
from gpxpy.gpx import GPXTrackPoint

from ...activity import Activity
from ...auth import Authenticate
from ...backend import Storage

# pylint: disable=attribute-defined-outside-init

__all__ = ['BasicTest']


class BasicTest(unittest.TestCase):
    """define some helpers"""

    allStorageClasses = None

 #   def __init__(self):
    #    super(BasicTest, self).__init__()

    def setup_auth(self, cls_, sub_name=None):
        """get auth data"""
        self.auth = Authenticate(cls_, sub_name).auth

    @staticmethod
    def create_unique_activity(storage, count, idx, what=None):
        """creates a unique activity in storage and returns it.
        test.gpx is used as a template.
        The last trackpoint will be placed at first_point + 50km + angle(idx * 360 / count)
        """
        if BasicTest.allStorageClasses is None:
            BasicTest.allStorageClasses = BasicTest._findStorageClasses()
        gpx_test_file = os.path.join(os.path.dirname(__file__), 'test.gpx')
        if not os.path.exists(gpx_test_file):
            raise Exception('MMTTests needs a GPX file named test.gpx for testing in {}'.format(
                os.getcwd()))

        data = io.StringIO(get_data(__package__, 'test.gpx').decode('utf-8'))
        gpx = gpxpy.parse(data)
        movement = gpxpy.geo.LocationDelta(distance=100000, angle=360 * idx / count)
        last_points = gpx.tracks[-1].segments[-1].points
        new_point = GPXTrackPoint(
            latitude=last_points[-1].latitude, longitude=last_points[-1].longitude + 0.001,
            time=last_points[-1].time + datetime.timedelta(hours=10, seconds=idx))
        new_point.move(movement)
        gpx.tracks[-1].segments[-1].points.append(new_point)
        result = Activity(storage=None, gpx=gpx)
        result.title = 'Random GPX # {}'.format(idx)
        result.description = 'Description to {}'.format(gpx.name)
        result.what = what or random.choice(Activity.legal_what)
        if storage:
            storage.save(result)
        return result

    def assertSameActivities(self, storage1, storage2): # pylint: disable=invalid-name
        """both storages must hold identical activities"""
        self.assertEqual(storage1, storage2, 'storage1:{} storage2:{}'.format(
            list(x.key() for x in storage1.activities),
            list(x.key() for x in storage2.activities)))

    def setup_storage(self, cls_, url=None, count=0, cleanup=True, clear_first=True, sub_name=None):
        """sets up an instance of a backend with count activities"""
        # TODO: document/rename sub_name
        self.setup_auth(cls_,  sub_name)
        result = cls_(url, auth=self.auth, cleanup=cleanup)
        if clear_first:
            result.remove_all()
        else:
            result.list_all()
        while count > len(result.activities):
            self.create_unique_activity(result, count, len(result.activities))
        return result

    @staticmethod
    def _findStorageClasses():
        """finds all storage classes. Those will be tested."""
        backends_directory = __file__
        while not backends_directory.endswith('backends'):
            backends_directory = os.path.dirname(backends_directory)
        if not os.path.exists(backends_directory):
            raise Exception('we are not where we should be')
        result = list()
        mod_names = os.listdir(backends_directory)
        for mod in mod_names:
            if not mod.endswith('.py'):
                continue
            mod = mod.replace('.py', '')
            if mod == '__init__':
                continue
            try:
                imported = importlib.__import__(mod, globals(), locals(), level=2)
                for name, cls in getmembers(imported, isclass):
                    if Storage in getmro(cls)[1:]:
                        # isinstance and is do not work here
                        result.append(cls)
            except ImportError:
                pass
        #sort because we want things reproducibly
        return sorted(set(result), key=lambda x:x.__class__.__name__)
