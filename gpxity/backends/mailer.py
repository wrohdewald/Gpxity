#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This implements :class:`gpxity.mailer.Mailer`: a mailing backend. It can only write."""

# pylint: disable=protected-access

import datetime
from threading import Timer
import smtplib
import socket
import logging
from email.message import EmailMessage

from .. import Backend

__all__ = ['Mailer']


class MailQueue:

    """Holds all data representing a sent mail."""

    # pylint: disable=too-few-public-methods

    counter = 0

    def __init__(self, mailer):
        """See class docstring."""
        self.mailer = mailer
        self.disabled = False
        self.tracks = dict()
        self.last_sent_time = datetime.datetime.now() - datetime.timedelta(days=5)

    def append(self, track):
        """Append a track to the mailing queue."""
        self.tracks[track.id_in_backend] = track.clone()
        if hasattr(track, 'mail_subject'):
            self.tracks[track.id_in_backend].mail_subject = track.mail_subject

    def subject(self, track=None) ->str:
        """Build the mail subject.

        Args:
            track: If given, use only track. Otherwise use self.tracks

        Returns:
            The subject

        """
        if len(self.tracks) == 1:
            for _ in self.tracks.values():
                track = _
        if track is not None:
            subject = track.mail_subject if hasattr(track, 'mail_subject') else track.title
            return self.mailer.subject_template.format(
                title=subject, distance='{:8.3f}km'.format(track.distance()))
        return '{} tracks'.format(len(self.tracks))

    def content(self) ->str:
        """The content of the mail message.

        Returns: list
            The content, a list with lines

        """
        is_single = len(self.tracks) == 1
        result = list()
        for key, track in self.tracks.items():
            if not key.endswith('.gpx'):
                key += '.gpx'
            if is_single:
                result.append(track.description)
                result.append('See the attached GPX file {}'.format(key))
            else:
                result.append(self.subject(track))
                indent = '   '
                result.append('{}See the attached GPX file {}'.format(indent, key))
                result.append('{}{}'.format(indent, track.description))
            result.append('')
            result.append('')
        return result

    def send(self):
        """Actually send the mail if there are any points."""
        if not self.tracks:
            return
        if self.disabled:
            self.tracks = dict()
            return
        section = self.mailer.config.section
        mail = EmailMessage()
        mail['subject'] = self.subject()
        mail['from'] = section.get('From', 'gpxity')
        mail['to'] = self.mailer.url.split()
        mail.set_content('\n'.join(self.content()))

        for key, track in self.tracks.items():
            if not key.endswith('.gpx'):
                key += '.gpx'
            mail.add_attachment(track.to_xml(), filename=key)
        host = section.get('Smtp', 'localhost')
        port = int(section.get('port', '25'))
        timeout = self.mailer.timeout
        if isinstance(timeout, (tuple, list)):
            timeout = timeout[0]
        try:
            with smtplib.SMTP(  # noqa
                    host,
                    port=port,
                    timeout=timeout) as smtp_server:
                smtp_server.send_message(mail)
        except socket.timeout:
            logging.error('Mailer: Disabled because the smtp server %s:%d did not answer within %d seconds ',
                          host, port, self.mailer.timeout)
            self.disabled = True
        except smtplib.SMTPRecipientsRefused as exc:
            logging.error('Mailer: Disabled because some Recipients are refused: %s', exc.recipients)
            self.disabled = True
            raise
        self.last_sent_time = datetime.datetime.now()
        self.mailer.history.append('to {}: {}'.format(mail['to'], mail['subject']))
        self.tracks = dict()

    def __repr__(self):
        """Return repr."""
        return 'MailQueue({} to {}'.format(', '.join(str(x) for x in self.tracks.values()), self.mailer.url)  # noqa


class Mailer(Backend):  # pylint: disable=abstract-method

    """Mailing backend. Write-only.

    Attributes:
        subject_template: This builds the mail subject. {title} and {distance} will
            be replaced by their respective values. Other placeholders are not yet defined.
        outstanding_tracks: Do not change this dict. Key is track.id_in_backend(), value is
            a clone of the track. This freezes the current title in the clone.
        url: Holds the address of the recipient.
        config.from: The name of the mail sender. Default "gpxity".
        config.port: The port of the smtp server to talk to. Default 25
        config.smtp: The name of the smtp server. Default "localhost".
        config.interval (str): seconds. Mails are not sent more often. Default is None. If None, always send when
            Mailer.flush() is called. This is used for bundling several writes into one single mail:
            gpxdo merge --copy will send all tracks with one single mail.
            Lifetracking uses this to send mails with the current track only every X seconds, the
            mail will only contain the latest version of the track.

    """

    id_count = 0

    def __init__(self, url=None, auth=None, cleanup=False, timeout=None):
        """See class docstring."""
        super(Mailer, self).__init__(url, auth, cleanup, timeout)
        self.history = list()
        self.subject_template = '{title} {distance}'
        self.timer = None
        self.queue = MailQueue(self)

    def _new_ident(self, _) ->str:
        """Build a unique id for track.

        Returns:
            A new unique id.

        """
        self.id_count += 1
        return str(self.id_count)

    def _write_all(self, track) ->str:
        """Mail the track.

        Returns:
            track.id_in_backend

        """
        if track.id_in_backend is None:
            new_ident = self._new_ident(track)
            with track._decouple():
                track.id_in_backend = new_ident
        self.queue.append(track)
        if self.config.interval is not None:
            seconds = int(self.config.interval)
            if self.queue.last_sent_time + datetime.timedelta(seconds=seconds) < datetime.datetime.now():
                self.queue.send()
            else:
                self._start_timer()
        return track.id_in_backend

    def destroy(self):
        """Mail the rest."""
        if self.timer:
            self.timer.cancel()
        self.queue.send()

    def flush(self):
        """Now is the time to write."""
        # this dict reduces all tracks to just one instance
        self.queue.send()
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def _start_timer(self, interval=None):
        """Start the flush timer."""
        if self.timer is None:
            if interval is None:
                interval = int(self.config.interval)
            self.timer = Timer(interval, self.flush)
            self.timer.start()

    def _lifetrack_start(self, track, points) ->str:
        """flush.

        Returns: The new id_in_backend.

        """
        track.mail_subject = 'Lifetracking starts: {}'.format(track.title)
        track.add_points(points)
        new_ident = self._write_all(track)
        self._append(track)
        assert self._has_item(new_ident), '{} not in {}'.format(new_ident, self)
        self.flush()
        return new_ident

    def _lifetrack_update(self, track, points):
        """flush."""
        track.mail_subject = 'Lifetracking continues: {}'.format(track.title)
        track.add_points(points)
        self._write_all(track)

    def _lifetrack_end(self, track):
        """flush."""
        track.mail_subject = 'Lifetracking ends: {}'.format(track.title)
        self._write_all(track)
        self.flush()

    def __str__(self) ->str:
        """A unique identifier.

        Returns:
            the unique identifier

        """
        return 'mailto:{}'.format(self.url)
