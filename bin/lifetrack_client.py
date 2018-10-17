#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
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
    from argcomplete import ChoicesCompleter  # noqa
except ImportError:
    pass

from gpxpy import gpx as mod_gpx
GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment


# This uses not the installed copy but the development files
_ = os.path.dirname(sys.path[0] or sys.path[1])
if os.path.exists(os.path.join(_, 'gpxity', '__init__.py')):
    sys.path.insert(0, _)
# pylint: disable=wrong-import-position
from gpxity import Track, Lifetrack, Backend, Directory, MMT, GPSIES, TrackMMT  # noqa


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
            assert isinstance(source, Track)
            backend = Backend.instantiate(self.options.backend)
            assert isinstance(backend, Backend)
            try:
                life = Lifetrack('127.0.0.1', [backend])
                all_points = list(source.points())
                life.start(all_points[:5])
                for point in all_points[5:]:
                    time.sleep(random.randrange(10))
                    life.update([point])
                time.sleep(random.randrange(10))
                life.end()
            finally:
                backend.destroy()
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

    def instantiate_object(self, name):
        """return a backend for name.
        If name is a single track, the returned backend has a match filtering
        only this one wanted track."""
        # pylint: disable=too-many-branches
        result = account = track_id = None
        if ':' in name and name.split(':')[0].upper() in ('MMT', 'GPSIES', 'TRACKMMT'):
            clsname = name.split(':')[0].upper()
            rest = name[len(clsname) + 1:]
            if '/' in rest:
                if rest.count('/') > 1:
                    raise Exception('wrong syntax in {}'.format(name))
                account, track_id = rest.split('/')
            else:
                account = rest
            if clsname == 'MMT':
                result = MMT(auth=account, timeout=self.options.timeout)
            elif clsname == 'TRACKMMT':
                result = TrackMMT(auth=account, timeout=self.options.timeout)
            elif clsname == 'GPSIES':
                result = GPSIES(auth=account, timeout=self.options.timeout)
        else:
            if os.path.isdir(name):
                account = name
                result = Directory(url=account)
            else:
                if name.endswith('.gpx'):
                    name = name[:-4]
                if os.path.isfile(name + '.gpx'):
                    account = os.path.dirname(name) or '.'
                    track_id = os.path.basename(name)
                result = Directory(url=account)
        if account is None:
            raise Exception('{} not found'.format(name))
        if track_id:
            result = result[track_id]
        return result

    def parse_commandline(self):
        """into self.options."""
        # pylint: disable=too-many-statements, too-many-branches
        parser = argparse.ArgumentParser('lifetrack_client')
        parser.add_argument('--source', help='the track with test data')
        parser.add_argument('--backend', help='the server')
        parser.add_argument(
            '--loglevel', help='set the loglevel',
            choices=('debug', 'info', 'warning', 'error'), default='error')
        parser.add_argument('--timeout', help="""
            Timeout: Either one value in seconds or two comma separated values: The first one is the connection
            timeout, the second one is the read timeout. Default is to wait forever.""", type=str, default=None)

        try:
            argcomplete.autocomplete(parser)
        except NameError:
            pass

        if len(sys.argv) < 2:
            parser.print_usage()
            sys.exit(2)

        self.options = parser.parse_args()

        if self.options.timeout is not None:
            if ',' in self.options.timeout:
                self.options.timeout = tuple(float(x) for x in self.options.timeout.split(','))
            else:
                self.options.timeout = float(self.options.timeout)


sys.exit(Main().exit_code)
