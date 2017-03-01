Changelog
=========

1.1.2
-----
  * MMT: Download activity sometimes did not download the entire track
  * bin/test and bin/coverage now accept test method names (without test_ prefix)
  * Directory: removes dead links without raising an exception
  * Activity.description never returns None
  * Activity: Parsing illegal GPX XML now prints a more helpful error message
  * Activity.clone() first does load_full
  * Activity(gpx=gpx) now handles keywords correctly
  * Backend.save() now accepts ident=str
  * Directory tries not to use illegal file names for symlinks

1.1.1
-----
Released 2017-02-26
  * Added Changelog

1.1.0  
-----
Released 2017-02-26 
  * New backend ServerDirectory

1.0.1
-----
Released 2017-02-25
  * Documentation fixes

1.0.0
-----
Released 2017-02-25
  * Initial version supporting backends Directory and MMT



