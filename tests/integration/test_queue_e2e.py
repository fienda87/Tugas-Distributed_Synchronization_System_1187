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


QUEUE_PRIMARY = os.getenv("QUEUE_PRIMARY", "http://127.0.0.1:9100")
QUEUE_REPLICA = os.getenv("QUEUE_REPLICA", "http://127.0.0.1:9102")
API_KEY = os.getenv("API_KEY", "demo_writer")
HEADERS = {"X-API-Key": API_KEY}


def _service_up(base_url: str) -> bool:
    try:
        r = _get(f"{base_url}/readyz", headers=HEADERS)
        return r.status_code == 200 and (r.json() or {}).get("ready") is True
    except Exception:
        return False


def test_queue_publish_consume_ack_owner():
    if not (_service_up(QUEUE_PRIMARY) and _service_up(QUEUE_REPLICA)):
        pytest.skip("Queue services not ready")
    topic = f"tq_{int(time.time() * 1000)}"
    key = "user42"

    # publish
    for i in range(5):
        r = _post(f"{QUEUE_PRIMARY}/queue/publish", params={"topic": topic, "key": key},
                  json_body={"n": i}, headers=HEADERS)
        assert r.status_code == 200

    # consume
    r = _post(f"{QUEUE_REPLICA}/queue/consume", params={"topic": topic, "key": key, "visibility_ttl": 3000, "max": 5},
              headers=HEADERS)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list) and len(items) > 0

    # ack via owner
    for it in items:
        r2 = _post(f"{QUEUE_REPLICA}/queue/ack_owner", params={"topic": topic, "owner": it.get("owner"), "msg_id": it.get("msg_id")},
                   headers=HEADERS)
        assert r2.status_code == 200

    time.sleep(3.5)
    r3 = _post(f"{QUEUE_REPLICA}/queue/consume", params={"topic": topic, "key": key, "visibility_ttl": 3000, "max": 5},
               headers=HEADERS)
    assert r3.status_code == 200
    assert r3.json() == []
