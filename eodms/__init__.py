__title__ = 'py-eodms-dds'
__name__ = 'eodms_dds'
__author__ = 'Kevin Ballantyne'
__copyright__ = 'Copyright (c) His Majesty the King in Right of Canada, ' \
                'as represented by the Minister of Natural Resources, 2025'
__license__ = 'MIT License'
__description__ = 'A Python package to access the EODMS DDS API service.'
__maintainer__ = 'Kevin Ballantyne'
__email__ = 'eodms-sgdot@nrcan-rncan.gc.ca'

from .__version__ import __version__
from .aaa import AAA_API
from .dds import DDS_API
from . import config