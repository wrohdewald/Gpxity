#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.
# The source in this file is inspired by and partially identical with paramiko.config


"""Configuration file for accounts in Backends."""

import os
import re
import logging
import copy


class Accounts:

    """Representation of config information as stored in the format used by Gpxity.

    Queries can be made via `lookup`. The format is a subset of
    ssh, see man ssh_config. But without variable expansion. The keyword
    Account only allows one name. Wildcards are supported in the Account
    name. Earlier matches
    have precendence over later matches.

    Keywords are case insensitive, arguments are not.

    """

    # pylint: disable=too-few-public-methods

    SETTINGS_REGEX = re.compile(r'(\w+)(?:\s*=\s*|\s+)(.+)')

    __account_files = dict()

    @classmethod
    def __parse(cls, path):
        """Parse an accounts file."""
        if path not in cls.__account_files:
            if not os.path.exists(path):
                logging.error('%s not found', path)
                return
            with open(path) as account_file:
                cls.__account_files[path] = cls.__parse_accounts(account_file)

    @classmethod
    def __parse_accounts(cls, file_obj):
        """Parse all accounts from file_obj.

        Returns: dict with all accounts.filename

        """
        result = dict()
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
            match = re.match(cls.SETTINGS_REGEX, line)
            if not match:
                raise Exception('Unparsable line {}'.format(line))
            yield match

    @classmethod
    def __yield_accounts(cls, file_obj):
        """Generate all accounts."""
        account = None
        for match in cls.__yield_matches(file_obj):
            key = match.group(1).lower()
            value = match.group(2)

            if key == 'account':
                value = value.lower()
                if account is not None:
                    yield account
                account = {
                    'name': value,
                }
                continue

            if key == 'url':
                if value.endswith('/') and value != '/':
                    raise Exception('Account {}: url {} must not end with /'.format(account['name'], value))

            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]

            if key not in account:
                account[key] = value

        if account is not None:
            yield account

    @classmethod
    def lookup(cls, filename, wanted_account):
        """
        Return a dict of config options for a given wanted_account.

        Returns: The dict

        """
        cls.__parse(filename)
        return copy.deepcopy(cls.__account_files[filename][wanted_account.lower()])


class Account:

    """As parsed from the accounts file. TODO: more docstring."""

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
            return
        self.name = name
        path = os.path.expanduser(filename or Account.path)
        lookup_name = name.split(':')[0]
        self.config = Accounts.lookup(path, lookup_name)
        if self.backend is None:
            raise Exception('Account({}, {}, {}) defines no Backend'.format(name, filename, kwargs))
        for key, value in kwargs.items():
            self.config[key.lower()] = value
        self.config['from_name'] = name
        if self.name.lower().startswith('directory:'):
            self.name = self.name[len('directory:'):]
        if self.name == '':
            self.name = '.'
    #    logging.error('%s: Using account data from %s kwargs=%s', self.name, accounts.filename, kwargs)

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
        result = 'Account({} -> {}: backend={}'.format(self.from_name, self.account, self.backend)
        if 'url' in self.config:
            result += ' url={}'.format(self.url)
        if 'username' in self.config:
            result += ' username={}'.format(self.username)
        return result + ')'

    def __str__(self):
        """The account in a parseable form.

        Returns: The string

        """
        if self.backend == 'Directory':
            if self.name == '.':
                return ''
            if self.name == '/':
                return '/'
            return self.name + '/'
        return self.name + ':'
