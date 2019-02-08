#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.
# The source in this file is inspired by and partially identical with paramiko.config


"""Configuration file for accounts in Backends."""

import os
import re
import copy
import tempfile

from gpxpy.geo import Location

__all__ = ['Account', 'DirectoryAccount']


class Fences:  # pylint: disable=too-few-public-methods

    """
    Defines circles.

    Args:
        config_str: The string from the accounts file
    Attributes:
        center (GPXTrackPoint): The center
        radius (meter): The radius in meters

    """

    def __init__(self, config_str: str):
        """init."""
        self.circles = list()
        if config_str is not None:
            for fence in config_str.split(' '):
                parts = fence.split('/')
                if len(parts) != 3:
                    raise ValueError('fence needs 3 parts: {}'.format(fence))
                try:
                    parts = [x.strip() for x in parts]
                    center = Location(float(parts[0]), float(parts[1]))
                    radius = float(parts[2])
                except Exception:
                    raise ValueError('Fence definition is wrong: {}'.format(fence))
                circle = (center, radius)
                self.circles.append(circle)

    def outside(self, point) ->bool:
        """Determine if point is outside of all fences.

        Returns: True or False.

        """
        return all(point.distance_2d(x[0]) > x[1] for x in self.circles)


class Accounts:

    """Representation of config information as stored in the format used by Gpxity.

    Queries can be made via `lookup`. The keyword  :literal:`Account` only allows one name.

    Keywords are case insensitive, arguments are not.

    Example for an entry in the accounts file:

    ::

        Account wp
            Backend WPTrackserver
            Username wordpress_username
            Url localhost
            Mysql wordpress_7@wordpress_7
            Password xxxx
            Fences 53.7505,10.7445/750

    """

    # pylint: disable=too-few-public-methods

    __SETTINGS_REGEX = re.compile(r'(\w+)(?:\s*=\s*|\s+)(.+)')

    __account_files = dict()

    @classmethod
    def __parse(cls, path):
        """Parse an accounts file."""
        if path not in cls.__account_files:
            if not os.path.exists(path):
                return
            cls.__account_files[path] = cls.__parse_accounts(path)

    @classmethod
    def __parse_accounts(cls, filename):
        """Parse all accounts from filename.

        Returns: dict with all accounts.filename

        """
        result = dict()
        with open(filename) as file_obj:
            for _ in cls.__yield_accounts(file_obj):
                result[_['name']] = _
        return result

    @staticmethod
    def __strip_whitespace(file_obj):
        """Filter out comments, strip lines."""
        for line in file_obj:
            line = line.strip()
            if line and not line.startswith('#'):
                yield line

    @classmethod
    def __yield_matches(cls, file_obj):
        """Yield usable lines."""
        for line in cls.__strip_whitespace(file_obj):
            match = re.match(cls.__SETTINGS_REGEX, line)
            if not match:
                raise Exception('Unparsable line {}'.format(line))
            yield match

    @classmethod
    def __yield_accounts(cls, file_obj):
        """Generate all accounts."""
        account = {'name': 'global'}
        for match in cls.__yield_matches(file_obj):
            key = match.group(1).lower()
            value = match.group(2)

            if key == 'account':
                if account is not None:
                    yield account
                account = {'name': value.lower()}
                continue

            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]

            if key not in account:
                account[key] = value

        if account is not None:
            yield account

    @classmethod
    def lookup(cls, filename: str, wanted_account: str):
        """
        Build an :class:`~gpxity.accounts.Account`.

        Args:
            filename: The name of the accounts file
            wanted_account: The name to look for in the accounts file

        Returns: dict

        """
        cls.__parse(filename)
        return copy.deepcopy(cls.__account_files[filename][wanted_account.lower()])


