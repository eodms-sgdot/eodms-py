import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from eodms.aaa import AAA_API


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"Content-Type": "application/json"}
        self.text = ""

    def json(self):
        return self._payload


def test_aaa_three_concurrent_logins_single_network_login(monkeypatch, tmp_path):
    """Three concurrent callers should trigger only one AAA login request."""

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    login_count = 0
    login_count_lock = threading.Lock()

    def fake_prepare_request(self, url, method='GET', **kwargs):
        nonlocal login_count

        if url.endswith('/aaa/v1/login'):
            with login_count_lock:
                login_count += 1

            # Keep the login request in flight briefly so other callers contend on lock.
            time.sleep(0.15)
            return _FakeResponse(
                200,
                {
                    "access_token": "token-abc",
                    "refresh_token": "refresh-abc",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 7200,
                },
            )

        if url.endswith('/aaa/v1/refresh'):
            return _FakeResponse(
                200,
                {
                    "access_token": "token-refreshed",
                    "refresh_token": "refresh-refreshed",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 7200,
                },
            )

        return _FakeResponse(404, {"error": "unexpected_url"})

    monkeypatch.setattr(AAA_API, "prepare_request", fake_prepare_request)

    def get_token(_):
        api = AAA_API("demo-user", "demo-pass", "prod")
        return api.get_access_token()

    with ThreadPoolExecutor(max_workers=3) as executor:
        tokens = list(executor.map(get_token, range(3)))

    assert tokens == ["token-abc", "token-abc", "token-abc"]
    assert login_count == 1

    creds_file = tmp_path / ".eodms" / "aaa_creds.demo-user.prod.json"
    assert os.path.exists(creds_file)


def test_aaa_stale_lock_is_recovered(monkeypatch, tmp_path):
    """A stale lock file should be removed so token login can proceed."""

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    login_count = 0

    def fake_prepare_request(self, url, method='GET', **kwargs):
        nonlocal login_count

        if url.endswith('/aaa/v1/login'):
            login_count += 1
            return _FakeResponse(
                200,
                {
                    "access_token": "token-stale-lock",
                    "refresh_token": "refresh-stale-lock",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 7200,
                },
            )

        return _FakeResponse(404, {"error": "unexpected_url"})

    monkeypatch.setattr(AAA_API, "prepare_request", fake_prepare_request)

    api = AAA_API("demo-user", "demo-pass", "prod")

    os.makedirs(api.auth_folder, exist_ok=True)
    with open(api._token_lock_fn, "w", encoding="utf-8") as lock_file:
        lock_file.write("stale lock")

    stale_mtime = time.time() - 300
    os.utime(api._token_lock_fn, (stale_mtime, stale_mtime))

    token = api.get_access_token()

    assert token == "token-stale-lock"
    assert login_count == 1
    assert os.path.exists(api.aaa_creds.cred_fn)
    assert not os.path.exists(api._token_lock_fn)
