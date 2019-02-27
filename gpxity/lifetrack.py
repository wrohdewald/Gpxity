#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.lifetrack.Lifetrack`."""

# pylint: disable=protected-access

import datetime
import logging

from .gpxfile import GpxFile
from .backend_base import BackendBase

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
                logging.debug('Lifetrack now also tracks into %s', self.identifier())
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

    def identifier(self):
        """Like GpxFile.identifier.

        But here the GpxFile has no backend!
        """
        return '{}{}'.format(self.backend.account, self.gpxfile.id_in_backend)

class Lifetrack:

    """Life tracking. The data will be forwarded to all given backends.

    Args:
        sender_ip: The IP of the client.
        target_backends (list): Those gpxfiles will receive the lifetracking data.
        tracker _id: The id for this Lifetrack instance.

    Attributes:
        done: Will be True after end() has been called.

    """

    def __init__(self, sender_ip, target_backends, tracker_id: str = None):
        """See class docstring."""
        assert sender_ip is not None
        self.sender_ip = sender_ip
        main_target = LifetrackTarget(target_backends[0], tracker_id)
        self.targets = [main_target]
        other_ids = set(main_target.gpxfile.ids)
        for other_backend in target_backends[1:]:
            for try_this in other_ids:
                acc, ident = BackendBase.parse_objectname(try_this)
                if str(acc) == str(other_backend.account):
                    self.targets.append(LifetrackTarget(other_backend, ident))
                    break
            else:
                self.targets.append(LifetrackTarget(other_backend, None))

        logging.debug('Lifetrack initially tracking into %s', ', '.join(x.identifier() for x in self.targets))
        self.done = False

    def tracker_id(self) ->str:
        """Identify this Lifetrack instance.

        Returns: str

        """
        try:
            return self.targets[0].gpxfile.id_in_backend
        except BaseException as exc:
            logging.debug('tracker_id said %s', exc)

    def start(self, points, title=None, public=None, category=None):
        """Start lifetracking.

        Returns: The id for this tracker to be given to the client

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

        # All secondary targets must be linked to the primary one.
        # Only the primary target is granted to exist when tracking starts.
        main_target = self.targets[0]
        main = main_target.backend[main_target.gpxfile.id_in_backend]
        with main.batch_changes():
            for secondary in self.targets[1:]:
                if secondary.started:
                    secondary_id = secondary.identifier()
                    if secondary_id not in main.ids:
                        new_ids = main.ids
                        new_ids.append(secondary_id)
                        main.ids = new_ids

    def end(self):
        """End lifetrack.

        If the backend does not support lifetrack, this does nothing."""
        for _ in self.targets:
            _.end()
        self.done = True

    def __str__(self):  # noqa
        return 'Lifetrack({} plus {}: {})'.format(
            self.tracker_id(), self.targets[0].gpxfile.ids, ' done' if self.done else '')

    def __repr__(self):  # noqa
        return str(self)