class Account:

    """As parsed from the accounts file.

    Attributes can be referenced as account.xxxx where xxx is an arbitrary
    value in the account definition from the accounts file.

    Args:
        name: The name of the account. Must exist in the accounts file.
        filename: Name of the accounts file. Default is Account.path
        kwargs: Additional parameters added to the account. They have precedence.

    If both name and file are None, only :literal:`**kwargs` are used.

    Attributes:
        path: Default value for the accounts file
        name: The name of the account
        config: A dict with all config values
        backend: The name of the backend class
        fences: The backend will never write points within fences.
            You can define any number of fences separated by spaces. Every fence is a circle.
            It has the form Lat/Long/meter.
            Lat and Long are the center position in decimal degrees, meter is the radius.

    """

    path = '~/.config/Gpxity/accounts'

    def __init__(self, name=None, filename=None, **kwargs):
        """Create an Account."""
        if name is None:
            self.config = dict()
            for key, value in kwargs.items():
                self.config[key.lower()] = value
            self.name = self.url or '.'
            if not self.backend:
                self.config['backend'] = 'Directory'
            self._resolve_fences()
            return
        self.name = name
        path = os.path.expanduser(filename or Account.path)
        lookup_name = name.split(':')[0]
        self.config = Accounts.lookup(path, lookup_name)
        if self.backend is None:
            raise Exception('Account({}, {}, {}) defines no Backend'.format(name, filename, kwargs))
        for key, value in kwargs.items():
            self.config[key.lower()] = value
        self._resolve_fences()

    def _resolve_fences(self):
        """create self.fences as a Fences instance."""
        if 'fences' in self.config:
            _ = Fences(self.config['fences'])
            del self.config['fences']
            self.fences = _
        else:
            self.fences = Fences(None)

    def __getattr__(self, key):
        """Only called if key is not an existing attribute.

        Returns: The value or None

        """
        try:
            config = object.__getattribute__(self, 'config')
        except AttributeError:
            return None
        return config.get(key.lower())

    def __repr__(self):
        """For debugging output.

        Returns: the str

        """
        result = 'Account({}): backend={}'.format(self.account, self.backend)
        if 'url' in self.config:
            result += ' url={}'.format(self.url)
        if 'username' in self.config:
            result += ' username={}'.format(self.username)
        return result + ')'

    def __str__(self):
        """The account in a parseable form.

        Returns: The string

        """
        return self.name + ':'


class DirectoryAccount(Account):

    """This will not use an acocunts file but the optional file :literal:`.config`.

    Args:
        url: The name of the directory. If it does not exist, create it.
            "" will translate into ".".
            A trailing "/" will raise an Exception.
            None will create a temporary directory.
        kwargs: Additional parameters added to the account. They have precedence.

    Attributes:
        path: Default value for the accounts file
        name: The name of the account
        config: A dict with all config values
        backend: The name of the backend class
        is_temporary: True for temporary directories.
        fences: The backend will never write points within fences.
            You can define any number of fences separated by spaces. Every fence is a circle.
            It has the form Lat/Long/meter.
            Lat and Long are the center position in decimal degrees, meter is the radius.
        prefix (str):  Class attribute, may be changed. The default prefix for
            temporary directories. Default value is :literal:`gpxity.`

    """

    path = None
    prefix = 'gpxity.'

    def __init__(self, url=None, **kwargs):  # pylint: disable=super-init-not-called
        """Create an Account."""
        self.is_temporary = url is None
        if self.is_temporary:
            url = tempfile.mkdtemp(prefix=self.__class__.prefix)
        if url == '':
            url = '.'
        if url == '/':
            raise Exception('Directory / is not allowed')
        if url.endswith('/') and url != '/':
            raise Exception('DirectoryAccount: url {} must not end with /'.format(url))
        self.config = dict()
        if not os.path.exists(url):
            os.makedirs(url)
        else:
            config_name = os.path.join(url, '.gpxity_config')
            if os.path.exists(config_name):
                self.config = Accounts.lookup(config_name, 'global')
        self.config['backend'] = 'Directory'
        self.config['url'] = url
        for key, value in kwargs.items():
            self.config[key.lower()] = value
        self.name = url
        self._resolve_fences()

    def __repr__(self):
        """For debugging output.

        Returns: the str

        """
        return 'DirectoryAccount({})'.format(self.name)

    def __str__(self):
        """The account in a parseable form.

        Returns: The string

        """
        if self.name == '.':
            return ''
        if self.name == '/':
            return '/'
        return self.name + '/'
