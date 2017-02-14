#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxmove.backends.MMTServerStorage`
"""


import datetime

from .fs import LocalStorage

__all__ = ['MMTServerStorage']
__all__ = []


class MMTServerStorage(LocalStorage):
    """The implementation for a server emulating MapMyTracks.
    The activity ident is the number given by us.
    """

    skip_test = True

    def __init__(self, url=None, auth=None, cleanup=False):
        super(MMTServerStorage, self).__init__(url, auth=auth, cleanup=cleanup)

    def get_time(self):
        """get MMT server time as a Linux timestamp"""
        return int(datetime.datetime.now().timestamp())

    def new_id(self, activity):
        """gives the activity a unique id"""
        try:
            return str(max(int(x) for x in self.list_gpx()) + 1)
        except ValueError:
            return 1

    def save(self, activity):
        """save full gpx, generate an id if needed"""
        if self not in activity.storage_ids:
            activity.add_to_storage(self, self.new_id(activity))
        super(MMTServerStorage, self).save(activity)

