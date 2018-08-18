#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This implements a mailing backend. It can only write."""

import datetime
from threading import Timer
import smtplib
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
        self.tracks = dict()
        self.last_sent_time = datetime.datetime.now() - datetime.timedelta(days=5)

    def append(self, track):
        """Append a track to the mailing queue."""
        self.tracks[track.id_in_backend] = track.clone()

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
            return self.mailer.subject_template.format(
                title=track.title, distance='{:8.3f}km'.format(track.distance()))
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
        mail = EmailMessage()
        mail['subject'] = self.subject()
        mail['from'] = self.mailer.config.get('From', 'gpxity')
        mail['to'] = self.mailer.url.split()
        content = EmailMessage()
        content.set_content('\n'.join(self.content()))
        mail.add_attachment(content)

        for key, track in self.tracks.items():
            attachment = EmailMessage()
            attachment.set_content(track.to_xml())
            if not key.endswith('.gpx'):
                key += '.gpx'
            attachment.add_header('Content-Disposition', 'attachment', filename=key)
            mail.add_attachment(attachment)
        with smtplib.SMTP(self.mailer.config.get('Smtp', 'localhost')) as smtp_server:
            smtp_server.send_message(mail)
        self.last_sent_time = datetime.datetime.now()
        self.tracks = dict()

    def __repr__(self):
        """Return repr."""
        return 'MailQueue({} to {}'.format(', '.join(str(x) for x in self.tracks.values()), self.mailer.url)  # noqa


class Mailer(Backend):  # pylint: disable=abstract-method

    """Mailing backend. Write-only.

    Attributes:
        subject_template: This builds the mail subject. {title} and {distance} will
            be replaced by their respective values. Other placeholders are not yet defined.
        min_interval: seconds. Mails are not sent more often. Default is 10. If None, always send immediately.
            The first mail will always be sent immediately.
        outstanding_tracks: Do not change this dict. Key is track.id_in_backend(), value is
            a clone of the track. This freezes the current title in the clone.
        url: Holds the address of the recipient.

    """

    id_count = 0

    def __init__(self, url=None, auth=None, cleanup=False, timeout=None, verify=True):
        """See class docstring."""
        super(Mailer, self).__init__(url, auth, cleanup, timeout, verify)
        if self.url.endswith('/'):
            self.url = self.url[:-1]
        self.history = list()
        self.subject_template = '{title} {distance}'
        self.min_interval = 10
        self.timer = None
        self._start_timer(1)  # Do not delay first mail by more than 1 second
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
            with track._decouple():  # pylint: disable=protected-access
                track.id_in_backend = new_ident
        self.queue.append(track)
        if self.queue.last_sent_time + datetime.timedelta(seconds=self.min_interval or 0) < datetime.datetime.now():
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
                interval = self.min_interval
            self.timer = Timer(interval, self.flush)
            self.timer.start()

    def _lifetrack_end(self, track):
        """flush."""
        self._write_all(track)
        self.flush()

    def identifier(self, track=None) ->str:
        """A unique identifier.

        Returns:
            the unique identifier

        """
        return 'mailto:{}'.format(self.url)
