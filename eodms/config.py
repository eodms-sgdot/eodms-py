import os
import ssl
from requests.packages import urllib3

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _resolve_staging_verify_ssl():
    """Return staging TLS verify setting from env vars, falling back to insecure mode."""
    for env_name in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        ca_bundle = os.environ.get(env_name)
        if ca_bundle:
            return ca_bundle
    return False


def get_domain_config(environment='prod'):
    """
    Get domain configuration based on environment.
    
    :param environment: Environment type ('prod' or 'staging')
    :return: Dictionary with 'domain', 'verify_ssl' keys
             verify_ssl may be bool or CA bundle path.
    """
    
    if environment == 'staging':
        return {
            'domain': os.environ['EODMS_STAGING_DOMAIN'],
            # Use CA bundle env vars when available; otherwise retain legacy staging behavior.
            'verify_ssl': _resolve_staging_verify_ssl(),
        }
    else:
        return {
            'domain': "https://www.eodms-sgdot.nrcan-rncan.gc.ca",
            # Explicitly keep prod verification deterministic and independent of CA env vars.
            'verify_ssl': True
        }
