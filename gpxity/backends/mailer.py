#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This implements a mailing backend. It can only write."""

import datetime
from subprocess import Popen, PIPE
from threading import Timer
import logging

from .. import Backend
from ..backends import Directory

__all__ = ['Mailer']


class MailerAtom:

    """Holds all data representing a sent mail."""

    # pylint: disable=too-few-public-methods

    def __init__(self, mailer, track, subject_template):
        """See class docstring."""
        self.mailer = mailer
        self.track = track.clone()  # fix current state
        self.url = track.backend.url
        self.id_in_backend = track.id_in_backend
        self.subject_template = subject_template
        self.send_time = self.send()

    def send(self):
        """Actually sends the mail.

        Mailer.url hold the mail addresses, separated by comma.

        Returns:

            The time whethe mail was sent."""

        with Directory(cleanup=True) as temp_dir:
            temp_dir.add(self.track)
            msg = 'GPX is attached\n\n\n'
            msg += self.track.description
            msg = msg.encode('utf-8')
            subject = self.track.title
            subject = self.subject_template.format(
                title=self.track.title, distance='{:8.3f}km'.format(self.track.distance()))
            process = Popen(
                ['mutt', '-s', subject, '-a', temp_dir.gpx_path(temp_dir[0].id_in_backend),
                 '--', self.url],
                stdin=PIPE)
            process.communicate(msg)
            logging.debug('Mail sent to %s: %s %s', self.url, subject, msg)
        return datetime.datetime.now()

    def __repr__(self):
        """Returns repr."""
        return 'MailerAtom({} to {}'.format(self.track, self.url)


class Mailer(Backend):  # pylint: disable=abstract-method

    """This is a minimal implementation, it only supports listing and retrieving tracks and life tracking.

    This is used for testing examples/mmtserver.py which in turn is used to
    receive life tracking data from smartphone apps like oruxmaps.

    Attributes:
        subject_template: This builds the mail subject. {title} and {distance} will
            be replaced by their respective values. Other placeholders are not yet defined.
        min_interval: seconds. Mails are not sent more often. Default is 1800.

    """

    id_count = 0

    def __init__(self, url=None, auth=None, cleanup=False, debug=False, timeout=None, verify=True):
        super(Mailer, self).__init__(url, auth, cleanup, debug, timeout, verify)
        if self.url.endswith('/'):
            self.url = self.url[:-1]
        self.history = list()
        self.subject_template = '{title} {distance}'
        self.min_interval = 1800
        self.last_sent_time = datetime.datetime.now() - datetime.timedelta(days=5)
        self.timer = None

    def _new_ident(self, _):
        """Buids a unique id for track."""
        self.id_count += 1
        return str(self.id_count)

    def _write_all(self, track) ->str:
        """Mail the track.

        Returns:
            track.id_in_backend

        """
        if track.id_in_backend is None:
            new_ident = self._new_ident(track)
            with track._decouple():  # pylint: disable=protected-access
                track.id_in_backend = new_ident
        remaining = self.last_sent_time + datetime.timedelta(seconds=self.min_interval) - datetime.datetime.now()
        if remaining.total_seconds() <= 0:
            self._really_write(track)
        else:
            if self.timer is None:
                self.timer = Timer(remaining.total_seconds(), self._really_write(track))
        return track.id_in_backend

    def _really_write(self, track):
        """Now is the time to write."""
        if track.gpx.get_track_points_no():
            self.last_sent_time = datetime.datetime.now()
            self.history.append(MailerAtom(self, track, self.subject_template))
            self.timer = None

    def identifier(self, track=None):
        return 'mailto:{}'.format(self.url)
