#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements only a minimum of what MMT can do:
upload entire tracks and extend a track. That is
what oruxmaps does - see examples/mmt_server.

TrackMMT is used to test mmt_server.
"""

from .mmt import MMT

__all__ = ['TrackMMT']


class TrackMMT(MMT):
    """This is a minimal implementation, it only supports listing
    and retrieving tracks and life tracking. This is used for
    testing examples/mmtserver.py which in turn is used to
    receive life tracking data from smartphone apps like
    oruxmaps.
    """

    # pylint: disable=abstract-method

   #  skip_test = True

    def _write_attribute(self, track, attribute):
        raise NotImplementedError()

    def _write_title(self, track):
        raise NotImplementedError()

    def _write_description(self, track):
        raise NotImplementedError()

    def _write_public(self, track):
        raise NotImplementedError()

    def _write_category(self, track):
        raise NotImplementedError()

    def _write_add_keywords(self, track, values):
        raise NotImplementedError()

    def _write_remove_keywords(self, track, values):
        raise NotImplementedError()

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation"""
        raise NotImplementedError()


    @property
    def session(self):
        return None

TrackMMT._define_support() # pylint: disable=protected-access
