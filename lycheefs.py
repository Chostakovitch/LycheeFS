#!/usr/bin/env python
# coding=utf-8
"""
# lycheefs: a FUSE-based filesystem for Lychee, a photo management system.

For additonal information, visit :
- [Lychee](https://github.com/LycheeOrg/Lychee)
- [lycheefs](https://github.com/Chostakovitch/LycheeFS)
"""

# Skeleton taken from this example : https://github.com/libfuse/python-fuse/blob/master/example/xmp.py
import configparser
import fuse
import logging
import os, errno, stat, sys
from datetime import datetime
from fuse import Fuse
from pychee import pychee

if not hasattr(fuse, '__version__'):
    raise RuntimeError("your fuse-py doesn't know of fuse.__version__, probably it's too old.")

fuse.fuse_python_api = (0, 2)
fuse.feature_assert('stateful_files', 'has_init')

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%d-%b-%y %H:%M:%S')

class LycheeFS(Fuse):
    _URL_KEY = 'url'
    _USER_KEY = 'user'
    _PASSWORD_KEY = 'password'

    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        # In examples, this is done in main, but I don't understand why.
        # I think this is better to tie this in __init__
        self.version = "%prog " + fuse.__version__ + ", pychee " + str(pychee.__version__)
        self.usage = "Exposes a Lychee server as a Filesystem in USErspace." + Fuse.fusage
        self.dash_s_do = "setsingle"
        # Add parser options to get Lychee URL and optional credentials
        self.parser.add_option('-c', '--config', metavar="FILE",
                                 help="path to the configuration file [default: %default]",
                                 default="settings.ini")
        self.parser.add_option('-i', '--instance', metavar="INSTANCE",
                                 help="section to use in the configuration file [default: first section of configuration]")
        options = self.parse(values=self, errex=1)

        # Exit if help is printed anyway
        if options.modifiers['showhelp'] == True:
            sys.exit(0)

        if not hasattr(self, 'config'):
            self.config = 'settings.ini'
            logging.info(f'config not specified, use default configuration file : {self.config}.')
        # As per examples (such as https://github.com/libfuse/python-fuse/blob/master/example/xmp.py),
        # __init__ should be the method to setup filesystem.
        self._create_lychee_session()

        # Use path instead of ids to make things readable,
        # ignore duplicates for now, and store name <=> id
        # because API uses id and we only get the path eg in readir
        self.album_path_id = {}
        self.path_stats = {}
        self.photo_path_id = {}
        #TODO maybe do this less dirty - this is used as a cache
        # when a file is first opened. Maybe use a dedicated library
        # which handles cache and remove unused one after some time,
        # to avoid filling memory for large Lychee instances
        self.photo_path_bytes = {}

    def getattr(self, path):
        if path in self.path_stats:
            return self.path_stats[path]
        st = fuse.Stat()
        st.st_uid = os.getuid()
        st.st_gid = os.getgid()
        # path is a directory (album or root)
        if path == '/' or path in self.album_path_id:
            st.st_mode = stat.S_IFDIR | 0o755
            st.st_nlink = 2
        # path is a file (image)
        elif path in self.photo_path_id:
            photo_id = self.photo_path_id[path]
            photo_info = self.client.get_photo(photo_id)
            creation_date = datetime.strptime(photo_info['created_at'], "%Y-%m-%dT%H:%M:%S%z")
            mod_date = datetime.strptime(photo_info['updated_at'], "%Y-%m-%dT%H:%M:%S%z")
            st.st_mode = stat.S_IFREG | 0o444
            st.st_nlink = 1
            st.st_size = photo_info['filesize']
            st.st_ctime = datetime.timestamp(creation_date)
            st.st_mtime = datetime.timestamp(mod_date)
            st.st_atime = datetime.timestamp(datetime.now())
            self.path_stats[path] = st
        # path does not exists
        else:
            return -errno.ENOENT
        return st

    #TODO check what to do with offset
    #TODO fix very bad handling of path - if anyone knows a path
    #previous to browse from root
    def readdir(self, path, offset):
        dirs = []
        files = []
        if path == '/':
            # Root is only made of albums (no images)
            # Also there is smart albums, eg recent or favorite.
            # Not sure what I will do with them, eg what should a
            # cut/paste into favorite album should do ?...
            albums = self.client.get_albums()
            dirs.extend([v for (k, v) in albums['smartalbums'].items()])
            dirs.extend(albums['albums'])
            dirs.extend(albums['shared_albums'])
        else:
            album = self.client.get_album(self.album_path_id[path])
            dirs.extend(album.get('albums', []))
            files.extend(album.get('photos', []))
        for d in dirs:
            self.album_path_id[os.path.join(path, d['title'])] = d['id']
            yield fuse.Direntry(d['title'], type=stat.S_IFDIR)
        for f in files:
            self.photo_path_id[os.path.join(path, f['title'])] = f['id']
            yield fuse.Direntry(f['title'], type=stat.S_IFREG)

    def open(self, path, flags):
        if path in self.photo_path_bytes:
            return
        if path not in self.photo_path_id:
            return -errno.ENOENT
        accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
        if (flags & accmode) != os.O_RDONLY:
            return -errno.EACCES
        photo_id = self.photo_path_id[path]
        # Download full-quality photo
        #TODO allow to control this by a CLI option,
        # but probably don't try to optimize anything ourselves
        photo_bytes = self.client.get_photos_archive([photo_id], 'FULL')
        self.photo_path_bytes[path] = photo_bytes

    def read(self, path, size, offset):
        # not useful now but will be for cache miss
        if path not in self.photo_path_id:
            return -errno.ENOENT

        photo = self.photo_path_bytes[path]
        photo_len = len(photo)
        if offset < photo_len:
            if offset + size > photo_len:
                size = photo_len - offset
            buf = photo[offset:offset + size]
        else:
            buf = b''
        return buf

    def _create_lychee_session(self):
        # Read configuration file
        instances = configparser.ConfigParser()
        instances.read(self.config)

        # Get suitable Lychee instance configuration
        if not hasattr(self, 'instance') and len(instances.sections()) > 0:
            self.instance = instances.sections()[0]
            logging.info(f'instance not specified, use first instance found : {self.instance}.')
        else:
            logging.error('instance is mandatory !\n')
            self.parser.print_help()
            sys.exit(1)

        if self.instance not in instances.sections():
            logging.error(f'instance {self.instance} not found in configuration.')
            sys.exit(1)

        # Get Lychee instance URL
        if not instances.has_option(self.instance, self._URL_KEY):
            logging.error(f'url is mandatory for instance {self.instance}.')
            sys.exit(1)
        host = instances.get(self.instance, self._URL_KEY)

        # This is the API client for the given URL
        logging.info(f'initializing connection to {host}...')
        self.client = pychee.LycheeClient(host)

        # Optional connection to access private albums and upload files
        if instances.has_option(self.instance, self._USER_KEY) and instances.has_option(self.instance, self._PASSWORD_KEY):
            logging.info(f'user and password found, logging to {host}...')
            user = instances.get(self.instance, self._USER_KEY)
            password = instances.get(self.instance, self._PASSWORD_KEY)
            self.client.login(user, password)

def main():
    fuse = LycheeFS()
    fuse.main()

if __name__ == '__main__':
    main()
