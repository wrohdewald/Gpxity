#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.diff.BackendDiff`."""

# pylint: disable=protected-access

from collections import defaultdict
from difflib import SequenceMatcher

from .backend import Backend
from .track import Track

__all__ = ['BackendDiff']


class BackendDiff:

    """Compares two backends.directory.

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
            """See class docstring."""
            self.left = left
            self.right = right
            self.differences = self.__compare()

        def __compare_metadata(self):
            """Compare some metadata between left and right.

            Returns:
                a dict with the differences

            """
            result = defaultdict(list)

            def compare_attribute(code, attribute, func=None):
                """Compare a specific attribute."""
                left_value = getattr(self.left, attribute) or ''
                right_value = getattr(self.right, attribute) or ''
                if func:
                    left_value = func(left_value)
                    right_value = func(right_value)
                if left_value != right_value:
                    result[code].append('"{}" <> "{}"'.format(left_value, right_value))

            compare_attribute('T', 'title')
            compare_attribute('D', 'description')
            compare_attribute('C', 'category')
            compare_attribute('K', 'keywords', lambda x: ', '.join(x))  # pylint: disable=unnecessary-lambda
            compare_attribute('S', 'public', lambda x: 'public' if x else 'private')
            return result

        def __compare(self):  # noqa
            """Compare both tracks.

            Returns:
                defaultdict(list): Keys are Flags for differences, see BackendDiff.diff_flags.
                    Values is a list(str) with additional info

            """
            # pylint: disable=too-many-locals, too-many-branches, too-many-nested-blocks

            result = self.__compare_metadata()

            def lists(track):
                """Returns two lists of tuples: once with time, once without time."""
                times = list()
                positions = list()
                for _ in track.points():
                    times.append(_.time)
                    positions.append(tuple([_.latitude or 0, _.longitude or 0, _.elevation or 0]))  # noqa
                return times, positions

            def pretty_times(time1, time2):
                """If time2 has the same date, use only the time."""
                if time1.date() == time2.date():
                    time2 = time2.time()
                return time1, time2

            left_times, left_positions = lists(self.left)
            right_times, right_positions = lists(self.right)
            for tag, left_start, left_end, right_start, right_end in SequenceMatcher(
                    None, left_positions, right_positions).get_opcodes():
                left_found = left_positions[left_start:left_end]
                right_found = right_positions[right_start:right_end]
                for idx, _ in enumerate(left_found):
                    left_found[idx] = list(_)
                    left_found[idx].append(left_times[left_start + idx])
                for idx, _ in enumerate(right_found):
                    right_found[idx] = list(_)
                    right_found[idx].append(right_times[right_start + idx])
                if tag == 'delete':
                    result['P'].append(
                        'points between {} and {} are missing on the right'.format(
                            *pretty_times(left_times[left_start], left_times[left_end - 1])))
                elif tag == 'insert':
                    result['P'].append(
                        'points between {} and {} are missing on the left'.format(
                            *pretty_times(right_times[right_start], right_times[right_end - 1])))
                elif tag == 'replace':
                    if [x[:2] for x in left_found] == [x[:2] for x in right_found]:
                        if len(
                                {(right_found[x][3] - left_found[x][3])
                                 for x in range(len(left_found))}) == 1:
                            time1, time2 = pretty_times(left_found[0][3], left_found[-1][3])
                            timedelta = right_found[0][3] - left_found[0][3]
                            if timedelta:
                                result['Z'].append(
                                    '{} points between {} and {} on the left are {} later on the right'.format(
                                        len(left_found), time1, time2, timedelta))
                            else:
                                # if points are different but times are the same, it must be the height. Ignore that.
                                pass
                        else:
                            result['Z'].append('Points have different times')
                    else:
                        result['P'].append(
                            'points between {} and {} are different'.format(
                                *pretty_times(
                                    min([left_times[left_start], right_times[right_start]]),
                                    max([left_times[left_end - 1], right_times[right_end - 1]]))))
                        for left, right in zip(left_found, right_found):
                            for data, sign in ((left, '<'), (right, '>')):
                                result['P'].append(
                                    '  {sign} {data[0]:8.6f} {data[1]:8.6f} {data[2]:5.2f} {data[3]}'.format(
                                        sign=sign, data=data))

            # some files have a problem with the time zone
            _ = self.left.time_offset(self.right)
            if _:
                result['Z'].append('Time offset: {}'.format(_))

            return result

    class BackendDiffSide:
        """Represents a side (left or right) in BackendDiff.

        Attributes:
            tracks: An Track, a list of tracks, a backend or a list of backends
            exclusive(list): Acivities existing only on this side
        """

        # pylint: disable=too-few-public-methods

        def __init__(self, tracks):
            """See class docstring."""
            self.tracks = list(self.flatten(tracks))
            self.build_positions()
            self.exclusive = []

        @staticmethod
        def flatten(whatever):
            """Flatten Backends or Tracks into a list of tracks."""
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
            """Return a set of long/lat tuples."""
            for _ in self.tracks:
                _.positions = {(x.longitude, x.latitude) for x in _.points()}

        def _find_exclusives(self, matched):
            """use data from the other side."""
            for _ in self.tracks:
                if _ not in matched:
                    self.exclusive.append(_)

    def __init__(self, left, right):
        """See class docstring."""
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
                    maxlen = max(len(left_track.positions), len(right_track.positions))
                    if len(left_track.positions & right_track.positions) >= maxlen * 0.9:
                        self.similar.append(BackendDiff.Pair(left_track, right_track))
                        matched.append(left_track)
                        matched.append(right_track)
        self.left._find_exclusives(matched)
        self.right._find_exclusives(matched)
