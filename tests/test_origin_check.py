"""Tests for the Host/Origin guard and the rolling 30-day login window (invented data only)."""

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from tests.test_app import load_app_namespace

NS = load_app_namespace()
check = NS["request_origin_allowed"]
within = NS["_is_login_within_days"]


class TestOriginCheck(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("LOOPBACK_HOST", "PUBLIC_BASE_URL", "ALLOWED_HOSTS"):
            os.environ.pop(k, None)

    def ok(self, method="GET", path="/api/x", **headers) -> bool:
        return check(method, path, headers)[0]

    def test_loopback_hosts_allowed(self) -> None:
        for h in ("localhost", "localhost:8095", "127.0.0.1:8095", "[::1]:8095", "LOCALHOST:1"):
            self.assertTrue(self.ok(Host=h), h)

    def test_dns_rebinding_and_missing_host_refused(self) -> None:
        self.assertFalse(self.ok(Host="evil.example"))
        self.assertFalse(self.ok(Host="evil.example:8095"))
        self.assertFalse(self.ok())

    def test_userinfo_and_paths_in_host_are_refused(self) -> None:
        for h in ("localhost:80@evil.example", "localhost@evil.example", "localhost/evil", "local host"):
            self.assertFalse(self.ok(Host=h), h)

    def test_origin_on_post_and_scan(self) -> None:
        self.assertTrue(self.ok("POST", Host="localhost:8095", Origin="http://localhost:8095"))
        self.assertTrue(self.ok("POST", Host="localhost:8095"))
        self.assertFalse(self.ok("POST", Host="localhost:8095", Origin="https://evil.example"))
        self.assertFalse(self.ok("POST", Host="localhost:8095", Origin="null"))
        self.assertFalse(self.ok("GET", "/api/scan?x=1", Host="localhost", Origin="https://evil.example"))
        # Plain GETs do not check Origin
        self.assertTrue(self.ok("GET", "/api/other", Host="localhost", Origin="https://evil.example"))

    def test_env_configured_hosts(self) -> None:
        os.environ["PUBLIC_BASE_URL"] = "https://janus.example.test:8443/"
        os.environ["ALLOWED_HOSTS"] = "Proxy.example.test, other.example.test:80"
        os.environ["LOOPBACK_HOST"] = "mybox"
        for h in ("janus.example.test", "proxy.example.test", "other.example.test", "mybox:8095"):
            self.assertTrue(self.ok(Host=h), h)
        self.assertFalse(self.ok(Host="evil.example"))


class TestLoginWindow(unittest.TestCase):
    NOW = datetime(2030, 6, 30, 12, 0, 0, tzinfo=timezone.utc)

    def test_window(self) -> None:
        self.assertTrue(within("2030-06-15T10:00:00Z", 30, self.NOW))
        self.assertTrue(within("2030-06-15T10:00:00.123456789Z", 30, self.NOW))
        self.assertTrue(within("2030-06-30T14:00:00+02:00", 30, self.NOW))
        self.assertFalse(within("2030-05-31T11:59:59Z", 30, self.NOW))
        self.assertTrue(within("2030-05-31T12:00:00Z", 30, self.NOW))

    def test_empty_or_invalid(self) -> None:
        for v in ("", None, "garbage", "2030-13-45"):
            self.assertFalse(within(v, 30, self.NOW), v)


if __name__ == "__main__":
    unittest.main()
