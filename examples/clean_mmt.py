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

to be done:
4. lists overlapping activities
5. say which activities are in Dokumente but not in MMT and vice versa. Use activity.time for compares.
6. apply geofencing
7. update MMT
"""

import sys
import webbrowser

# This uses not the installed copy but the development files
sys.path.insert(0,  '..')
from gpxity.backends import Directory, MMT

def copy_from_mmt(mmt, local):
    for a in mmt:
        if a.id_in_backend not in local:
            local.save(a, ident=a.id_in_backend)

def remove_shorties(local, remote=None):
    for local_activity in local:
        has_points = local_activity.gpx.get_points_no()
        if  has_points < 10:
            print('*** {} had only {} points'.format(local_activity, has_points))
            ident = local_activity.id_in_backend
            webbrowser.open('http://www.mapmytracks.com/explore/activity/{}'.format(ident))
            local.remove(ident)
            if remote and ident in remote:
                remote.remove(ident)

mmt = MMT(auth=sys.argv[1])
local = Directory(sys.argv[2])
def overlapping_times(activities):
    """Yields groups of activities with overlapping times.
    This may be very slow for many long activities."""
    previous = None
    group = set()
    for current in sorted(activities,  key=lambda x: x.time):
        if previous and current.time < previous.last_time:
            group.add(previous)
            group.add(current)
        else:
            if group:
                yield sorted(group,  key=lambda x:x.time)
            group = set()
        previous = current
    if group:
        yield sorted(group,  key=lambda x:x.time)

def remove_overlaps(backend):
    for group in overlapping_times(backend):
        print('Keeping: {}: {}-{}'.format(group[0].id_in_backend, group[0].time, group[0].last_time))
        for acti in group[1:]:
            print('remove: {}: {}-{}'.format(acti.id_in_backend, acti.time, acti.last_time))
            backend.remove(acti.id_in_backend)
        print()


copy_from_mmt(mmt, local)

remove_shorties(local, mmt)

