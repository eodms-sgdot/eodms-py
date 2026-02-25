import requests
from requests.packages import urllib3
import ssl
import os
import json
# import time
from datetime import datetime, timedelta
import dateparser
from . import api_logger
from .__version__ import __version__
from . import config

class AAA_Creds():

    def __init__(self):

        self.access_token = None
        self.refresh_token = None
        self.access_exp = None
        self.refresh_exp = None
        self.access_seconds = None
        self.refresh_seconds = None

        self.cred_fn = None

        self.logger = api_logger.EODMSLogger('eodms_aaa', api_logger.eodms_logger)

    def get_json(self, with_seconds=False):
        """
        Gets a JSON of the credentials
        """

        access_str = self.access_exp
        if isinstance(access_str, datetime):
            access_str = access_str.isoformat()

        refresh_str = self.refresh_exp
        if isinstance(refresh_str, datetime):
            refresh_str = refresh_str.isoformat()

        out_json = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expiration": access_str,
            "refresh_expiration": refresh_str
        }

        if with_seconds:
            out_json['access_seconds'] = self.access_seconds
            out_json['refresh_seconds'] = self.refresh_seconds

        return out_json
    
    def set_vals(self, **kwargs):
        """
        Sets one or multiple variables.

        :param kwargs:
            - access_token
            - refresh_token
            - access_exp
            - refresh_exp
            - access_seconds
            - refresh_seconds
        """

        if kwargs.get('access_token') is not None:
            self.logger.info("Updating Access Token...")
            self.access_token = kwargs.get('access_token')

        if kwargs.get('refresh_token') is not None:
            self.logger.info("Updating Refresh Token...")
            self.refresh_token = kwargs.get('refresh_token')

        if kwargs.get('access_exp') is not None:
            dt = kwargs.get('access_exp')
            self.logger.info(f"Updating Access Expiration as {dt}...")
            self.access_exp = dt

        if kwargs.get('refresh_exp') is not None:
            dt = kwargs.get('refresh_exp')
            self.logger.info(f"Updating Refresh Expiration as {dt}...")
            self.refresh_exp = dt

        if kwargs.get('access_seconds') is not None:
            self.access_seconds = kwargs.get('access_seconds')

        if kwargs.get('refresh_seconds') is not None:
            self.refresh_seconds = kwargs.get('refresh_seconds')

    def set_fn(self, fn):
        """
        Sets the aaa_creds.json path.
        """

        self.cred_fn = fn

    def get_access_exp(self, as_dt=True):
        """
        Returns the Access Token expiration time.

        :param as_dt: Determines whether to return the time as a datetime.
        :type  as_dt: boolean
        """

        if as_dt:
            return dateparser.parse(self.access_exp)
        
        return self.access_exp
    
    def get_refresh_exp(self, as_dt=True):
        """
        Returns the Refresh Token expiration time.

        :param as_dt: Determines whether to return the time as a datetime.
        :type  as_dt: boolean
        """

        if as_dt:
            return dateparser.parse(self.refresh_exp)
        
        return self.refresh_exp

    def export_vals(self):
        """
        Exports the credential values to the aaa_creds.json file.
        """

        with open(self.cred_fn, 'w') as f:
            json.dump(self.get_json(), f)

        return self.cred_fn

    def import_vals(self):
        """
        Imports the credential values from the aaa_creds.json file.
        """

        if not os.path.exists(self.cred_fn):
            return None

        try:
            with open(self.cred_fn, 'r') as file:
                creds = json.load(file)
        except:
            return None

        self.access_token = creds.get('access_token')
        self.refresh_token = creds.get('refresh_token')
        
        access_exp_str = creds.get('access_expiration')
        refresh_exp_str = creds.get('refresh_expiration')

        self.access_exp = datetime.fromisoformat(access_exp_str)
        self.refresh_exp = datetime.fromisoformat(refresh_exp_str) \
                            if refresh_exp_str is not None else datetime.now()

        self.logger.info(f"Access Expiration: {self.access_exp}")
        self.logger.info(f"Refresh Expiration: {self.refresh_exp}")

