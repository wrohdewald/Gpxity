#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.Lifetrack`."""

from .track import Track

__all__ = ['Lifetrack']


class LifetrackTarget:

    """A single target of a lifetracking instance."""

    def __init__(self, backend):
        """See class docstring."""
        self.backend = backend
        self.track = Track()
        self.__started = False

    def update(self, points) ->str:
        """Update lifetrack into a specific track.

        Returns:
            the new id_in_backend

        """

        # pylint: disable=protected-access

        if not points:
            if not self.__started:
                raise Exception('Lifetrack needs initial points')
            else:
                raise Exception('Lifetrack.update needs points')
        if 'Lifetracking' in self.track.title:
            with self.track._decouple():
                self.track.title = ':'.join(self.track.title.split(':')[1:])
        old_title = self.track.title
        new_ident = None
        try:
            if 'Lifetracking' not in self.track.title:
                with self.track._decouple():
                    self.track.title = (
                        'Lifetracking continues:'
                        if self.__started else 'Lifetracking starts:') + ' ' + self.track.title
            if 'lifetrack' in self.backend.supported:
                if not self.__started:
                    new_ident = self.backend._lifetrack_start(self.track, self._prepare_points(points))
                    with self.backend._decouple():
                        self.track._set_backend(self.backend)
                        self.track.id_in_backend = new_ident
                else:
                    self.backend._lifetrack_update(self.track, self._prepare_points(points))
            else:
                self.track.add_points(points)
                if not self.__started:
                    self.track = self.backend.add(self.track)
                    new_ident = self.track.id_in_backend
                    assert new_ident
                assert self.track.id_in_backend
            return new_ident
        finally:
            with self.track._decouple():
                self.track.title = old_title
            self.__started = True

    def end(self):
        """End lifetracking for a specific backend."""
        if not self.__started:
            raise Exception('Lifetrack not yet started')
        if 'lifetrack_end' in self.backend.supported:
            with self.track._decouple():  # pylint: disable=protected-access
                self.track.title = 'Lifetracking ends: ' + self.track.title
            self.backend._lifetrack_end(self.track)  # pylint: disable=protected-access

    def _prepare_points(self, points):
        """Round points.

        Returns:
            The rounded points

        """
        result = list(points)[:]
        self.track._round_points(result)  # pylint: disable=protected-access
        return result


class Lifetrack:

    """Life tracking. The data will be forwarded to all given backends.

    Args:
        target_tracks: Those tracks will receive the lifetracking data.
            This may be a list(Track) or a single track.

    """

    # pylint: disable=protected-access

    def __init__(self, target_backends):
        """See class docstring."""
        if isinstance(target_backends, list):
            _ = target_backends
        else:
            _ = [target_backends]

        self.targets = [LifetrackTarget(x) for x in _]
        self.id_in_server = None

    def update(self, points):
        """Start or update lifetrack.

        If the backend does not support lifetrack, this just saves the track in the backend.

        Args:
            points(list): New points

        """
        for _ in self.targets:
            id_in_server = _.update(points)
            assert _.track.id_in_backend, '{} in {} got no id_in_backend'.format(_.track, _.backend)
            if self.id_in_server is None:
                self.id_in_server = id_in_server

    def end(self):
        """End lifetrack.

        If the backend does not support lifetrack, this does nothing."""
        for _ in self.targets:
            _.end()

    def set_title(self, title):
        """Set title for all targets."""
        for _ in self.targets:
            with _.track._decouple():
                _.track.title = title

    def set_category(self, category):
        """Set category for all targets."""
        for _ in self.targets:
            with _.track._decouple():
                _.track.category = category

    def set_public(self, public):
        """Set public for all targets."""
        for _ in self.targets:
            with _.track._decouple():
                _.track.public = public
