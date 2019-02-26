#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines some helpers."""

import os
import datetime
import time
import logging
import curses
from math import isclose

from gpxpy.geo import length as gpx_length

__all__ = ['Duration', 'repr_timespan', 'uniq', 'remove_directory', 'is_gpxfile', 'collect_gpxfiles',
           'positions_equal', 'pairs', 'add_speed', 'utc_datetime', 'local_datetime', 'ColorStreamHandler']



class ColorStreamHandler(logging.Handler):
    """Color logging."""

    def __init__(self, use_colors=True):
        logging.Handler.__init__(self)
        self.use_colors = use_colors

        # Get the foreground color attribute for this environment
        self.fcap = curses.tigetstr('setaf')

        # Get the normal attribute
        self.normal_color = curses.tigetstr('sgr0').decode("utf-8")

        # Get + Save the color sequences
        colors = (
            (logging.INFO, curses.COLOR_GREEN),
            (logging.DEBUG, curses.COLOR_BLUE),
            (logging.WARNING, curses.COLOR_YELLOW),
            (logging.ERROR, curses.COLOR_RED),
            (logging.CRITICAL, curses.COLOR_BLACK))
        self.colors = {x[0]: curses.tparm(self.fcap, x[1]).decode('utf-8') for x in colors}

    def color(self, msg, level):
        """Color the message according to logging level."""
        try:
            return self.colors[level] + msg + self.normal_color
        except BaseException:
            return msg

    def emit(self, record):
        """Output the message."""
        msg = self.format(record)
        if self.use_colors:
            msg = self.color(msg, record.levelno)
        print(msg + '\r')


class Duration:

    """A context manager showing time information for debugging."""

    # pylint: disable=too-few-public-methods

    def __init__(self, name):
        """See class docstring."""
        self.name = name
        self.start_time = datetime.datetime.now()

    def __enter__(self):
        """See class docstring.

        Returns:
            self

        """
        return self

    def __exit__(self, exc_type, exc_value, trback):
        """See class docstring."""
        logging.debug(
            '%s in %s %s-%s',
            datetime.datetime.now() - self.start_time,
            self.name, self.start_time, datetime.datetime.now())


def repr_timespan(start, end) ->str:
    """return a string representing the timespan.

    Returns:
        a string like #h#m

    """
    duration = end - start
    hours = duration.seconds // 3600
    minutes = (duration.seconds - hours * 3600) // 60
    hours += duration.days * 24
    return '{}:{:02}'.format(hours, minutes)


def uniq(lst):
    """return lst with unique elements."""
    seen = []
    for _ in lst:
        if _ not in seen:
            seen.append(_)
            yield _


def remove_directory(path):
    """If this fails, show directory content."""
    try:
        os.rmdir(path)
    except FileNotFoundError:
        logging.error("REMOVE_DIRECTORY %s: not found", path)
        raise
    except OSError as exc:
        logging.error('rmdir: errno: %s cannot remove directory: %s', exc, path)
        if os.path.exists(path):
            for _ in os.listdir(path):
                logging.error('  dir still has %s', _)


def is_gpxfile(value):
    """Return True or False without looking at the type, so we do not need to import GpxFile."""
    return hasattr(value, 'id_in_backend')


def collect_gpxfiles(sources):
    """A copied list with gpxfiles combined from all sources, to be used in 'for'-loops.

    Returns:
        A list of gpxfiles

    """
    if is_gpxfile(sources):
        return [sources]
    result = list()
    for source in sources:
        if is_gpxfile(source):
            result.append(source)
        else:
            logging.debug('')
            logging.debug('collecting gpxfiles from %s %s', source.account.backend, source)
            result.extend(source)
    return result


def positions_equal(pos1, pos2, digits=4):
    """Check if both points have the same position.

    Args:
        digits: Number of after comma digits to compare

    Returns:
        True if so

    """
    _ = 1 / 10 ** digits
    return isclose(pos1.longitude, pos2.longitude, rel_tol=_) and isclose(pos1.latitude, pos2.latitude, rel_tol=_)


def add_speed(points, window: int = 2):
    """Add speed to points in m/sec.

    It uses the last X points for computation: distance and time
    between [current_point - window] an [current_point]

    Args:
        window: The number of last points to consider.

    """
    if not points:
        return
    points[0].gpxity_speed = 0.0
    start_idx = 0
    for _, point in enumerate(reversed(points)):  # noqa
        if hasattr(point, 'gpxity_speed'):
            start_idx = _
            break
    start_idx = len(points) - start_idx
    if start_idx == len(points):
        return

    target_points = points[start_idx:]
    for idx, target_point in enumerate(target_points):
        window_start = max(idx + start_idx - window, 0)
        start_point = points[window_start]
        window_distance = gpx_length(points[window_start:start_idx + idx])
        delta = (target_point.time - start_point.time)
        window_time = delta.days * 86400.0 + delta.seconds + delta.microseconds / 1000000.0
        if window_time:
            window_speed = window_distance / window_time
        else:
            window_speed = 0.0
        target_point.gpxity_speed = window_speed


def pairs(seq):
    """Return a list of all adjacent elements."""
    # pylint: disable=stop-iteration-return
    iterable = iter(seq)
    prev = next(iterable)
    for _ in iterable:
        yield prev, _
        prev = _


def utc_to_local_delta():
    """The difference local - utc.

    This is encapsulated because
    Returns: (timedelta) the difference.

    """
    return datetime.timedelta(seconds=time.localtime().tm_gmtoff)

def local_datetime(utc):
    """Convert UTC datetime to local datetime.

    Returns: datetime

    """
    return utc + utc_to_local_delta()

def utc_datetime(local):
    """Convert local datetime to UTC datetime.

    Returns: datetime

    """
    return local - utc_to_local_delta()
