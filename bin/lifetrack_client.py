#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

# PYTHON_ARGCOMPLETE_OK
# for command line argument completion, put this into your .bashrc:
# eval "$(register-python-argcomplete gpxdo)"
# or see https://argcomplete.readthedocs.io/en/latest/


"""lifetrack_client is a command line tool for lifetrack testing, client side."""

import argparse
import os
import sys
import logging
import time
import random

try:
    import argcomplete
    # pylint: disable=unused-import
except ImportError:
    pass

from gpxpy import gpx as mod_gpx
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment


# This uses not the installed copy but the development files
_ = os.path.dirname(sys.path[0] or sys.path[1])
if os.path.exists(os.path.join(_, 'gpxity', '__init__.py')):
    sys.path.insert(0, _)
# pylint: disable=wrong-import-position
from gpxity import GpxFile, Lifetrack, Backend, Directory, MMT, GPSIES, TrackMMT  # noqa


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
            source = Backend.instantiate(self.options.source)
            assert isinstance(source, GpxFile)
            backend = Backend.instantiate(self.options.backend)
            assert isinstance(backend, Backend)
            life = Lifetrack('127.0.0.1', [backend])
            all_points = list(source.points())
            life.start(all_points[:5])
            for point in all_points[5:]:
                time.sleep(random.randrange(10))
                life.update_tracker([point])
            time.sleep(random.randrange(10))
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
        parser.add_argument('--source', help='the gpxfile with test data')
        parser.add_argument('--backend', help='the server')
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
