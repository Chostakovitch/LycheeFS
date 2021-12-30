#!/usr/bin/env python
# coding=utf-8
"""
# lychee_fuse: a FUSE-based filesystem for Lychee, a photo management system.

For additonal information, visit :
- [Lychee](https://github.com/LycheeOrg/Lychee)
- [lychee-fuse](https://github.com/Chostakovitch/lychee-fuse)
"""

# Skeleton taken from this example : https://github.com/libfuse/python-fuse/blob/master/example/xmp.py
import configparser
import fuse
import logging
import sys
from fuse import Fuse
from pychee import pychee

if not hasattr(fuse, '__version__'):
    raise RuntimeError("your fuse-py doesn't know of fuse.__version__, probably it's too old.")

fuse.fuse_python_api = (0, 2)
fuse.feature_assert('stateful_files', 'has_init')

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%d-%b-%y %H:%M:%S')

class Lychee(Fuse):
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

    def _create_lychee_session(self):
        instances = configparser.ConfigParser()
        instances.read(self.config)
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
    fuse = Lychee()
    fuse.main()

if __name__ == '__main__':
    main()
