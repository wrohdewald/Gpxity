Changelog
=========

  * WPTrackserver and Directory allow renaming by assinging new id_in_backend
  * Backend.subscription shows the name of the subscription model
  * gpxdo: dates may now contain a time
  * gpxdo split --stops MINUTES instead of fix --jumps
  * gpxdo fix --clear-times, --set-first-time, --set-last-time, --add-times
  * new: Track.locate_point() and Track.add_locations()
  * split class Account into Account and DirectoryAccount

1.6.0 release 2019-01-xx
------------------------

  * integrate ServerDirectory into Directory
  * replace auth_cfg with accounts, new syntax for identifiers

1.5.1 release 2019-01-02
------------------------

  * fix documentation at readthedocs.io
  * gpxdo ls --location shows name of starting place: city, country

1.5.0 release 2019-01-02
------------------------

  * new backend for Openrunner
  * gpxdo --similar now supports a list of tracks
  * new: gpxdo --join
  * Track.merge (and gpxdo merge) now also merge waypoints
  * Up/Download for the same backend class is now lossless for category
  * adapted MMT backend to server changes

1.4.1 release 2018-10-22
------------------------

  * Lifetrack fixes
  * gpxity_server now supports https

1.4.0 release 2018-10-21
------------------------

  * many improvements to gpxity_server and backends with lifetracking capability
  * fixes for WPTrackserver (wants local time and speed per position and distance per track)
  * new: gpxdo dump --points
  * new: Backend.fences for privacy zones

1.3.3.2 release 2018-10-04
--------------------------

  * fix creating doc at readthedocs.io

1.3.3.1 release 2018-10-04
--------------------------

  * all unittests can now be run in the test installation docker

1.3.3 release 2018-10-04
------------------------

  * new Backend WPTrackserver directly accessing its mysql database
  * new: Backend.clone()
  * new: Backend.needs_config
  * new: Track.ids and gpxdo fix --id-from-backend
  * new: gpxdo cp
  * new: Track.first_different_point()
  * Track.merge(), Backend.merge() and gpxdo merge have a new arg partial_tracks
  * new: gpxdo fix --add-minutes
  * new: gpxdo fix --simplify
  * new: gpxdo fix --split
  * new: track.index(other)
  * new: simplify keyword handling: eliminate gpxdo kw --remove
  * gpxdo kw is now gpxdo keywords
  * new: gpxdo ls --locate and class Locate
  * make gpxity_server for lifetracking more stable

1.3.2 release 2018-08-19
------------------------

  * make bin/install_test work with latest changes

1.3.1 release 2018-08-19
------------------------

  * Adapt to latest gpxpy 1.3.3
  * Fix bugs

1.3.0 release 2018-08-18
------------------------

This release renames class Activity to Track, and it renames Track.what
to Track.category. The latter means that .gpx files should be adjusted:
where the keywords now contain "What:", change that to "Category:".

  * new: Track.last_point() avoids having to iterate over the full list
  * new: gpxdo diff
  * gpxdo: bash completion if argcomplete is installed (pip install argcomplete).
    Put this into your .bashrc: eval "$(register-python-argcomplete gpxdo)"
    or see https://argcomplete.readthedocs.io/en/latest/
  * new in Track: speed(), moving_speed(), warnings()
  * gpxdo --long shows warnings about strange tracks
  * gpxdo --total
  * gpxdo set --help shows all legal categories
  * gpxdo ls: if no file/directory given, use "."
  * gpxdo: unify how backends/tracks are displayed. Remove leading "./" from names.
  * gpxdo --debug shows backtrace for errors
  * Backend.merge() now also accepts a single Track
  * Backend.diff() now accepts an Track, a Backend or a list of any of them on for both sides
  * GPSIES: workaround for sporadic bug in editTrack
  * Track.clone() does not pass id_in_backend anymore
  * Backend.scan() tries to keep known tracks
  * Backend.diff() now compares all attributes
  * new: Track.identifier() and Backend.identifier() and use them for better output in gpxdo
  * new: gpxdo set for setting/clearing any attributes
  * Track.add_keyword(): given a duplicate, silently ignore it
  * gpxdo kw now accepts a list of comma separated keywords
  * gpxdo: filter by keywords: --only-kw
  * gpxdo --last-date now includes that date
  * gpxdo --first-date and --last-date now also accept YYYY-MM and YYYY
  * gpxdo --date is new: specific date YYYY, YYYY-MM or YYYY-MM-DD
  * gpxdo --set --id-from-title is new
  * gpxdo --set --id-from-time is new
  * gpxdo --similar
  * new: Track.similarity(other)
  * gpxity now uses the python logging module for all output
  * gpxdo: replace --debug and --verbose by --loglevel
  * new backend Mailer
  * new: class Lifetrack
  * new: bin/gpxity_server. This is unfinished work, it is intended as a server for
    lifetracking.

