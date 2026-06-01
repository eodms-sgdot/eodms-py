import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from tqdm.auto import tqdm

from . import api_logger
from . import config
from .__version__ import __version__
from .errors import ProcessingError


class Processes_API:
    """Client for the EODMS OGC Processes API."""

    TERMINAL_STATES = {"successful", "failed", "dismissed"}

    def __init__(self, aaa_api=None, environment='prod'):
        domain_config = config.get_domain_config(environment)
        self.domain = domain_config['domain']
        self.verify_ssl = domain_config.get('verify_ssl', True)
        self.api_url = f"{self.domain}/processing"

        self.aaa = aaa_api
        self.logger = api_logger.EODMSLogger('eodms_processes', api_logger.eodms_logger)

    @staticmethod
    def _default_user_agent() -> str:
        return f"{requests.utils.default_user_agent()} py-eodms-dds/{__version__}"

    def _apply_user_agent(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        if self.aaa is not None:
            return self.aaa.get_default_headers(headers)

        out_headers = dict(headers or {})
        out_headers['User-Agent'] = self._default_user_agent()
        return out_headers

    def _send_request(
        self,
        path: str,
        method: str = 'GET',
        json_payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        requires_auth: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Prepare and send an HTTP request to the Processes API."""
        url = f"{self.api_url}{path}"

        headers: Dict[str, str] = {'Accept': 'application/json'}
        if extra_headers:
            headers.update(extra_headers)

        if requires_auth:
            if self.aaa is None:
                raise ProcessingError("This operation requires AAA_API authentication.")
            access_token = self.aaa.get_access_token()
            if not access_token:
                raise ProcessingError("Processes API access token unavailable.")
            headers['Authorization'] = f"Bearer {access_token}"

        if json_payload is not None:
            headers['Content-Type'] = 'application/json'

        headers = self._apply_user_agent(headers)
        self.logger.debug(f"Outbound User-Agent: {headers.get('User-Agent')}")

        if self.aaa is not None:
            return self.aaa.prepare_request(
                url,
                method=method,
                headers=headers,
                json=json_payload,
                params=params,
            )

        req = requests.Request(method, url, headers=headers, json=json_payload, params=params)
        prepared = req.prepare()
        session = requests.Session()
        session.trust_env = False
        return session.send(prepared, verify=self.verify_ssl)

    @staticmethod
    def _require_json(resp: requests.Response) -> Dict[str, Any]:
        """Parse a JSON response and raise a readable error on failure."""
        if resp.status_code not in (200, 201):
            try:
                err = resp.json()
            except Exception:
                err = {'message': resp.text}
            raise ProcessingError(f"Request failed [{resp.status_code}]: {json.dumps(err)}")

        try:
            return resp.json()
        except Exception as exc:
            raise ProcessingError("Response body is not valid JSON.") from exc

    def list_processes(self) -> Dict[str, Any]:
        """List available processing services from /processing/processes."""
        resp = self._send_request('/processes')
        process_json = self._require_json(resp)
        self.logger.info("Successfully listed available processes")
        return process_json

    def get_process(self, process_id: str) -> Dict[str, Any]:
        """Get process description from /processing/processes/{process_id}."""
        resp = self._send_request(f'/processes/{process_id}')
        process_json = self._require_json(resp)
        self.logger.info(f"Successfully retrieved process description for {process_id}")
        return process_json

    def print_process_inputs(self, process_id: str) -> Dict[str, Any]:
        """Print expected input schema for a process and return full description JSON."""
        process_json = self.get_process(process_id)
        print(json.dumps(process_json.get('inputs', {}), indent=4))
        return process_json

    def submit_process(
        self,
        process_id: str,
        inputs: Dict[str, Any],
        outputs: Optional[Dict[str, Any]] = None,
        mode: str = 'async',
    ) -> Dict[str, Any]:
        """Submit a process execution request to /processing/processes/{process_id}/execution."""
        if outputs is None:
            outputs = {
                f"{process_id}-response": {
                    'format': {'mediaType': 'application/json'}
                }
            }

        payload = {
            'inputs': inputs,
            'outputs': outputs,
            'mode': mode,
        }

        resp = self._send_request(
            f'/processes/{process_id}/execution',
            method='POST',
            json_payload=payload,
            requires_auth=True,
            extra_headers={'Prefer': 'respond-async'},
        )
        result_json = self._require_json(resp)
        job_id = result_json.get('jobID')
        self.logger.info(f"Successfully submitted process {process_id} (jobID={job_id})")
        return result_json

    def submit_r1_process(
        self,
        segment_id: str,
        process_id: str,
        slc_type: str = 'beta0',
        lookup_table: str = 'mixed',
        start_time: Optional[str] = None,
        stop_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit RADARSAT-1 processing request using notebook-compatible inputs."""
        inputs = {
            'uuid': segment_id,
            'lookup_table': lookup_table,
            'slc_type': slc_type,
        }

        if start_time:
            inputs['start_time'] = start_time
        if stop_time:
            inputs['stop_time'] = stop_time

        return self.submit_process(process_id=process_id, inputs=inputs)

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get current job status from /processing/jobs/{job_id}."""
        resp = self._send_request(f'/jobs/{job_id}', requires_auth=True)
        status_json = self._require_json(resp)
        return status_json

    def poll_job_status(
        self,
        job_id: str,
        interval: int = 30,
        timeout: int = 600,
    ) -> Dict[str, Any]:
        """Poll a job status endpoint until it reaches a terminal state or timeout."""
        start_ts = time.time()
        self.logger.info(f"Monitoring job {job_id}...")

        while True:
            if time.time() - start_ts > timeout:
                raise ProcessingError(f"Job monitoring timed out after {timeout} seconds")

            status_json = self.get_job_status(job_id)
            status = str(status_json.get('status', 'unknown'))
            self.logger.info(f"Job {job_id} status: {status}")

            if status.lower() in self.TERMINAL_STATES:
                return status_json

            time.sleep(interval)

    def get_job_results(self, job_id: str) -> Dict[str, Any]:
        """Get job result manifest from /processing/jobs/{job_id}/results."""
        resp = self._send_request(
            f'/jobs/{job_id}/results',
            requires_auth=True,
            extra_headers={'Prefer': 'respond-async'},
        )
        result_json = self._require_json(resp)
        self.logger.info(f"Successfully retrieved results for job {job_id}")
        return result_json

    @staticmethod
    def _extract_file_uris(result_json: Dict[str, Any]) -> List[str]:
        """Extract file URIs from nested OGC Processes result structures."""
        uris: List[str] = []

        def walk(node: Any):
            if isinstance(node, dict):
                files = node.get('files')
                if isinstance(files, list):
                    for entry in files:
                        if isinstance(entry, str):
                            uris.append(entry)
                        elif isinstance(entry, dict):
                            href = entry.get('href')
                            if isinstance(href, str):
                                uris.append(href)

                href = node.get('href')
                if isinstance(href, str):
                    uris.append(href)

                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(result_json)

        deduped: List[str] = []
        seen = set()
        for uri in uris:
            if uri not in seen and re.match(r'^(s3|https?)://', uri):
                seen.add(uri)
                deduped.append(uri)

        return deduped

    @staticmethod
    def _parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
        parsed = urlparse(s3_uri)
        if parsed.scheme != 's3' or not parsed.netloc or not parsed.path:
            raise ValueError(f"Invalid S3 URI: {s3_uri}")
        return parsed.netloc, parsed.path.lstrip('/')

    def _download_http_file(self, url: str, out_file: str) -> str:
        headers = self._apply_user_agent()
        self.logger.debug(f"Outbound User-Agent: {headers.get('User-Agent')}")

        with requests.get(url, stream=True, verify=self.verify_ssl, headers=headers) as stream:
            stream.raise_for_status()
            with open(out_file, 'wb') as pipe:
                with tqdm.wrapattr(
                    pipe,
                    method='write',
                    miniters=1,
                    desc=os.path.basename(out_file)
                ) as file_out:
                    for chunk in stream.iter_content(chunk_size=1024):
                        file_out.write(chunk)
        return out_file

    def _download_s3_file(self, s3_uri: str, out_file: str) -> str:
        try:
            import boto3
            from botocore import UNSIGNED
            from botocore.config import Config
        except Exception as exc:
            raise ProcessingError(
                "Downloading s3:// result files requires boto3. Install with: pip install boto3"
            ) from exc

        bucket, key = self._parse_s3_uri(s3_uri)
        s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
        s3.download_file(bucket, key, out_file)
        return out_file

    def download_job_results(
        self,
        job_id: str,
        out_dir: str,
        skip_existing: bool = True,
    ) -> List[str]:
        """Download job output files (s3:// and https:// URIs) to a local folder."""
        result_json = self.get_job_results(job_id)
        file_uris = self._extract_file_uris(result_json)

        if not file_uris:
            self.logger.warning(f"No downloadable result files found for job {job_id}")
            return []

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        downloaded_files: List[str] = []
        for uri in file_uris:
            filename = os.path.basename(urlparse(uri).path)
            out_file = os.path.join(out_dir, filename)

            if skip_existing and os.path.exists(out_file):
                self.logger.info(f"Skipping existing file: {out_file}")
                downloaded_files.append(out_file)
                continue

            self.logger.info(f"Downloading result file: {uri}")
            if uri.startswith('s3://'):
                self._download_s3_file(uri, out_file)
            else:
                self._download_http_file(uri, out_file)

            downloaded_files.append(out_file)

        self.logger.info(f"Downloaded {len(downloaded_files)} file(s) for job {job_id}")
        return downloaded_files
