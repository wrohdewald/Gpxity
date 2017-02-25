#!/usr/bin/env python3

import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.rst')) as readme_file:
    long_description = readme_file.read()


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
    packages=find_packages(exclude=['doc', 'test', 'bin']),
    install_requires=['requests', 'gpxpy'],
    extras_require={
        'test': ['coverage'],
        'dev': ['sphinx', 'sphinx-autodoc-annotation']
        })



