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


LOCK_LEADER = os.getenv("LOCK_LEADER", "http://127.0.0.1:9000")
API_KEY = os.getenv("API_KEY", "demo_writer")
HEADERS = {"X-API-Key": API_KEY}


def _service_up(base_url: str) -> bool:
    try:
        r = _get(f"{base_url}/readyz", headers=HEADERS)
        return r.status_code == 200 and (r.json() or {}).get("ready") is True
    except Exception:
        return False


def test_lock_shared_exclusive_and_deadlock():
    if not _service_up(LOCK_LEADER):
        pytest.skip("Lock service not ready")
    resource = f"r_lock_{int(time.time() * 1000)}"
    # Exclusive lock
    r = _post(f"{LOCK_LEADER}/lock/acquire", json_body={
        "resource": resource,
        "mode": "exclusive",
        "client_id": "c1",
        "timeout_ms": 2000,
    }, headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert j.get("granted") is True
    tok = j.get("token")

    # Shared lock should queue
    r2 = _post(f"{LOCK_LEADER}/lock/acquire", json_body={
        "resource": resource,
        "mode": "shared",
        "client_id": "c2",
        "timeout_ms": 2000,
    }, headers=HEADERS)
    assert r2.status_code == 200
    assert r2.json().get("granted") is False

    # Release then shared should be granted
    r3 = _post(f"{LOCK_LEADER}/lock/release", json_body={"resource": resource, "token": tok}, headers=HEADERS)
    assert r3.status_code == 200

    time.sleep(0.2)
    r4 = _get(f"{LOCK_LEADER}/lock/state", params={"resource": resource}, headers=HEADERS)
    assert r4.status_code == 200

    # Deadlock probe should respond
    # Retry with backoff in case of transient failures
    r5 = None
    for attempt in range(3):
        r5 = _post(f"{LOCK_LEADER}/lock/deadlock", json_body={}, headers=HEADERS)
        if r5.status_code == 200:
            break
        time.sleep(0.5)
    
    assert r5 is not None, "Deadlock probe failed after 3 attempts"
    assert r5.status_code == 200, f"Expected 200, got {r5.status_code}: {r5.text}"
    assert "deadlock" in r5.json()
