#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module cleans my MMT activities:

1. creates a Directory backend if it does not exist
2. downloads all MMT activities and saves them in Directory using
    the MMT activity_id for the file name. Only for activities we
    do not have yet.
3. removes activities with less than 10 points
4. lists overlapping activities
5. say which activities are in Dokumente but not in MMT and vice versa. Use activity.time for compares.

To be done:
6. apply geofencing
"""

import sys
import webbrowser
import datetime


# This uses not the installed copy but the development files
sys.path.insert(0,  '..')

from gpxity import Activity, Directory, MMT, BackendDiff

def copy_from_mmt(mmt, local):
    for a in mmt:
        if a.id_in_backend not in local:
            local.save(a, ident=a.id_in_backend)

def remove_shorties(local, remote=None, min_points=10):
    for local_activity in local:
        has_points = local_activity.gpx.get_points_no()
        if  has_points < min_points:
            print('*** {} had only {} points'.format(local_activity, has_points))
            ident = local_activity.id_in_backend
            webbrowser.open('http://www.mapmytracks.com/explore/activity/{}'.format(ident))
            local.remove(ident)
            if remote and ident in remote:
                remote.remove(ident)


def remove_overlaps(backend):
    """when times between activities overlap, remove all but the longest activity"""
    for group in Activity.overlapping_times(backend):
        print('Keeping: {}: {}-{}'.format(group[0].id_in_backend, group[0].time, group[0].last_time))
        for acti in group[1:]:
            print('remove: {}: {}-{}'.format(acti.id_in_backend, acti.time, acti.last_time))
            acti.remove()
        print()

def dump_diffs(backend1, backend2):
    differ = BackendDiff(backend1, backend2)
#    differ = BackendDiff(backend1, backend2, key=lambda x:x.gpx.get_track_points_no())
    if differ.left.exclusive:
        print('only in {}:'.format(backend1.url))
        for key, values in differ.left.exclusive.items():
            for _ in values:
                print('{}: {}'.format(key, _))
        print()
    if differ.right.exclusive:
        print('only in {}:'.format(backend2.url))
        for key, values in differ.right.exclusive.items():
            for _ in values:
                print('{}: {}'.format(key, _))
        print()

    for key,  values in differ.matches.items():
        left = values[0]
        for right in values[1:]:
            first_diff_time = last_diff_time = None
            for _, (point1, point2) in enumerate(zip(left.points(), right.points())):
                # GPXTrackPoint has no __eq__ and no working hash()
                # those are only the most important attributes:
                if (point1.longitude != point2.longitude
                    or point1.latitude != point2.latitude
                    or point1.elevation != point2.elevation):
                    if first_diff_time is None:
                        first_diff_time = point1.time
                    last_diff_time = point1.time
            if first_diff_time:
                print('{}: different points between {} and {} in:'.format(
                    key, first_diff_time, last_diff_time))
                print('      {}'.format(left))
                print('      {}'.format(right))
    print()

    hours2 = datetime.timedelta(hours=2)
    differ2 = BackendDiff(backend1, backend2, right_key=lambda x: x.time + hours2)

    if differ2.matches:
        for key,  values in differ2.matches.items():
            left = values[0]
            for right in values[1:]:
                print('{}: happens exactly 2 hours later in {}'.format(key, right))
        print

    hours2 = datetime.timedelta(hours=2)
    differ2 = BackendDiff(backend1, backend2, right_key=lambda x: x.time - hours2)

    if differ2.matches:
        for key, values in differ2.matches.items():
            left = values[0]
            for right in values[1:]:
                print('{}: happens exactly 2 hours earlier in {}'.format(key, right))
        print


mmt = MMT(auth=sys.argv[1])
mmt_local = Directory('/home/wr/Dokumente/Privat/mmt')
gpx = Directory('/home/wr/Dokumente/Privat/gpx')

#remove_shorties(mmt_local,  mmt)
#remove_shorties(gpx)

mmt_local.merge(mmt, remove=True, use_remote_ident=True)

dump_diffs(gpx, mmt_local)
