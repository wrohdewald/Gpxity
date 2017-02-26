#!/usr/bin/env python3

import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

long_description = """
Gpxity is a Python - library making it easy to move activities between different backends.
In this context, a backend is a place where activities can be stored.

Implemented backends are:

  * Directory          for .gpx files on an accessible file system
  * ServerDirectory    suited for a server implementation
  * MMT                for activities on http://mapmytracks.com

Sometimes you might just change a harmless thing like the description but
the backend does not allow changing this separately, so we have to re-upload
the whole activity. If it is is big and the remote server slow, this might
take 10 minutes or more. Right now this library has no asynchronous interface,
so it can really take some time until your program continues.

"""

setup(
    name='Gpxity',
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    description='A uniform interface to GPX services like mapmytracks or gpsies',
    long_description=long_description,
    url='https://github.com/wrohdewald/Gpxity',
    author='Wolfgang Rohdewald',
    author_email='wolfgang@rohdewald.de',
    license='GPLv2',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Communications',
        'Topic :: Internet :: WWW/HTTP',
        ],
    packages=find_packages(exclude=['doc', 'test', 'bin', '.gitignore']),
    install_requires=['requests', 'gpxpy'],
    extras_require={
        'test': ['coverage'],
        'dev': ['sphinx', 'sphinx-autodoc-annotation']
        })



