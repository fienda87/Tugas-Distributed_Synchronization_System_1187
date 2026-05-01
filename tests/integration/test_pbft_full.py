import os
import json
import time
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


PBFT_NODE = os.getenv("PBFT_NODE", "http://127.0.0.1:9400")
API_KEY = os.getenv("API_KEY", "demo_writer")
HEADERS = {"X-API-Key": API_KEY}


def _service_up(base_url: str) -> bool:
    try:
        r = _get(f"{base_url}/readyz", headers=HEADERS)
        return r.status_code == 200 and (r.json() or {}).get("ready") is True
    except Exception:
        return False


def test_pbft_decision():
    if not _service_up(PBFT_NODE):
        pytest.skip("PBFT service not ready")
    payload = {"op": "set", "k": "x", "v": 1}
    r = _post(f"{PBFT_NODE}/pbft/request", json_body=payload, headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert j.get("accepted") is True

    r2 = _get(f"{PBFT_NODE}/pbft/status", headers=HEADERS)
    assert r2.status_code == 200
    st = r2.json()
    assert st.get("quorum", 0) >= 2
