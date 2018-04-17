#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines some helpers.
"""

import datetime

__all__ = ['Duration', 'repr_timespan', 'VERSION']

VERSION = '1.2.1'

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
    return '{}h{}m'.format(hours, minutes)