class AAA_API():

    def __init__(self, username, password, environment='prod'):
        """
        Initializes the AAA_API instance.
        :param username: EODMS username
        :param password: EODMS password
        :param environment: Environment to use ('prod' or 'staging')
        """

        self.aaa_creds = AAA_Creds()
        self.logger = api_logger.EODMSLogger('eodms_aaa', api_logger.eodms_logger)

        self.username = username
        self.password = password

        domain_config = config.get_domain_config(environment)
        self.domain = domain_config['domain']
        self.verify_ssl = domain_config.get('verify_ssl', True)

        user_folder = os.path.expanduser('~')
        self.auth_folder = os.path.join(user_folder, '.eodms')
        self.aaa_creds.set_fn(os.path.join(self.auth_folder, f'aaa_creds.{self.username}.{environment}.json'))

        if not os.path.exists(self.auth_folder):
            os.makedirs(self.auth_folder)

        self.login_success = True
        self.response = None

    def get_access_token(self):
        """
        Gets a new Access Token using either an existing Access Token, 
            the "refresh" endpoint or "login"
            depending on the expiration dates of the current tokens.

        Ex:
            - existing Access Token if both tokens have not expired
            - "refresh" if the Access Token has expired but the Refresh
                Token has not
            - "logging" if both tokens have expired
        """

        self.aaa_creds.import_vals()

        if self.aaa_creds.access_token is None:
            self.logger.info("No existing Access Token found. Logging in...")
            self._login()
            return self.aaa_creds.access_token

        now_dt = datetime.now()
        access_exp = self.aaa_creds.access_exp
        refresh_exp = self.aaa_creds.refresh_exp

        if now_dt >= access_exp and now_dt >= refresh_exp:
            self.logger.info("Current Refresh Token has expired. "
                        "Getting new Tokens...")

            # Get a new token
            self._login()
        elif now_dt >= access_exp and now_dt < refresh_exp:
            self.logger.info("Current Access Token has expired. "
                  "Getting a new Access Token using current Refresh Token...")

            self._refresh()

        if not self.login_success:
            self.logger.warning("WARNING: Could not access current AAA "
                  f"session with existing tokens in {self.aaa_creds.cred_fn}")
            
        # self._print_response()

        return self.aaa_creds.access_token
    
    def prepare_request(self, url, method='GET', **kwargs):

        req = requests.Request(method, url, **kwargs)
        
        prepared = req.prepare()
        
        # Send the request
        session = requests.Session()
        session.trust_env = False
        response = session.send(prepared, verify=self.verify_ssl)

        #self.logger.info(f"response headers: {response.request.headers}")

        return response

    def _print_response(self):
        log_str = "AAA Response Info:"

        if self.response is None:
            log_str += "\n  N/A"
        else:
            for k, v in self.response.items():
                log_str += f"\n  {k}: {v}"

        self.logger.debug(log_str)

    def _update_tokens(self, **kwargs):

        # Determine the expiration times
        refresh_time = self.response.get('refresh_token_expires_in') - 180
        access_time = self.response.get('expires_in') - 120
        now_dt = datetime.now()
        self.access_exp = now_dt + timedelta(seconds=access_time)
        self.refresh_exp = now_dt + timedelta(seconds=refresh_time)

        kwargs["access_exp"] = self.access_exp
        kwargs["refresh_exp"] = self.refresh_exp
        kwargs["access_seconds"] = self.response.get('refresh_token_expires_in')
        kwargs["refresh_seconds"] = self.response.get('expires_in')

        # self.aaa_creds.set_vals(access_exp=self.access_exp,
        #                         refresh_exp=self.refresh_exp)
        
        self.aaa_creds.set_vals(**kwargs)    
        self.aaa_creds.export_vals()

    def _login(self):
        """
        Starts a new session using the "login" endpoint of the AAA API 
            and gets the Access Token.
        """

        url = f"{self.domain}/aaa/v1/login"

        payload = {
            "grant_type": "password",
            "password": self.password,
            "username": self.username
        }

        #self.logger.info(f"Logging into {url} (user {self.username} pass {self.password})...")

        # resp = requests.post(url, json=payload, trust_env=False, verify=False) #, verify=False)
        resp = self.prepare_request(url, "POST", json=payload)

        if resp.status_code == 200:
            self.logger.info("Successfully logged in using AAA API")

            self.response = resp.json()

            new_access_token = self.response.get('access_token')
            new_refresh_token = self.response.get('refresh_token')
            # new_access_exp = self.access_exp.isoformat()

            # try:
            #     new_refresh_exp = self.refresh_exp.isoformat()
            # except:
            #     new_refresh_exp = ""

            self._update_tokens(access_token=new_access_token,
                                refresh_token=new_refresh_token)

            self.login_success = True

        else:
            err_json = resp.json()
            error = err_json.get('error')
            msg = err_json.get('message')
            self.logger.warning(f"WARNING: Failed to log in using "
                  f"AAA API: {error}: {msg}")
            self.login_success = False

            if resp.status_code == 429:
                self.logger.info("Attempting to get new Access Token "
                      "using existing Refresh Token...")
                self._refresh()

    def _refresh(self):
        """
        Gets a new Access Token using an existing Refresh Token 
            and the "refresh" endpoint of the AAA API.
        """

        url = f"{self.domain}/aaa/v1/refresh"

        # resp = requests.get(url, verify=False)

        headers = {"Authorization": f"Bearer {self.aaa_creds.refresh_token}"}
        resp = self.prepare_request(url, headers=headers)

        if resp.status_code == 200:
            self.logger.info("Successfully refreshed using AAA API")
            self.response = resp.json()

            new_access_token = self.response.get('access_token')
            new_refresh_token = self.response.get('refresh_token')

            self._update_tokens(access_token=new_access_token,
                                refresh_token=new_refresh_token)

            self.login_success = True
        else:
            err_json = resp.json()
            error = err_json.get('error')
            msg = err_json.get('message')
            self.logger.error("WARNING: Failed to refresh using "
                  f"AAA API: {error}: {msg}")
            self.login_success = False


        