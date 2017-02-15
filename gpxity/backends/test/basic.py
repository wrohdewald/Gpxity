# -*- coding: utf-8 -*-


# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
Tests for gpxity.backends
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
from ...backend import Backend

# pylint: disable=attribute-defined-outside-init

__all__ = ['BasicTest']


class BasicTest(unittest.TestCase):
    """define some helpers

    Attributes:
        all_backend_classes: a list of all backend implementations
        auth (tuple(str, str)): username/password
    """

    all_backend_classes = None

 #   def __init__(self):
    #    super(BasicTest, self).__init__()

    def setup_auth(self, cls_, sub_name=None):
        """get auth data. Save it in self.auth

        Args:
            cls_ (Backend): The backend class
            sub_name: for more specific username/passwords, see :class:`gpxity.auth.Authenticate`
        """
        self.auth = Authenticate(cls_, sub_name).auth

    @staticmethod
    def create_unique_activity(count, idx, what=None):
        """creates a unique activity and returns it.
        test.gpx is used as a template.
        The last trackpoint will be placed at first_point + 50km + angle(idx * 360 / count)
        """
        if BasicTest.all_backend_classes is None:
            BasicTest.all_backend_classes = BasicTest._find_backend_classes()
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
        result = Activity(backend=None, gpx=gpx)
        result.title = 'Random GPX # {}'.format(idx)
        result.description = 'Description to {}'.format(gpx.name)
        result.what = what or random.choice(Activity.legal_what)
        return result

    def assertSameActivities(self, backend1, backend2): # pylint: disable=invalid-name
        """both backends must hold identical activities"""
        self.assertEqual(backend1, backend2, 'backend1:{} backend2:{}'.format(
            list(x.key() for x in backend1.activities),
            list(x.key() for x in backend2.activities)))

    def setup_backend(self, cls_, url=None, count=0, cleanup=True, clear_first=True, sub_name=None):
        """sets up an instance of a backend with count activities

        Args:
            cls_ (Backend): the class of the backend to be created
            url (str): the url for the backend
            count (int): how many random activities should be inserted?
            cleanup (bool): If True, remve all activities when done. Passed to the backend.
            clear_first (bool): if True, first remove all existing activities
            sub_name (str): use this to get specific username/passwords from Authenticate

        Returns:
            the prepared Backend
        """

        self.setup_auth(cls_, sub_name)
        result = cls_(url, auth=self.auth, cleanup=cleanup)
        if clear_first:
            result.remove_all()
        else:
            result.list_all()
        while count > len(result.activities):
            activity = self.create_unique_activity(count, len(result.activities))
            result.save(activity)
        return result

    @staticmethod
    def _find_backend_classes():
        """finds all backend classes. Those will be tested."""
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
                for _, cls in getmembers(imported, isclass):
                    if Backend in getmro(cls)[1:]:
                        # isinstance and is do not work here
                        result.append(cls)
            except ImportError:
                pass
        #sort because we want things reproducibly
        return sorted(set(result), key=lambda x: x.__class__.__name__)
