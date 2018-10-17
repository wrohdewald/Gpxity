#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.lifetrack.Lifetrack`."""

# pylint: disable=protected-access

import datetime

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

        if not points:
            if not self.__started:
                raise Exception('Lifetrack needs initial points')
            else:
                raise Exception('Lifetrack.update needs points')
        new_ident = None
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
        self.__started = True
        return new_ident

    def end(self):
        """End lifetracking for a specific backend."""
        if not self.__started:
            raise Exception('Lifetrack not yet started')
        if 'lifetrack_end' in self.backend.supported:
            self.backend._lifetrack_end(self.track)

    def _prepare_points(self, points):
        """Round points.

        Returns:
            The rounded points

        """
        result = list(points)[:]
        self.track._round_points(result)
        return result


class Lifetrack:

    """Life tracking. The data will be forwarded to all given backends.

    Args:
        sender_ip: The IP of the client.
        target_backends (list): Those tracks will receive the lifetracking data.
        ids (list(str)): If given, use as id_in_backend. One for every backend.
            May be list(str) or str

    Attributes:
        done: Will be True after end() has been called.
        ids (str): The ids of all backends joined by '----'.

    """

    def __init__(self, sender_ip, target_backends, ids=None):
        """See class docstring."""
        assert sender_ip is not None
        self.sender_ip = sender_ip
        self.targets = [LifetrackTarget(x) for x in target_backends]
        if isinstance(ids, list):
            ids = '----'.join(ids)
        if ids:
            for target, use_id in zip(self.targets, ids.split('----')):
                target.track.id_in_backend = use_id
        self.done = False

    def formatted_ids(self) ->str:
        """One string holding all backend ids.

        Returns: that string.

        """
        return '----'.join(x.track.id_in_backend for x in self.targets)

    def start(self, points, title=None, public=None, category=None):
        """Start lifetracking.

        Returns: The new id_in_backend

        """
        if title is None:
            title = str(datetime.datetime.now())[:16]
        if public is None:
            public = False
        if category is None:
            category = self.targets[0].backend.legal_categories[0]

        for _ in self.targets:
            with _.track._decouple():
                _.track.title = title
                _.track.public = public
                _.track.category = category
        self.update(points)
        return self.formatted_ids()

    def update(self, points):
        """Start or update lifetrack.

        If the backend does not support lifetrack, this just saves the track in the backend.

        Args:
            points(list): New points

        """
        for _ in self.targets:
            _.update(points)

    def end(self):
        """End lifetrack.

        If the backend does not support lifetrack, this does nothing."""
        for _ in self.targets:
            _.end()
        self.done = True

    def __str__(self):  # noqa
        return 'Lifetrack({}{})'.format(self.formatted_ids(), ' done' if self.done else '')

    def __repr__(self):  # noqa
        return str(self)
