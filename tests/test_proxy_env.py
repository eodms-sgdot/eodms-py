from pathlib import Path

import requests

from eodms.aaa import AAA_API
from eodms.processes import Processes_API


class _AdapterResponse(requests.Response):
    def __init__(self, request):
        super().__init__()
        self.status_code = 200
        self._content = b"{}"
        self.headers["Content-Type"] = "application/json"
        self.url = request.url
        self.request = request


def _capture_proxies(monkeypatch):
    captured = []

    def fake_send(self, request, **kwargs):
        captured.append(kwargs.get("proxies"))
        return _AdapterResponse(request)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return captured


def _capture_authorization(monkeypatch):
    captured = []

    def fake_send(self, request, **kwargs):
        captured.append(request.headers.get("Authorization"))
        return _AdapterResponse(request)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return captured


def test_aaa_prepare_request_uses_https_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    captured = _capture_proxies(monkeypatch)

    api = AAA_API("demo-user", "demo-pass", "prod")
    api.prepare_request("https://example.com/aaa/v1/login")

    assert captured == [{"https": "http://proxy.example.com:3128"}]


def test_processes_send_request_uses_https_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    captured = _capture_proxies(monkeypatch)

    api = Processes_API(environment="prod")
    api._send_request("/processes")

    assert captured == [{"https": "http://proxy.example.com:3128"}]


def test_aaa_prepare_request_ignores_netrc_auth_while_using_proxy_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    Path(tmp_path / "_netrc").write_text(
        "machine example.com login wrong-user password wrong-pass\n",
        encoding="utf-8",
    )

    captured = _capture_authorization(monkeypatch)

    api = AAA_API("demo-user", "demo-pass", "prod")
    api.prepare_request("https://example.com/aaa/v1/login", method="POST", json={"username": "demo-user", "password": "demo-pass"})

    assert captured == [None]