#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

# PYTHON_ARGCOMPLETE_OK
# for command line argument completion, put this into your .bashrc:
# eval "$(register-python-argcomplete gpxdo)"
# or see https://argcomplete.readthedocs.io/en/latest/


"""lifetrack_client is a command line tool for lifetrack testing, client side.

It can also use a GPS mouse as source."""

import argparse
import os
import sys
import logging
import datetime
import time
import random
import serial

try:
    import argcomplete
    # pylint: disable=unused-import
except ImportError:
    pass

try:
    from pynmea2 import parse as parse_nmea
    from pynmea2.nmea import ParseError
    HAVE_NMEA = True
except ImportError:
    HAVE_NMEA = False

from gpxpy import gpx as mod_gpx
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXTrackPoint = mod_gpx.GPXTrackPoint


# This uses not the installed copy but the development files
_ = os.path.dirname(sys.path[0] or sys.path[1])
if os.path.exists(os.path.join(_, 'gpxity', '__init__.py')):
    sys.path.insert(0, _)
# pylint: disable=wrong-import-position
from gpxity import GpxFile, Lifetrack, Backend # noqa

class Source:

    """Abstract API for either GPX file or a GPS mouse."""

    # pylint: disable=too-few-public-methods

    def __init__(self, name):
        self.name = name
        if name.startswith('/dev/'):
            if not HAVE_NMEA:
                print('The python library pynmea2 is not available')
                sys.exit(2)
            self.__source = serial.Serial(name)
        else:
            self.__source = Backend.instantiate(name)
            assert isinstance(self.__source, GpxFile)

    def points(self):
        """Return the points."""
        altitude = None
        if isinstance(self.__source, serial.Serial):
            visible_sats = {}
            while True:
                raw = self.__source.readline().decode()
                provider = raw[1:3]
                try:
                    msg = parse_nmea(raw)
                    if hasattr(msg, 'altitude'):
                        altitude = msg.altitude
                    if msg.sentence_type == 'RMC':
                        if msg.is_valid:
                            logging.debug('RMC: %s', msg)
                            yield  GPXTrackPoint(
                                latitude=msg.latitude,
                                longitude=msg.longitude,
                                time=msg.datetime.replace(
                                    microsecond=0, tzinfo=datetime.timezone.utc),
                                elevation=altitude)
                        else:
                            logging.debug('INVALID RMC: %s', msg)
                    elif msg.sentence_type == 'GSV' and int(msg.msg_num) == 1:
                        if visible_sats.get(provider) != msg.num_sv_in_view:
                            visible_sats[provider] = msg.num_sv_in_view
                            logging.debug('Visible satellites: %s', visible_sats)
                except ParseError:
                    pass
        else:
            for _ in self.__source.points():
                time.sleep(random.randrange(10))
                yield _

class Main:

    """this is where the work is done."""

    def __init__(self):
        """No args."""
        # pylint: disable=too-many-branches,too-many-nested-blocks

        self.exit_code = 0
        self.options = None
        self.parse_commandline()
        if self.exit_code:
            return
        self.logger = logging.getLogger()
        self.logger.setLevel(self.options.loglevel.upper())
        self.source = None
        try:
            source = Source(self.options.source)
            backends = []
            tracker_id = None
            for _ in self.options.backend:
                backend = Backend.instantiate(_)
                if not isinstance(backend, Backend):
                    tracker_id = backend.id_in_backend
                    backend = backend.backend
                backends.append(backend)
            life = None
            for point in source.points():
                if life is None:
                    life = Lifetrack('127.0.0.1', backends, tracker_id=tracker_id)
                    life.start([point])
                else:
                    life.update_trackers([point])
            life.end()
        except Exception as _:  # pylint: disable=broad-except
            self.error(_)

    def error(self, msg, exit_code=None):
        """Print the error message.
        Sets the process exit code.
        With --debug, re-raises the exception."""
        self.logger.error(msg)
        self.exit_code = exit_code or 1
        if self.logger.level == logging.DEBUG:
            raise msg

    def parse_commandline(self):
        """into self.options."""
        # pylint: disable=too-many-statements, too-many-branches
        parser = argparse.ArgumentParser('lifetrack_client')
        parser.add_argument('--source', help='the gpxfile with test data', required=True)
        parser.add_argument('--backend', help='the server', required=True, action='append')
        parser.add_argument(
            '--loglevel', help='set the loglevel',
            choices=('debug', 'info', 'warning', 'error'), default='error')
        try:
            argcomplete.autocomplete(parser)
        except NameError:
            pass

        if len(sys.argv) < 2:
            parser.print_usage()
            sys.exit(2)

        self.options = parser.parse_args()


sys.exit(Main().exit_code)
