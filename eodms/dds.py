import os
import requests
from requests.packages import urllib3
from tqdm.auto import tqdm
import ssl
from urllib.parse import unquote
from urllib.parse import urlparse, parse_qs


from . import aaa
from . import api_logger
from . import config
from .errors import DDSError

class DDS_API():
    """Client for the EODMS Data Delivery Service (DDS) API."""
    
    def __init__(self, aaa_api, environment='prod'):
        domain_config = config.get_domain_config(environment)
        self.domain = domain_config['domain']
        self.verify_ssl = domain_config.get('verify_ssl', True)
        self.img_info = None

        self.logger = api_logger.EODMSLogger('eodms_logger', api_logger.eodms_logger)

        # self.logger.debug((f"ssl.get_server_certificate(): {ssl.get_server_certificate(self.domain)}"))

        self.aaa = aaa_api

        # self.login_info = self.aaa.login()

    def get_item(self, collection, item_uuid, catalog="EODMS"):

        url = f"{self.domain}/dds/v1/item/{catalog}/{collection}/{item_uuid}"

        access_token = self.aaa.get_access_token()
        if not access_token:
            raise DDSError("DDS access token unavailable.")
        headers = {"Authorization": f"Bearer {access_token}"}
        # resp = requests.get(url, headers=headers, trust_env=False, verify=False)
        resp = self.aaa.prepare_request(url, headers=headers)

        if resp.status_code == 200:
            self.logger.info(f"Successfully got item {collection}/{item_uuid}")
            try:
                self.img_info = resp.json()
            except Exception as exc:
                resp_text = resp.text or ""
                if resp_text.lstrip().upper().startswith('<HTML>'):
                    raise DDSError("DDS API returned HTML instead of JSON.") from exc
                raise DDSError("DDS API returned invalid JSON.") from exc
        elif resp.status_code == 202:
            try:
                self.img_info = resp.json()
            except Exception as exc:
                raise DDSError("DDS API returned invalid JSON for accepted item response.") from exc
            status = self.img_info.get('status')
            self.logger.info(f"{collection}/{item_uuid} is being prepared; current"
                  f"status is {status}.")
        else:
            try:
                err_json = resp.json()
                self.logger.error(err_json)
                self.logger.error(f"Failed to get {collection}/{item_uuid}\n")
                raise DDSError(
                    f"Failed to get {collection}/{item_uuid}: {err_json}"
                )
            except ValueError as exc:
                self.logger.error("Failed to get item using DDS API\n")
                raise DDSError(
                    f"Failed to get {collection}/{item_uuid}: HTTP {resp.status_code} {resp.text}"
                ) from exc

        return self.img_info

    def download_item(self, out_folder) -> str:
        """
        Downloads the item to the specified folder.
        Returns the filename (full path).
        """

        if self.img_info is None:
            self.logger.error("No image info available.\n")
            raise DDSError("No image info available for download.")

        download_url = self.img_info.get('download_url')

        if not download_url:
            raise DDSError("DDS item response does not include a download URL.")

        url_parsed = urlparse(download_url)
        dest_fn = os.path.join(out_folder, os.path.basename(url_parsed.path))

        self.logger.info(f"Downloading image to {dest_fn}...\n")

        headers = self.aaa.get_default_headers()
        self.logger.debug(
            f"Outbound User-Agent: {headers.get('User-Agent')}"
        )

        def _as_positive_int(value):
            if value is None:
                return None
            try:
                parsed = int(str(value).strip())
            except (TypeError, ValueError):
                return None
            if parsed > 0:
                return parsed
            return None

        total_bytes = None
        for key in ("size", "file_size", "bytes", "filesize", "content_length"):
            total_bytes = _as_positive_int(self.img_info.get(key))
            if total_bytes is not None:
                break

        req = requests.Request("GET", download_url, headers=headers)
        prepared = req.prepare()
        session = requests.Session()
        proxies = requests.utils.get_environ_proxies(prepared.url)

        with session.send(
            prepared,
            stream=True,
            verify=self.verify_ssl,
            proxies=proxies,
        ) as stream:
            stream.raise_for_status()

            if total_bytes is None:
                total_bytes = _as_positive_int(stream.headers.get('Content-Length'))

            if total_bytes is not None:
                self.logger.debug(f"DDS download size detected: {total_bytes} bytes")
            else:
                self.logger.debug("DDS download size unavailable; progress total/ETA disabled")

            with open(dest_fn, 'wb') as pipe:
                with tqdm(
                    total=total_bytes,
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                    miniters=1,
                    desc=os.path.basename(dest_fn),
                ) as pbar:
                    for chunk in stream.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        pipe.write(chunk)
                        pbar.update(len(chunk))

        return dest_fn
