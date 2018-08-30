# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.Authenticate`."""

import logging
import os
from configparser import ConfigParser

__all__ = ['Authenticate']


class Authenticate:

    """
    Get password and / or Url from auth.cfg.

    If nothing is useable, sets them to None.

    auth.cfg is expected in :literal:`~/.config/Gpxity/auth.cfg`

    .. DANGER::
       auth.cfg is not encrypted. Better not use this unless you know what you are doing!

    Args:
        backend (Backend): The backend
        username (str): For the wanted account in the backend

    Attributes:
        path (str): The name for the auth file. Class variable, to be changed before
          Authenticate() is instantiated.

        auth (tuple(str,str)): (username, password). Both are either str or None.

        url: If given, overrides the url given to the backend

    For every specific account in a backend, auth.cfg has a section. Its name is
    case sensitive: The ClassName must match exactly.

      * [ClassName.username]

    A section can define
      * Password
      * Url
      * Mysql, used by WPTrackserver

    An example for user gpxitytest on gpsies.com:

    .. code-block:: guess

        [GPSIES:gpxitytest]
        Password = the_unencrypted_password

    A mail account:

    .. code-block:: guess

        [Mailer:gpxitytest]
        Url = tester@test.test


    """

    # pylint: disable=too-few-public-methods

    path = '~/.config/Gpxity/auth.cfg'

    def __init__(self, backend, username: str = None):
        """See class docstring."""

        logging.debug('Authenticate(%s, %s)', backend, username)
        self.backend = backend
        self.__username = username
        self.auth = (None, None)
        self.url = None
        self.section = dict()
        self.__path = os.path.expanduser(self.path)
        with open(self.__path) as auth_file:
            self._parse_config(auth_file.read())

    def _parse_config(self, data):
        """try to use data."""

        password = None

        config = ConfigParser()
        config.read_string(data)

        config_key = '{}:{}'.format(self.backend.__class__.__name__, self.__username)
        try:
            self.section = config[config_key]
        except KeyError:
            if self.backend.needs_config:
                raise KeyError('Section [{}] not found in {}'.format(config_key, self.__path))
        if 'Password' in self.section:
            password = self.section['Password']
        if 'Url' in self.section:
            self.url = self.section['Url']
        else:
            self.url = self.backend.url

        self.auth = (self.__username, password)
