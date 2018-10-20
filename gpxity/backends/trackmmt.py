#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements only a minimum of what MMT can do.

Upload entire tracks and extend a track. That is
what oruxmaps does - see examples/mmt_server.

TrackMMT is used to test mmt_server.

"""

from .mmt import MMT

__all__ = ['TrackMMT']


class TrackMMT(MMT):

    """This is a minimal implementation, it only supports listing and retrieving tracks and life tracking.

    This is used for testing gpxity_server which in turn is used to
    receive life tracking data from smartphone apps like
    oruxmaps.

    """

    # pylint: disable=abstract-method

    def _load_track_headers(self):
        """not implemented."""
        raise NotImplementedError()

    def _write_attribute(self, track, attribute):
        """not implemented."""
        raise NotImplementedError()

    def _write_title(self, track):
        """not implemented."""
        raise NotImplementedError()

    def _write_description(self, track):
        """not implemented."""
        raise NotImplementedError()

    def _write_public(self, track):
        """not implemented."""
        raise NotImplementedError()

    def _write_category(self, track):
        """not implemented."""
        raise NotImplementedError()

    def _write_add_keywords(self, track, values):
        """not implemented."""
        raise NotImplementedError()

    def _write_remove_keywords(self, track, values):
        """not implemented."""
        raise NotImplementedError()

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation."""
        raise NotImplementedError()

    @property
    def is_free_account(self):
        """Our own local server can do lifeftracking.

        Returns:
            False

        """
        return False

    def destroy(self):
        """Would need implementations for scan and remove."""
