import requests
from requests.packages import urllib3
import ssl
import os
import json
import time
# import time
from datetime import datetime, timedelta
import dateparser
from . import api_logger
from .__version__ import __version__
from . import config
from .errors import AAAError

class AAA_Creds():
    """Authentication Authorization and Accounting (AAA) credentials management class."""
    def __init__(self):

        self.access_token = None
        self.refresh_token = None
        self.access_exp = None
        self.refresh_exp = None
        self.access_seconds = None
        self.refresh_seconds = None

        self.cred_fn = None

        self.logger = api_logger.EODMSLogger('eodms_aaa', api_logger.get_logger('aaa'))

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

        # Write atomically so other processes never read a partially-written token file.
        tmp_fn = f"{self.cred_fn}.tmp.{os.getpid()}"
        with open(tmp_fn, 'w') as f:
            json.dump(self.get_json(), f)
        os.replace(tmp_fn, self.cred_fn)

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


        # self.logger.info(f"Access Expiration: {self.access_exp}")
        # self.logger.info(f"Refresh Expiration: {self.refresh_exp}")

class AAA_API():

    def __init__(self, username, password, environment='prod'):
        """
        Initializes the AAA_API instance.
        :param username: EODMS username
        :param password: EODMS password
        :param environment: Environment to use ('prod' or 'staging')
        """

        self.aaa_creds = AAA_Creds()
        self.logger = api_logger.EODMSLogger('eodms_aaa', api_logger.get_logger('aaa'))

        self.username = username
        self.password = password

        domain_config = config.get_domain_config(environment)
        self.domain = domain_config['domain']
        self.verify_ssl = domain_config.get('verify_ssl', True)

        user_folder = os.path.expanduser('~')
        self.auth_folder = os.path.join(user_folder, '.eodms')
        self.aaa_creds.set_fn(os.path.join(self.auth_folder, f'aaa_creds.{self.username}.{environment}.json'))
        self._token_lock_fn = f"{self.aaa_creds.cred_fn}.lock"
        self._token_lock_timeout = 30
        self._token_lock_poll_interval = 0.2
        self._token_lock_stale_seconds = 120

        if not os.path.exists(self.auth_folder):
            os.makedirs(self.auth_folder, exist_ok=True)

        self.login_success = True
        self.response = None
        self.last_error = None

    def _acquire_token_lock(self):
        """Acquire an inter-process lock for token refresh/login operations."""

        started = time.time()

        while True:
            try:
                fd = os.open(self._token_lock_fn, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, 'w') as lock_file:
                    lock_file.write(f"pid={os.getpid()} created={datetime.now().isoformat()}\n")
                return True
            except FileExistsError:
                try:
                    mtime = os.path.getmtime(self._token_lock_fn)
                    lock_age = time.time() - mtime
                    if lock_age > self._token_lock_stale_seconds:
                        self.logger.warning(
                            "Detected stale AAA token lock; removing it. "
                            f"lock_file={self._token_lock_fn} age_seconds={lock_age:.1f}"
                        )
                        os.remove(self._token_lock_fn)
                        continue
                except FileNotFoundError:
                    # Lock released between checks; retry immediately.
                    continue
                except OSError:
                    pass

                if time.time() - started >= self._token_lock_timeout:
                    self.logger.error(
                        "Timed out waiting for AAA token lock. "
                        f"lock_file={self._token_lock_fn} timeout_seconds={self._token_lock_timeout}"
                    )
                    self._record_error("Timed out waiting for AAA token lock.")
                    return False

                time.sleep(self._token_lock_poll_interval)

    def _release_token_lock(self):
        """Release the inter-process token lock."""

        try:
            os.remove(self._token_lock_fn)
        except FileNotFoundError:
            pass
        except OSError as e:
            self.logger.warning(
                "Failed to remove AAA token lock file. "
                f"lock_file={self._token_lock_fn} error={e}"
            )

    @staticmethod
    def _token_tail(token, tail_len=8):
        """Return a safe token fingerprint for logs without exposing full token."""
        if not token:
            return "none"
        token_str = str(token)
        if len(token_str) <= tail_len:
            return token_str
        return token_str[-tail_len:]

    @staticmethod
    def _fmt_dt(dt_val):
        if dt_val is None:
            return "none"
        if hasattr(dt_val, "isoformat"):
            return dt_val.isoformat()
        return str(dt_val)

    def _record_error(self, message, status_code=None):
        self.last_error = AAAError(message, status_code=status_code)
        self.login_success = False

    @staticmethod
    def _response_preview(resp, max_len=250):
        """Return concise response details for logging/debugging."""
        if resp is None:
            return "response=N/A"

        content_type = resp.headers.get('Content-Type', 'unknown')
        body = (resp.text or '').strip().replace("\n", " ")
        if len(body) > max_len:
            body = f"{body[:max_len]}..."

        return (
            f"status={resp.status_code}, content_type={content_type}, "
            f"body_preview={body!r}"
        )

    def _safe_json(self, resp, context):
        """Parse response JSON without raising if server returns invalid content."""
        try:
            return resp.json()
        except ValueError as e:
            self.logger.error(
                f"{context}: invalid JSON from AAA server ({e}). "
                f"{self._response_preview(resp)}"
            )
            return None

    @staticmethod
    def _default_user_agent():
        """Build package User-Agent suffix on top of requests default."""
        return f"{requests.utils.default_user_agent()} eodms-py/{__version__}"

    def _build_user_agent(self, custom_user_agent=None):
        default_ua = self._default_user_agent()

        if not custom_user_agent:
            return default_ua

        if f"eodms-py/{__version__}" in custom_user_agent:
            return custom_user_agent

        return f"{custom_user_agent} eodms-py/{__version__}"

    def get_default_headers(self, headers=None):
        """Return request headers with User-Agent populated."""
        out_headers = dict(headers or {})
        out_headers["User-Agent"] = self._build_user_agent(
            out_headers.get("User-Agent")
        )
        return out_headers

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
        if not self._acquire_token_lock():
            return None

        try:
            # Re-read under lock so only one process decides whether to login/refresh.
            self.aaa_creds.import_vals()

            self.logger.info(
                "AAA token state before decision: "
                f"access_present={bool(self.aaa_creds.access_token)} "
                f"refresh_present={bool(self.aaa_creds.refresh_token)} "
                f"access_exp={self._fmt_dt(self.aaa_creds.access_exp)} "
                f"refresh_exp={self._fmt_dt(self.aaa_creds.refresh_exp)} "
                f"creds_file={self.aaa_creds.cred_fn}"
            )

            if self.aaa_creds.access_token is None:
                self.logger.info("AAA token decision=login reason=no_access_token")
                self._login()
                return self.aaa_creds.access_token

            now_dt = datetime.now()
            access_exp = self.aaa_creds.access_exp
            refresh_exp = self.aaa_creds.refresh_exp

            if now_dt >= access_exp and now_dt >= refresh_exp:
                self.logger.info(
                    "AAA token decision=login reason=access_and_refresh_expired "
                    f"now={self._fmt_dt(now_dt)}"
                )

                # Get a new token
                self._login()
            elif now_dt >= access_exp and now_dt < refresh_exp:
                self.logger.info(
                    "AAA token decision=refresh reason=access_expired_refresh_valid "
                    f"refresh_tail={self._token_tail(self.aaa_creds.refresh_token)} "
                    f"refresh_exp={self._fmt_dt(refresh_exp)}"
                )

                self._refresh()
            else:
                self.logger.info(
                    "AAA token decision=reuse_cached_access reason=token_still_valid "
                    f"access_tail={self._token_tail(self.aaa_creds.access_token)} "
                    f"access_exp={self._fmt_dt(access_exp)}"
                )

            if not self.login_success:
                self.logger.error("Could not access current AAA "
                    f"session with existing tokens in {self.aaa_creds.cred_fn}")
                return None

            return self.aaa_creds.access_token
        finally:
            self._release_token_lock()
    
    def prepare_request(self, url, method='GET', **kwargs):

        kwargs['headers'] = self.get_default_headers(kwargs.get('headers'))
        self.logger.debug(
            f"Outbound User-Agent: {kwargs['headers'].get('User-Agent')}"
        )

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
        try:
            resp = self.prepare_request(url, "POST", json=payload)
        except Exception as e:
            self.logger.error(f"AAA login request failed: {e}")
            self._record_error(f"AAA login request failed: {e}")
            return

        if resp.status_code == 200:
            self.logger.info("Successfully logged in using AAA API")

            self.response = self._safe_json(resp, "AAA login response parse error")
            if not isinstance(self.response, dict):
                self.logger.error("AAA login returned an unexpected response format; cannot update tokens.")
                self._record_error("AAA login returned an unexpected response format.", status_code=resp.status_code)
                return

            new_access_token = self.response.get('access_token')
            new_refresh_token = self.response.get('refresh_token')
            if not new_access_token or not new_refresh_token:
                self.logger.error(
                    "AAA login response missing access_token or refresh_token. "
                    f"{self._response_preview(resp)}"
                )
                self._record_error("AAA login response missing access_token or refresh_token.", status_code=resp.status_code)
                return
            # new_access_exp = self.access_exp.isoformat()

            # try:
            #     new_refresh_exp = self.refresh_exp.isoformat()
            # except:
            #     new_refresh_exp = ""

            self._update_tokens(access_token=new_access_token,
                                refresh_token=new_refresh_token)

            self.login_success = True
            self.last_error = None

        else:
            err_json = self._safe_json(resp, "AAA login error response parse error") or {}
            error = err_json.get('error', 'unknown_error')
            msg = err_json.get('message', 'No message returned')
            failure_message = f"Login failed for user {self.username} using AAA API: {error}: {msg}"
            self.logger.error(f"Login failed for user {self.username} using "
                  f"AAA API: {error}: {msg}")
            self.logger.error(f"AAA login failure details: {self._response_preview(resp)}")
            self._record_error(failure_message, status_code=resp.status_code)

            if resp.status_code == 429:
                self.logger.warning(
                    "AAA login returned 429; attempting refresh fallback. "
                    f"refresh_token_present={bool(self.aaa_creds.refresh_token)} "
                    f"refresh_tail={self._token_tail(self.aaa_creds.refresh_token)}"
                )
                self._refresh()

    def _refresh(self):
        """
        Gets a new Access Token using an existing Refresh Token 
            and the "refresh" endpoint of the AAA API.
        """

        url = f"{self.domain}/aaa/v1/refresh"

        # resp = requests.get(url, verify=False)

        self.logger.info(
            "AAA refresh attempt: "
            f"refresh_token_present={bool(self.aaa_creds.refresh_token)} "
            f"refresh_tail={self._token_tail(self.aaa_creds.refresh_token)}"
        )

        headers = {"Authorization": f"Bearer {self.aaa_creds.refresh_token}"}
        try:
            resp = self.prepare_request(url, headers=headers)
        except Exception as e:
            self.logger.error(f"AAA refresh request failed: {e}")
            self._record_error(f"AAA refresh request failed: {e}")
            return

        if resp.status_code == 200:
            self.logger.info("Successfully refreshed using AAA API")
            self.response = self._safe_json(resp, "AAA refresh response parse error")
            if not isinstance(self.response, dict):
                self.logger.error("AAA refresh returned an unexpected response format; cannot update tokens.")
                self._record_error("AAA refresh returned an unexpected response format.", status_code=resp.status_code)
                return

            new_access_token = self.response.get('access_token')
            new_refresh_token = self.response.get('refresh_token')
            if not new_access_token or not new_refresh_token:
                self.logger.error(
                    "AAA refresh response missing access_token or refresh_token. "
                    f"{self._response_preview(resp)}"
                )
                self._record_error("AAA refresh response missing access_token or refresh_token.", status_code=resp.status_code)
                return

            self._update_tokens(access_token=new_access_token,
                                refresh_token=new_refresh_token)

            self.login_success = True
            self.last_error = None
        else:
            err_json = self._safe_json(resp, "AAA refresh error response parse error") or {}
            error = err_json.get('error', 'unknown_error')
            msg = err_json.get('message', 'No message returned')
            failure_message = f"Failed to refresh using AAA API: {error}: {msg}"
            self.logger.error("Failed to refresh using "
                  f"AAA API: {error}: {msg}")
            self.logger.error(f"AAA refresh failure details: {self._response_preview(resp)}")
            self._record_error(failure_message, status_code=resp.status_code)


        