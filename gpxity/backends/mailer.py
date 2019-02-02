#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
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
        self.gpxfiles = dict()
        self.last_sent_time = datetime.datetime.now() - datetime.timedelta(days=5)

    def append(self, gpxfile):
        """Append a gpxfile to the mailing queue."""
        self.gpxfiles[gpxfile.id_in_backend] = gpxfile.clone()
        if hasattr(gpxfile, 'mail_subject'):
            self.gpxfiles[gpxfile.id_in_backend].mail_subject = gpxfile.mail_subject

    def subject(self, gpxfile=None) ->str:
        """Build the mail subject.

        Args:
            gpxfile: If given, use only gpxfile. Otherwise use self.gpxfiles

        Returns:
            The subject

        """
        if len(self.gpxfiles) == 1:
            for _ in self.gpxfiles.values():
                gpxfile = _
        if gpxfile is not None:
            subject = gpxfile.mail_subject if hasattr(gpxfile, 'mail_subject') else gpxfile.title
            return self.mailer.subject_template.format(
                title=subject, distance='{:8.3f}km'.format(gpxfile.distance))
        return '{} gpxfiles'.format(len(self.gpxfiles))

    def content(self) ->str:
        """The content of the mail message.

        Returns: list
            The content, a list with lines

        """
        is_single = len(self.gpxfiles) == 1
        result = list()
        for key, gpxfile in self.gpxfiles.items():
            if not key.endswith('.gpx'):
                key += '.gpx'
            if is_single:
                result.append(gpxfile.description)
                result.append('See the attached GPX file {}'.format(key))
            else:
                result.append(self.subject(gpxfile))
                indent = '   '
                result.append('{}See the attached GPX file {}'.format(indent, key))
                result.append('{}{}'.format(indent, gpxfile.description))
            result.append('')
            result.append('')
        return result

    def send(self):
        """Actually send the mail if there are any points."""
        if not self.gpxfiles:
            return
        if self.disabled:
            self.gpxfiles = dict()
            return
        account = self.mailer.account
        mail = EmailMessage()
        mail['subject'] = self.subject()
        mail['from'] = account.mailfrom or 'gpxity'
        mail['to'] = account.url.split()
        mail.set_content('\n'.join(self.content()))

        for key, gpxfile in self.gpxfiles.items():
            if not key.endswith('.gpx'):
                key += '.gpx'
            mail.add_attachment(gpxfile.xml(), filename=key)
        host = account.smtp or 'localhost'
        port = int(account.port or '25')
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
        self.gpxfiles = dict()

    def __repr__(self):
        """Return repr."""
        return 'MailQueue({} to {}'.format(', '.join(str(x) for x in self.gpxfiles.values()), self.mailer.url)  # noqa


class Mailer(Backend):  # pylint: disable=abstract-method

    """Mailing backend. Write-only.

    Attributes:
        subject_template: This builds the mail subject. {title} and {distance} will
            be replaced by their respective values. Other placeholders are not yet defined.
        url: Holds the address of the recipient.
        account.mailfrom: The name of the mail sender. Default "gpxity".
        account.port: The port of the smtp server to talk to. Default 25
        account.smtp: The name of the smtp server. Default "localhost".
        account.interval (str): seconds. Mails are not sent more often. Default is None. If None, always send when
            Mailer.flush() is called. This is used for bundling several writes into one single mail:
            gpxdo merge --copy will send all gpxfiles with one single mail.
            Lifetracking uses this to send mails with the current gpxfile only every X seconds, the
            mail will only contain the latest version of the gpxfile.

    """

    id_count = 0

    test_is_expensive = False

    def __init__(self, account):
        """See class docstring."""
        super(Mailer, self).__init__(account)
        self.history = list()
        self.subject_template = '{title} {distance}'
        self.timer = None
        self.queue = MailQueue(self)

    def _new_ident(self, _) ->str:
        """Build a unique id for gpxfile.

        Returns:
            A new unique id.

        """
        self.id_count += 1
        return str(self.id_count)

    def _write_all(self, gpxfile) ->str:
        """Mail the gpxfile.

        Returns:
            gpxfile.id_in_backend

        """
        if gpxfile.id_in_backend is None:
            new_ident = self._new_ident(gpxfile)
            with gpxfile._decouple():
                gpxfile.id_in_backend = new_ident
        self.queue.append(gpxfile)
        if self.account.interval is not None:
            seconds = int(self.account.interval)
            if self.queue.last_sent_time + datetime.timedelta(seconds=seconds) < datetime.datetime.now():
                self.queue.send()
            else:
                self._start_timer()
        return gpxfile.id_in_backend

    def detach(self):
        """Mail the rest."""
        if self.timer:
            self.timer.cancel()
        self.queue.send()

    def flush(self):
        """Now is the time to write."""
        # this dict reduces all gpxfiles to just one instance
        self.queue.send()
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def _start_timer(self, interval=None):
        """Start the flush timer."""
        if self.timer is None:
            if interval is None:
                interval = int(self.account.interval)
            self.timer = Timer(interval, self.flush)
            self.timer.start()

    def _lifetrack_start(self, gpxfile, points) ->str:
        """flush.

        Returns: The new id_in_backend.

        """
        gpxfile.mail_subject = 'Lifetracking starts: {}'.format(gpxfile.title)
        new_ident = self._write_all(gpxfile)
        self._append(gpxfile)
        assert self._has_item(new_ident), '{} not in {}'.format(new_ident, self)
        self.flush()
        return new_ident

    def _lifetrack_update(self, gpxfile, points):
        """flush."""
        gpxfile.mail_subject = 'Lifetracking continues: {}'.format(gpxfile.title)
        self._write_all(gpxfile)

    def _lifetrack_end(self, gpxfile):
        """flush."""
        gpxfile.mail_subject = 'Lifetracking ends: {}'.format(gpxfile.title)
        self._write_all(gpxfile)
        self.flush()

    def __str__(self) ->str:
        """A unique identifier.

        Returns:
            the unique identifier

        """
        return 'mailto:{}'.format(self.url)
