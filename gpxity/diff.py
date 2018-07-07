#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Backend`
"""

from collections import defaultdict

from .backend import Backend
from .activity import Activity

__all__ = ['BackendDiff']


class BackendDiff:
    """Compares two backends.directory

    Args:
        left (Backend): A backend, an activity or a list of either
        right (Backend): Same as for the left side

    Attributes:
        left(:class:`BackendDiffSide`): Attributes for the left side
        right(:class:`BackendDiffSide`): Attributes for the right side
        identical(list(Activity)): Activities appearing on both sides.
        similar(list(Pair)): Pairs of Activities are on both sides with
            differences. This includes all activities having at least
            100 identical positions without being identical.
        diff_flags: T=time, D=description, W=what, S=status,
            K=keywords, P=positions, Z=time offset
    """

    # pylint: disable=too-few-public-methods

    diff_flags = 'TDWSKPZ'
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
                result['T'].append('"{}" <> "{}"'.format(self.left.title or '', self.right.title or ''))

            if self.left.description != self.right.description:
                result['D'].append('"{}" <> "{}"'.format(self.left.description or '', self.right.description or ''))

            if self.left.what != self.right.what:
                result['W'].append('"{}" <> "{}"'.format(self.left.what or '', self.right.what or ''))

            if self.left.keywords != self.right.keywords:
                result['K'].append('"{}" <> "{}"'.format(
                    ', '.join(self.left.keywords), ', '.join(self.right.keywords)))

            if self.left.public != self.right.public:
                public_names = {False: 'private', True: 'public'}
                result['S'].append(
                    '"{}" <> "{}"'.format(
                        public_names[self.left.public], public_names[self.right.public]))

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
        """Represents a side (left or right) in BackendDiff.

        Attributes:
            activities: An activitiy, a list of activities, a backend or a list of backends
            exclusive(list): Acivities existing only on this side
        """

        # pylint: disable=too-few-public-methods

        def __init__(self, activities):
            self.activities = list(self.flatten(activities))
            self.build_positions()
            self.exclusive = []

        @staticmethod
        def flatten(whatever):
            """Flattens Backends or Activities into a list of activities"""
            if isinstance(whatever, list):
                for list_item in whatever:
                    if isinstance(list_item, Activity):
                        yield list_item
                    elif isinstance(list_item, Backend):
                        for _ in list_item:
                            yield _
            else:
                if isinstance(whatever, Activity):
                    yield whatever
                elif isinstance(whatever, Backend):
                    for _ in whatever:
                        yield _

        def build_positions(self):
            """Returns a set of long/lat tuples"""
            for _ in self.activities:
                _.positions = set([(x.longitude, x.latitude) for x in _.points()])

        def _find_exclusives(self, matched):
            """use data from the other side"""
            for _ in self.activities:
                if _ not in matched:
                    self.exclusive.append(_)

    def __init__(self, left, right):

        self.similar = []
        self.identical = []
        matched = []
        self.left = BackendDiff.BackendDiffSide(left)
        self.right = BackendDiff.BackendDiffSide(right)
        # pylint: disable=too-many-nested-blocks
        for left_activity in self.left.activities:
            for right_activity in self.right.activities:
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
