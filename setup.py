#!/usr/bin/env python3

"""
see https://setuptools.readthedocs.io/en/latest/setuptools.html
"""

from setuptools import setup, find_packages

def readall(path):
    """explicitly close the file again"""
    with open(path) as in_file:
        return in_file.read()

setup(
    name='Gpxity',
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    description='A uniform interface to GPX services like mapmytracks or gpsies',
    long_description=readall('README.rst') + '\n\n' + readall('CHANGELOG.rst'),
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
    packages=find_packages(),
    install_requires=['requests', 'lxml'],
    scripts=['bin/gpxdo'],
    test_suite='gpxity.backends.test',
    extras_require={
        'develop': ['coverage', 'sphinx', 'sphinx-autodoc-annotation', 'pytest']
        })
