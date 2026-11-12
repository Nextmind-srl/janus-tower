"""Shared helpers of the demo-mode tests (not a test module): private backend namespaces, an in-process server, a tiny HTTP client."""

import http.client
import json
import os
import shutil
import threading
from http.cookies import SimpleCookie
from pathlib import Path
from unittest import mock

import server

ROOT = Path(server.__file__).resolve().parent
REPO_DATA_DIR = ROOT / "data"
OAUTH_ENV_KEYS = ("GCP_OAUTH_CLIENT_ID", "GCP_OAUTH_CLIENT_SECRET")


def load_namespace(env: dict | None = None, drop: tuple = OAUTH_ENV_KEYS) -> dict:
    """A private copy of the whole backend, loaded exactly as server.py does, with a controlled environment.
    The environment is restored on return; the decision about demo mode is taken while the namespace loads."""
    with mock.patch.dict(os.environ, env or {}):
        for key in drop:
            # An empty variable wins over the developer's local `.env`, so these tests do not depend on it
            os.environ[key] = ""
        ns = {"__name__": "janustower_demo_test", "__file__": server.__file__}
        server.load_backend_modules(ns)
    return ns


def load_demo_namespace(**extra_env) -> dict:
    return load_namespace({"JANUSTOWER_DEMO": "1", **extra_env})


def cleanup_namespace(ns: dict) -> None:
    demo_dir = ns.get("DEMO_DATA_DIR")
    if demo_dir:
        shutil.rmtree(demo_dir, ignore_errors=True)


def snapshot_dir(path: Path) -> dict:
    """{relative path: (size, mtime_ns)} of everything under `path` (empty when it does not exist)."""
    out = {}
    if path.exists():
        for p in sorted(path.rglob("*")):
            st = p.stat()
            out[str(p.relative_to(path))] = (st.st_size, st.st_mtime_ns)
    return out


class InProcessServer:
    """The real MonitorHandler of a namespace, served on a random loopback port in a thread."""

    def __init__(self, ns: dict) -> None:
        self.ns = ns
        self.httpd = ns["ThreadingHTTPServer"](("127.0.0.1", 0), ns["MonitorHandler"])
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class Client:
    """Minimal HTTP client with a cookie jar (the demo login travels in cookies)."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.cookies: dict = {}

    def request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        if self.cookies:
            hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        data = None
        if body is not None:
            data = json.dumps(body)
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            conn.request(method, path, body=data, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            for line in resp.msg.get_all("Set-Cookie") or []:
                jar = SimpleCookie()
                jar.load(line)
                for name, morsel in jar.items():
                    if morsel.value:
                        self.cookies[name] = morsel.value
                    else:
                        self.cookies.pop(name, None)
        finally:
            conn.close()
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return resp.status, resp, parsed

    def get(self, path: str, **kw):
        return self.request("GET", path, **kw)

    def post(self, path: str, body: dict | None = None, **kw):
        return self.request("POST", path, body={} if body is None else body, **kw)
