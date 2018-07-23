#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Backend`
"""

from collections import defaultdict
from difflib import SequenceMatcher

from .backend import Backend
from .track import Track

__all__ = ['BackendDiff']


class BackendDiff:
    """Compares two backends.directory

    Args:
        left (Backend): A backend, a track or a list of either
        right (Backend): Same as for the left side

    Attributes:
        left(:class:`BackendDiffSide`): Attributes for the left side
        right(:class:`BackendDiffSide`): Attributes for the right side
        identical(list(Track)): Tracks appearing on both sides.
        similar(list(Pair)): Pairs of Tracks are on both sides with
            differences. This includes all tracks having at least
            100 identical positions without being identical.
        diff_flags: T=time, D=description, C=category, S=status,
            K=keywords, P=positions, Z=time offset
    """

    # pylint: disable=too-few-public-methods

    diff_flags = 'TDCSKPZ'
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
            """Compare both tracks
            Returns:
                defaultdict(list): Keys are Flags for differences, see BackendDiff.diff_flags.
                    Values is a list(str) with additional info
            """
            # pylint: disable=too-many-locals

            result = defaultdict(list)

            if self.left.title != self.right.title:
                result['T'].append('"{}" <> "{}"'.format(self.left.title or '', self.right.title or ''))

            if self.left.description != self.right.description:
                result['D'].append('"{}" <> "{}"'.format(self.left.description or '', self.right.description or ''))

            if self.left.category != self.right.category:
                result['C'].append('"{}" <> "{}"'.format(self.left.category or '', self.right.category or ''))

            if self.left.keywords != self.right.keywords:
                result['K'].append('"{}" <> "{}"'.format(
                    ', '.join(self.left.keywords), ', '.join(self.right.keywords)))

            if self.left.public != self.right.public:
                public_names = {False: 'private', True: 'public'}
                result['S'].append(
                    '"{}" <> "{}"'.format(
                        public_names[self.left.public], public_names[self.right.public]))

            def lists(track):
                """Returns two lists of tuples: once with time, once without time."""
                times = list()
                positions = list()
                for _ in track.points():
                    times.append(_.time)
                    positions.append(tuple([_.latitude, _.longitude, _.elevation]))
                return times, positions

            def pretty_times(time1, time2):
                """If time2 has the same date, print only the time."""
                if time1.date() == time2.date():
                    time2 = time2.time()
                return time1, time2

            left_times, left_positions = lists(self.left)
            right_times, right_positions = lists(self.right)
            for tag, left_start, left_end, right_start, right_end in SequenceMatcher(
                    None, left_positions, right_positions).get_opcodes():
                if tag == 'delete':
                    result['P'].append(
                        'points between {} and {} are missing on the right'.format(
                            *pretty_times(left_times[left_start], left_times[left_end - 1])))
                elif tag == 'insert':
                    result['P'].append(
                        'points between {} and {} are missing on the left'.format(
                            *pretty_times(right_times[right_start], right_times[right_end - 1])))
                elif tag == 'replace':
                    result['P'].append(
                        'points between {} and {} are different'.format(
                            *pretty_times(
                                min([left_times[left_start], right_times[right_start]]),
                                max([left_times[left_end - 1], right_times[right_end - 1]]))))

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
            tracks: An Track, a list of tracks, a backend or a list of backends
            exclusive(list): Acivities existing only on this side
        """

        # pylint: disable=too-few-public-methods

        def __init__(self, tracks):
            self.tracks = list(self.flatten(tracks))
            self.build_positions()
            self.exclusive = []

        @staticmethod
        def flatten(whatever):
            """Flattens Backends or Tracks into a list of tracks"""
            if isinstance(whatever, list):
                for list_item in whatever:
                    if isinstance(list_item, Track):
                        yield list_item
                    elif isinstance(list_item, Backend):
                        for _ in list_item:
                            yield _
            else:
                if isinstance(whatever, Track):
                    yield whatever
                elif isinstance(whatever, Backend):
                    for _ in whatever:
                        yield _

        def build_positions(self):
            """Returns a set of long/lat tuples"""
            for _ in self.tracks:
                _.positions = set([(x.longitude, x.latitude) for x in _.points()])

        def _find_exclusives(self, matched):
            """use data from the other side"""
            for _ in self.tracks:
                if _ not in matched:
                    self.exclusive.append(_)

    def __init__(self, left, right):

        self.similar = []
        self.identical = []
        matched = []
        self.left = BackendDiff.BackendDiffSide(left)
        self.right = BackendDiff.BackendDiffSide(right)
        # pylint: disable=too-many-nested-blocks
        for left_track in self.left.tracks:
            for right_track in self.right.tracks:
                if left_track == right_track:
                    self.identical.append(left_track)
                    matched.append(left_track)
                    matched.append(right_track)
                else:
                    if len(left_track.positions & right_track.positions) >= 100:
                        self.similar.append(BackendDiff.Pair(left_track, right_track))
                        matched.append(left_track)
                        matched.append(right_track)
        # pylint: disable=protected-access
        self.left._find_exclusives(matched)
        self.right._find_exclusives(matched)
