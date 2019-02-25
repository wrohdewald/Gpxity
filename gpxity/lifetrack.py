#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.lifetrack.Lifetrack`."""

# pylint: disable=protected-access

import datetime

from .gpxfile import GpxFile

__all__ = ['Lifetrack']


class LifetrackTarget:

    """A single target of a lifetracking instance."""

    def __init__(self, backend, use_id=None):
        """See class docstring."""
        self.backend = backend
        if use_id in backend:
            existing_track = backend[use_id]
            self.gpxfile = existing_track.clone()
            self.gpxfile.id_in_backend = use_id
        else:
            self.gpxfile = GpxFile()
            self.gpxfile.id_in_backend = use_id
        self.started = False
        assert not self.gpxfile.backend, 'TrackerTarget.gpxfile {} has backend {}'.format(
            self.gpxfile, self.gpxfile.backend)

    def update_tracker(self, points) ->str:
        """Update lifetrack into a specific gpxfile.

        Returns:
            the new id_in_backend if not yet started else None.
            If the backend fences away all points, also return None.

        """
        if not points:
            if not self.started:
                raise Exception('Lifetrack needs initial points')
            else:
                raise Exception('Lifetrack.update_tracker needs points')
        new_ident = None
        points = self._prepare_points(points)
        self.gpxfile.add_points(points)
        if not self.started:
            if points or self.backend.accepts_zero_points:
                new_ident = self.backend._lifetrack_start(self.gpxfile, points)
                assert new_ident
                self.gpxfile.id_in_backend = new_ident
                self.started = True
        elif points:
            self.backend._lifetrack_update(self.gpxfile, points)
        assert not self.gpxfile.backend, 'LifetrackTarget.gpxfile {} has backend {}'.format(
            self.gpxfile, self.gpxfile.backend)
        return new_ident

    def end(self):
        """End lifetracking for a specific backend.
        Because of fencing, lifetracking may not even have started."""
        if self.gpxfile.point_list() or self.backend.accepts_zero_points:
            self.backend._lifetrack_end(self.gpxfile)

    def _prepare_points(self, points):
        """Round points and remove those within fences.

        Returns (list):
            The prepared points

        """
        result = [x for x in points if self.backend.account.fences.outside(x)]
        if len(result) < len(points):
            self.backend.logger.debug("Fences removed %d out of %d points", len(points) - len(result), len(points))
        self.gpxfile._round_points(result)
        return result


class Lifetrack:

    """Life tracking. The data will be forwarded to all given backends.

    Args:
        sender_ip: The IP of the client.
        target_backends (list): Those gpxfiles will receive the lifetracking data.
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
            ids = [x if x != 'None' else None for x in ids]
        self.sender_ip = sender_ip
        self.targets = [LifetrackTarget(target, use_id) for target, use_id in zip(target_backends, ids)]
        self.done = False

    def tracker_id(self) ->str:
        """One string holding all backend ids.

        Returns: that string or None.

        """
        try:
            return '----'.join(x.gpxfile.id_in_backend or 'None' for x in self.targets)
        except TypeError:
            return None

    def start(self, points, title=None, public=None, category=None):
        """Start lifetracking.

        Returns: All id_in_backend joined by '----'

        """
        if title is None:
            title = str(datetime.datetime.now())[:16]
        if public is None:
            public = False

        for _ in self.targets:
            with _.gpxfile._decouple():
                # decouple because the _life* methods will put data into the backend
                _.gpxfile.title = title
                _.gpxfile.public = public
                _.gpxfile.category = category
                _.started = _.gpxfile.id_in_backend is not None
        self.update_trackers(points)
        return self.tracker_id()

    def update_trackers(self, points):
        """Start or update lifetrack.

        If the backend does not support lifetrack, this just saves the gpxfile in the backend.

        Args:
            points(list): New points

        """
        for _ in self.targets:
            _.update_tracker(points)

    def end(self):
        """End lifetrack.

        If the backend does not support lifetrack, this does nothing."""
        for _ in self.targets:
            _.end()
        self.done = True

    def __str__(self):  # noqa
        return 'Lifetrack({}{})'.format(self.tracker_id(), ' done' if self.done else '')

    def __repr__(self):  # noqa
        return str(self)
