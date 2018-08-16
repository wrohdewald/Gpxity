#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.Lifetrack`."""

from .track import Track

__all__ = ['Lifetrack']


class LifetrackTarget:

    """A single target of a lifetracking instance."""

    def __init__(self, backend):
        self.backend = backend
        self.track = Track()
        self.id_in_backend = None
        self.__started = False

    def update(self, points):
        """Update lifetrack into a specific track."""

        # pylint: disable=protected-access

        if not points:
            if not self.__started:
                raise Exception('Lifetrack needs initial points')
            else:
                raise Exception('Lifetrack.update needs points')
        old_title = self.track.title
        try:
            with self.track._decouple():
                if self.__started:
                    self.track.title = 'Lifetracking continues ' + self.track.title
                else:
                    self.track.title = 'Lifetracking starts ' + self.track.title
            if 'lifetrack' in self.backend.supported:
                print('   Lifetrack_target.update, lifetrack is supported')
                if not self.__started:
                    print('lifetrack._update ruft backend._lifetrack_start mit title', self.track.title)
                    new_ident = self.backend._lifetrack_start(self.track, self._prepare_points(points))
                    with self.track._decouple():
                        self.track.id_in_backend = new_ident
                else:
                    print('lifetrack._update ruft backend._lifetrack_update')
                    self.backend._lifetrack_update(self.track, self._prepare_points(points))
            else:
                print('   Lifetrack._update ruft track.add_points')
                self.track.add_points(points)
                if not self.__started:
                    print('   adding track to backend')
                    self.backend.add(self.track)
                    print('   added  track to backend')
        finally:
            with self.track._decouple():
                self.track.title = old_title
        self.__started = True

    def end(self):
        """End lifetracking for a specific backend."""
        if not self.__started:
            raise Exception('Lifetrack not yet started')
        if 'lifetrack' in self.backend.supported:
            self.track.title = 'Lifetracking ends, {:>8.3f}km done'.format(
                self.track.distance()) + ' ' + self.track.title
            self.backend._lifetrack_end(self.track)  # pylint: disable=protected-access

    def _prepare_points(self, points):
        """Round points."""
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
        if isinstance(target_backends, list):
            _ = target_backends
        else:
            _ = [target_backends]

        if not any(x.__class__.__name__ == 'ServerDirectory' for x in _):
            raise Exception('Lifetrack: At least one target must be a ServerDirectory')
        self.targets = [LifetrackTarget(x) for x in _]

    def update(self, points):
        """Start or update lifetrack.

        If the backend does not support lifetrack, this just saves the track in the backend.

        Args:
            points(list): New points

        Returns:
            The id in the first ServerDirectory

        """
        result = None
        for _ in self.targets:
            _.update(points)
            if result is None and _.backend.__class__.__name__ == 'ServerDirectory':
                result = _.id_in_backend
        return result

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
