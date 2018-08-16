#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines some helpers."""

import os
import datetime

__all__ = ['Duration', 'repr_timespan', 'uniq', 'remove_directory', 'is_track', 'collect_tracks']


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
        print('{} in {} ({}-{})'.format(
            datetime.datetime.now()-self.start_time,
            self.name, self.start_time, datetime.datetime.now()))


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
        print('rmdir: errno: {} cannot remove directory: {}'.format(exc.errno, path))
        if os.path.exists(path):
            for _ in os.listdir(path):
                print('  ', _)


def is_track(value):
    """Return True or False without looking at the type, so we do not need to import Track."""
    return hasattr(value, 'id_in_backend')


def collect_tracks(sources, verbose=False):
    """A copied list with tracks combined from all sources, to be used in 'for'-loops.

    Returns:
        A list of tracks

    """
    if is_track(sources):
        return [sources]
    result = list()
    for source in sources:
        if verbose:
            print('collecting tracks from', source.identifier() or '.')
        if is_track(source):
            result.append(source)
        else:
            result.extend(source)
    return result