1.2.6 release 2018-06-05
------------------------
  * utility for testing installation in a docker container
  * version number is not in the source anymore, setup.py creates version.py

1.2.2 release 2018-04-25
------------------------
  * gpxdo ls --long is no longer ignored
  * explicitly enforce utf-8 when reading or writing .gpx files
  * improve setup.py
  * require gpxpy 1.2.0


1.2.1 release 2018-04-17
------------------------
  * Backend has a new arg "timeout"
  * README has a link to readthedocs
  * Auth: added an example
  * Backend.sync_from is gone, there are now Track.merge() and Backend.merge()
  * diverse fixes for gpxdo
  * Track.what is now always in internal format
  * Simplify specific backend code by moving more code into the general Backend class
  * Track.dirty is gone, there now is Track.rewrite()
  * Backend: renamed save() to add()
  * Track.identifier is new, to be used by gpxdo
  * Track.length is the track length
  * gpxdo ls has many more options, including --sort
  * gpxdo rm has a new option --dry-run


1.2.0 release 2018-04-09
------------------------
  * New backend GPSIES for www.gpsies.com
  * New: Command line utility "gpxdo" exposing commands for listing, copying,
         merging, removing, editing, fixing, comparing
  * New class BackendDiff
  * Backend: rename copy_all_from to sync_from and add parameters
  * hide class Authenticate from public API
  * Define assumption about points having to be ordered by time
  * Do not use slow GPX.get_time_bounds()
  * Track.last_time now is a property
  * MMT: Map Track.keywords to MMT tags
  * Track.keywords now returns them sorted
  * MMT: login only once per backend instance
  * Make list(Track) sortable (by title)
  * New: Track.adjust_time()
  * Track: Improve __str__ and __repr__
  * Backend can now be used as an iterable
  * New class BackendDiff
  * MMT now supports life tracking
  * New generator Track.segments()
  * Simplify usage of auth.conf
  * fix illegal XML generated by gpxy for GPX 1.1
  * New: Backend.match implements client-side filtering
  * New: BackendException
  * New: Map values for "what" between different backends
  * New: Backend.legal_whats shows the values for "what" supported by a backend


1.1.2  release 2017-03-4
------------------------
  * a first example
  * simplify authentication
  * simplify Backend API
  * len(backend) is the number of tracks
  * Allow backend[x] and x in backend
  * hide Backend.tracks, directly add needed methods to Backend
  * MMT: Download track sometimes did not download the entire track
  * bin/test and bin/coverage now accept test method names (without `test_` prefix)
  * Directory: removes dead links without raising an exception
  * Track.description never returns None
  * Track: Parsing illegal GPX XML now prints a more helpful error message
  * Track.clone() first does load_full
  * Track(gpx=gpx) now handles keywords correctly
  * Backend.save() now accepts ident=str
  * Directory tries not to use illegal file names for symlinks

1.1.1  released 2017-02-26
--------------------------
  * Added Changelog

1.1.0  released 2017-02-26 
--------------------------
  * New backend ServerDirectory

1.0.1  released 2017-02-25
--------------------------
  * Documentation fixes

1.0.0  released 2017-02-25
--------------------------
  * Initial version supporting backends Directory and MMT



