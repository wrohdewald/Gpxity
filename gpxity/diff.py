#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Backend`
"""

from collections import defaultdict

from .backend import Backend

__all__ = ['BackendDiff']


class BackendDiff:
    """Compares two backends.directory

    Args:
        left (Backend): A backend
        right (Backend): The other one
        key: A lambda which does the comparison.
            Default is the start time: `key=lambda x: x.time`
        right_key: Default is key. If given, this will be used for activities from right.
            This allows things like `BackendDiff(b1, b2, right_key = lambda x: x.time + hours2)`
            where hours2 is a timedelta of two hours. If your GPX data has a problem with
            the time zone, this lets you find activities differring only by exactly 2 hours.

    Attributes:
        left(:class:`BackendDiffSide`): Attributes for the left side
        right(:class:`BackendDiffSide`): Attributes for the right side
        keys_in_both(list): keys appearing on both sides.
        matches(dict(list)): For every keys_in_both, this lists all matching activities from both sides
    """

    # pylint: disable=too-few-public-methods

    class BackendDiffSide:
        """Represents a backend in BackendDiff.

        Attributes:
            backend: The backend
            key_lambda: The used lambda for calculating the key values. They are used for comparison.
            entries(dict): keys are what key_lambda calculates. values are lists of matching activities
            exclusive(dict): keys with corresponding activity lists for activities existing only on this side
        """

        # pylint: disable=too-few-public-methods

        def __init__(self, backend, key_lambda):
            self.key_lambda = key_lambda
            self.entries = defaultdict(list)
            if isinstance(backend, Backend):
                self.backends = [backend]
            else:
                self.backends = backend
            for this in self.backends:
                for _ in this:
                    try:
                        key = key_lambda(_)
                        assert key is not None, key_lambda
                    except TypeError:
                        print('BackendDiffSide cannot apply key to {}/{}'.format(this, _))
                        raise
                    self.entries[key].append(_)
            self.exclusive = dict()

        def _use_other(self, other):
            """use data from the other side"""
            for _ in self.entries.keys():
                if _ not in other.entries:
                    self.exclusive[_] = self.entries[_]

    def __init__(self, left, right, key=None, right_key=None):
        if key is None:
            key = lambda x: x.time or x.gpx.get_track_points_no() or id(x)
        if right_key is None:
            right_key = key
        self.left = BackendDiff.BackendDiffSide(left, key)
        self.right = BackendDiff.BackendDiffSide(right, right_key)
        self.left._use_other(self.right) # pylint: disable=protected-access
        self.right._use_other(self.left) # pylint: disable=protected-access
        self.keys_in_both = self.left.entries.keys() & self.right.entries.keys()
        self.matches = defaultdict(list)
        for _ in self.keys_in_both:
            self.matches[_].extend(self.left.entries[_])
            self.matches[_].extend(self.right.entries[_])
