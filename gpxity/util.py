#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines some helpers.
"""

import os
import datetime

__all__ = ['Duration', 'repr_timespan', 'uniq', 'remove_directory', 'is_track', 'collect_tracks']

class Duration:
    """A context manager showing time information for debugging."""

    # pylint: disable=too-few-public-methods

    def __init__(self, name):
        self.name = name
        self.start_time = datetime.datetime.now()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, trback):
        print('{} in {} ({}-{})'.format(
            datetime.datetime.now()-self.start_time,
            self.name, self.start_time, datetime.datetime.now()))


def repr_timespan(start, end):
    """returns a string in the form #h#m"""
    duration = end - start
    hours = duration.seconds // 3600
    minutes = (duration.seconds - hours * 3600) // 60
    hours += duration.days * 24
    return '{}:{:02}'.format(hours, minutes)

def uniq(lst):
    """returns lst with unique elements"""
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
    """Returns True or False without looking at the type, so we do not need to
    import Track."""
    return hasattr(value, 'id_in_backend')

def collect_tracks(sources, verbose=False, multi_backends=True):
    """A copied list with tracks combined from all sources, to be used in 'for'-loops"""
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
    if not multi_backends:
        if len(set(x.backend.identifier() for x in result)) > 1:
            raise Exception('collect_tracks accepts only one backend')
    return result
