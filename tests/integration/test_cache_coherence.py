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


CACHE_A = os.getenv("CACHE_A", "http://127.0.0.1:9200")
CACHE_B = os.getenv("CACHE_B", "http://127.0.0.1:9201")
API_KEY = os.getenv("API_KEY", "demo_writer")
HEADERS = {"X-API-Key": API_KEY}


def _service_up(base_url: str) -> bool:
    try:
        r = _get(f"{base_url}/readyz", headers=HEADERS)
        return r.status_code == 200 and (r.json() or {}).get("ready") is True
    except Exception:
        return False


def test_cache_invalidation_and_ttl():
    if not (_service_up(CACHE_A) and _service_up(CACHE_B)):
        pytest.skip("Cache services not ready")
    key = f"k_{int(time.time() * 1000)}"

    r = _post(f"{CACHE_A}/cache/put", json_body={"key": key, "value": "v1"}, headers=HEADERS)
    assert r.status_code == 200

    r2 = _get(f"{CACHE_B}/cache/get", params={"key": key}, headers=HEADERS)
    assert r2.status_code == 200
    assert r2.json().get("value") == "v1"

    r3 = _post(f"{CACHE_A}/cache/put", json_body={"key": key, "value": "v2"}, headers=HEADERS)
    assert r3.status_code == 200

    deadline = time.time() + 2.0
    ok = False
    while time.time() < deadline:
        r4 = _get(f"{CACHE_B}/cache/get", params={"key": key}, headers=HEADERS)
        if r4.status_code == 200 and r4.json().get("value") == "v2":
            ok = True
            break
        time.sleep(0.05)
    assert ok

    ttl_key = f"ttl_{int(time.time() * 1000)}"
    _post(f"{CACHE_A}/cache/put", params={"ttl_ms": 1000}, json_body={"key": ttl_key, "value": "temp"}, headers=HEADERS)
    time.sleep(1.5)
    r5 = _get(f"{CACHE_A}/cache/get", params={"key": ttl_key}, headers=HEADERS)
    assert r5.status_code == 200
    assert r5.json().get("hit") is False
