#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.ServerDirectory`
"""


from .directory import Directory

__all__ = ['ServerDirectory']

class ServerDirectory(Directory):
    """Like :class:`Directory` but the activity ids are different: Just a number.
    A new id is generated by adding 1 to the highest existing id.

    The symbolic links per YYYY/MM use the title of the activity as link name.

    """

    # pylint: disable=abstract-method

    skip_test = True

    def _new_id(self, _):
        """Buids a unique id for activity"""
        try:
            return str(max(int(x) for x in self._list_gpx()) + 1)
        except ValueError:
            return '1'

ServerDirectory._define_support() # pylint: disable=protected-access
