#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines some helpers."""

import os
import datetime
import logging
from math import isclose

__all__ = ['Duration', 'repr_timespan', 'uniq', 'remove_directory', 'is_track', 'collect_tracks',
           'positions_equal']


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
    except OSError as exc:
        logging.error('rmdir: errno: %s cannot remove directory: %s', exc.errno, path)
        if os.path.exists(path):
            for _ in os.listdir(path):
                logging.error('  dir still has %s', _)


def is_track(value):
    """Return True or False without looking at the type, so we do not need to import Track."""
    return hasattr(value, 'id_in_backend')


def collect_tracks(sources):
    """A copied list with tracks combined from all sources, to be used in 'for'-loops.

    Returns:
        A list of tracks

    """
    if is_track(sources):
        return [sources]
    result = list()
    for source in sources:
        if is_track(source):
            result.append(source)
        else:
            logging.debug('')
            logging.debug('collecting tracks from %s', source)
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
