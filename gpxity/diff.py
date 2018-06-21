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

    Attributes:
        left(:class:`BackendDiffSide`): Attributes for the left side
        right(:class:`BackendDiffSide`): Attributes for the right side
        identical(list(Activity)): Activities appearing on both sides.
        similar(list(Pair)): Pairs of Activities are on both sides with
            differences. This includes all activities having at least
            100 identical positions without being identical.
        diff_flags: T=time, P=positions
    """

    # pylint: disable=too-few-public-methods

    diff_flags = 'TPZ'

    class Pair:
        """Holds two comparable Items and the diff result
        Attributes:
            differences(dict()): Keys are Flags for differences, see BackendDiff.diff_flags.
                    Values is a list(str) with additional info
        """
        def __init__(self, left, right):
            self.left = left
            self.right = right
            self.differences = self.__compare()

        def __compare(self):
            """Compare both activities
            Returns:
                defaultdict(list): Keys are Flags for differences, see BackendDiff.diff_flags.
                    Values is a list(str) with additional info
            """

            time_range = [None, None]
            def print_diff_time(time_range):
                """If time_range is relevant, print and reset it."""
                if time_range[0] and time_range[1] != time_range[0]:
                    result['P'].append('different points between {} and {}'.format(
                        time_range[0], time_range[1] or 'end'))
                time_range[0] = None
                time_range[1] = None

            result = defaultdict(list)
            if self.left.title != self.right.title:
                result['T'].append('"{}" against "{}"'.format(self.left.title or '', self.right.title or ''))
            for _, (point1, point2) in enumerate(zip(self.left.points(), self.right.points())):
                # GPXTrackPoint has no __eq__ and no working hash()
                # those are only the most important attributes:
                if (point1.longitude != point2.longitude
                        or point1.latitude != point2.latitude
                        or point1.elevation != point2.elevation):
                    if time_range[0] is None:
                        time_range[0] = point1.time
                    time_range[1] = point1.time
                else:
                    print_diff_time(time_range)
            print_diff_time(time_range)

            # gpx files produced by old versions of Oruxmaps have a problem with the time zone
            def offset(point1, point2):
                """Returns the time delta if both points have a time."""
                if point1.time and point2.time:
                    return point2.time - point1.time
                return None

            start_time_delta = offset(next(self.left.points()), next(self.right.points()))
            if start_time_delta:
                end_time_delta = offset(self.left.last_point(), self.right.last_point())
                if start_time_delta == end_time_delta:
                    result['Z'].append('Time offset: {}'.format(start_time_delta))

            return result


    class BackendDiffSide:
        """Represents a backend in BackendDiff.

        Attributes:
            backends: The backends
            exclusive(list): Acivities existing only on this side
        """

        # pylint: disable=too-few-public-methods

        def __init__(self, backends):
            if isinstance(backends, Backend):
                self.backends = [backends]
            else:
                self.backends = backends
            self.exclusive = []

        def _find_exclusives(self, matched):
            """use data from the other side"""
            for this in self.backends:
                for _ in this:
                    if _ not in matched:
                        self.exclusive.append(_)

    def __init__(self, left, right):

        def positions(activity):
            """Returns a set of long/lat tuples"""
            return set([(x.longitude, x.latitude) for x in activity.points()])

        self.similar = []
        self.identical = []
        matched = []
        self.left = BackendDiff.BackendDiffSide(left)
        self.right = BackendDiff.BackendDiffSide(right)
        # pylint: disable=too-many-nested-blocks
        for left_backend in self.left.backends:
            for left_activity in left_backend:
                left_activity.positions = positions(left_activity)
                for right_backend in self.right.backends:
                    for right_activity in right_backend:
                        if not hasattr(right_activity, 'positions'):
                            right_activity.positions = positions(right_activity)
                        if left_activity == right_activity:
                            self.identical.append(left_activity)
                            matched.append(left_activity)
                            matched.append(right_activity)
                        else:
                            if len(left_activity.positions & right_activity.positions) >= 100:
                                self.similar.append(BackendDiff.Pair(left_activity, right_activity))
                                matched.append(left_activity)
                                matched.append(right_activity)
        # pylint: disable=protected-access
        self.left._find_exclusives(matched)
        self.right._find_exclusives(matched)
