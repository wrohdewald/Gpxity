# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.auth.Authenticate`."""

import os
import logging
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
        backend (~gpxity.backend.Backend): The backend

        username (str): For the wanted account in the backend. You can also pass
            dict(). In that case, the config file is not read at all, only this dict() will
            be used.

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

    def __init__(self, backend, url, username: str = None):
        """See class docstring."""
        self.__config = ConfigParser()
        if isinstance(username, dict):
            self.__section_name = '{}:from_dict'.format(backend.__class__.__name__)
            self.__config[self.__section_name] = {}
            self.section = self.__config[self.__section_name]
            for key, value in username.items():
                self.section[key.lower()] = str(value)
        else:
            self.__section_name = '{}:{}'.format(backend.__class__.__name__, username)
            self.__path = os.path.expanduser(self.path)
            logging.info('Using auth data from %s', self.__path)
            if os.path.exists(self.__path):
                with open(self.__path) as auth_file:
                    self.__config.read_string(auth_file.read())
                    if self.__section_name not in self.__config:
                        if backend.needs_config:
                            raise KeyError('Section [{}] not found in {}'.format(self.__section_name, self.__path))
                        self.__config[self.__section_name] = {}
                    self.section = self.__config[self.__section_name]
                    self.section['username'] = username or ''
            else:
                logging.info('%s not found', self.__path)
                self.section = dict()
        if self.section.get('username', None) == 'wrong_user':
            raise KeyError
        if 'url' not in self.section:
            self.section['url'] = url or ''
        self._check_url()

    def _check_url(self):
        """Check syntax for url."""
        _ = self.url
        if _ and _.endswith('/') and _ != '/':
            raise Exception('url {} must not end with /'.format(_))

    def __getattr__(self, key):
        """Only called if key is not an existing attribute.

        Returns: The value

        """
        return self.section[key.lower()] if key.lower() in self.section else None
