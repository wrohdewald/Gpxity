#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.backends.MMTServer`
"""


from .directory import Directory

__all__ = ['MMTServer']
__all__ = []


class MMTServer(Directory):
    """The implementation for a server emulating MapMyTracks.
    The activity ident is the number given by us.
    """

    # pylint: disable=abstract-method

    skip_test = True

    def __init__(self, url=None, auth=None, cleanup=False):
        super(MMTServer, self).__init__(url, auth=auth, cleanup=cleanup)

    def _set_new_id(self, activity):
        """gives the activity a unique id"""
        try:
            activity.id_in_backend = str(max(int(x) for x in self._list_gpx()) + 1)
        except ValueError:
            activity.id_in_backend = '1'

MMTServer._define_support() # pylint: disable=protected-access
