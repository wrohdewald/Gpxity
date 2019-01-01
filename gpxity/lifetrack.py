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

    def __init__(self, backend, use_id=None):
        """See class docstring."""
        self.backend = backend
        if use_id in backend:
            existing_track = backend[use_id]
            self.track = existing_track.clone()
            self.track.id_in_backend = use_id
        else:
            self.track = Track()
            self.track.id_in_backend = use_id
        self.started = False
        assert self.track.backend is None, 'TrackerTarget.track {} has backend {}'.format(
            self.track, self.track.backend)

    def update(self, points) ->str:
        """Update lifetrack into a specific track.

        Returns:
            the new id_in_backend if not yet started else None

        """
        if not points:
            if not self.started:
                raise Exception('Lifetrack needs initial points')
            else:
                raise Exception('Lifetrack.update needs points')
        new_ident = None
        points = self._prepare_points(points)
        self.track.add_points(points)
        if not self.started:
            # TODO: a unittest where points are empty here because of fences
            new_ident = self.backend._lifetrack_start(self.track, points)
            self.track.id_in_backend = new_ident
            self.started = True
        elif points:
            self.backend._lifetrack_update(self.track, points)
        assert self.track.id_in_backend
        assert self.track.backend is None, 'LifetrackTarget.track {} has backend {}'.format(
            self.track, self.track.backend)
        return new_ident

    def end(self):
        """End lifetracking for a specific backend."""
        if not self.started:
            raise Exception('Lifetrack not yet started')
        self.backend._lifetrack_end(self.track)

    def _prepare_points(self, points):
        """Round points and remove those within fences.

        Returns (list):
            The prepared points

        """
        result = [x for x in points if self.backend.fences.outside(x)]
        if len(result) < len(points):
            self.backend.logger.debug("Fences removed %d out of %d points", len(points) - len(result), len(points))
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
        if ids is None:
            ids = [None] * len(target_backends)
        elif isinstance(ids, str):
            ids = ids.split('----')
        self.sender_ip = sender_ip
        self.targets = [LifetrackTarget(target, use_id) for target, use_id in zip(target_backends, ids)]
        self.done = False

    def formatted_ids(self) ->str:
        """One string holding all backend ids.

        Returns: that string or None.

        """
        try:
            return '----'.join(x.track.id_in_backend for x in self.targets)
        except TypeError:
            return None

    def start(self, points, title=None, public=None, category=None):
        """Start lifetracking.

        Returns: The new id_in_backend

        """
        if title is None:
            title = str(datetime.datetime.now())[:16]
        if public is None:
            public = False
        if category is None:
            category = self.targets[0].backend.supported_categories[0]

        for _ in self.targets:
            with _.track._decouple():
                # decouple because the _life* methods will put data into the backend
                _.track.title = title
                _.track.public = public
                _.track.category = category
                _.started = _.track.id_in_backend is not None
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
