import os
import ssl
from requests.packages import urllib3

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_domain_config(environment='prod'):
    """
    Get domain configuration based on environment.
    
    :param environment: Environment type ('prod' or 'staging')
    :return: Dictionary with 'domain', 'verify_ssl' keys
    """
    
    if environment == 'staging':
        eodms_dir = os.path.expanduser('~/.eodms')

        return {
            'domain': os.environ['EODMS_STAGING_DOMAIN'],
            #'ssl_cert_path': ssl_cert_path,
            'verify_ssl': False  # Disable SSL verification for staging
        }
    else:
        return {
            'domain': "https://www.eodms-sgdot.nrcan-rncan.gc.ca",
            'verify_ssl': True
        }
