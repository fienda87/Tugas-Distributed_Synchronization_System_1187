import os
import json
import pytest

try:
    import requests  # type: ignore
except Exception:
    requests = None
    import urllib.request
    import urllib.parse

    class _Resp:
        def __init__(self, code, data):
            self.status_code = code
            self._data = data
        def json(self):
            return json.loads(self._data.decode("utf-8"))
        @property
        def text(self):
            return self._data.decode("utf-8")

    def _urlopen(method, url, params=None, json_body=None, timeout=5, headers=None):
        if params:
            q = urllib.parse.urlencode(params, doseq=True)
            url = f"{url}?{q}"
        data = None
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=h, method=method.upper())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _Resp(r.status, r.read())


def _post(url, params=None, json_body=None, headers=None, timeout=5):
    if requests:
        return requests.post(url, params=params, json=json_body, headers=headers, timeout=timeout, proxies={"http": None, "https": None})
    return _urlopen("POST", url, params=params, json_body=json_body, headers=headers, timeout=timeout)


def _get(url, params=None, headers=None, timeout=5):
    if requests:
        return requests.get(url, params=params, headers=headers, timeout=timeout, proxies={"http": None, "https": None})
    return _urlopen("GET", url, params=params, headers=headers, timeout=timeout)


GATEWAY = os.getenv("GATEWAY", "http://127.0.0.1:9300")
API_KEY = os.getenv("API_KEY", "demo_writer")
HEADERS = {"X-API-Key": API_KEY}


def _service_up(base_url: str) -> bool:
    try:
        r = _get(f"{base_url}/readyz", headers=HEADERS)
        return r.status_code == 200 and (r.json() or {}).get("ready") is True
    except Exception:
        return False


def test_geo_and_balancer():
    if not _service_up(GATEWAY):
        pytest.skip("Gateway service not ready")
    r = _get(f"{GATEWAY}/geo/route", params={"client_region": "us-east"}, headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "region" in j

    _post(f"{GATEWAY}/balancer/report", json_body={"node": "n1", "latency_ms": 120, "ok": True}, headers=HEADERS)
    _post(f"{GATEWAY}/balancer/report", json_body={"node": "n2", "latency_ms": 220, "ok": True}, headers=HEADERS)

    r2 = _get(f"{GATEWAY}/balancer/next", params={"nodes": "n1,n2"}, headers=HEADERS)
    assert r2.status_code == 200
    assert r2.json().get("node") in ("n1", "n2")
