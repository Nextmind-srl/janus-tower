"""Demo mode activation rule: decided once at startup from the environment / `.env`, never from a request."""

import contextlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import demo_test_support as sup

ROOT = sup.ROOT


def decide(ns_or_none=None):
    """Loads the pure functions of backend/demo_mode.py on their own (no side effect at import time that matters here)."""
    mod = {"__name__": "demo_mode_pure", "__file__": str(ROOT / "backend" / "demo_mode.py"), "_JT_DEMO_ENRICH_ONLY": True}
    exec(compile((ROOT / "backend" / "demo_mode.py").read_text(encoding="utf-8"), "demo_mode.py", "exec"), mod)  # noqa: S102
    sup.cleanup_namespace(mod)
    return mod


class TestActivationRule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dm = decide()
        cls.decide = staticmethod(cls.dm["decide_demo_mode"])

    def test_explicit_on(self):
        self.assertTrue(self.decide({"JANUSTOWER_DEMO": "1"}))
        self.assertTrue(self.decide({"JANUSTOWER_DEMO": "true"}))
        self.assertTrue(self.decide({"JANUSTOWER_DEMO": "1", "GCP_OAUTH_CLIENT_ID": "id", "GCP_OAUTH_CLIENT_SECRET": "secret"}))

    def test_explicit_off_wins_even_without_oauth(self):
        self.assertFalse(self.decide({"JANUSTOWER_DEMO": "0"}))
        self.assertFalse(self.decide({"JANUSTOWER_DEMO": "false"}))
        self.assertFalse(self.decide({"JANUSTOWER_DEMO": "0", "GCP_OAUTH_CLIENT_ID": "id", "GCP_OAUTH_CLIENT_SECRET": "secret"}))

    def test_automatic_without_oauth_client(self):
        self.assertTrue(self.decide({}))
        self.assertTrue(self.decide({"JANUSTOWER_DEMO": ""}))
        self.assertTrue(self.decide({"JANUSTOWER_DEMO": "maybe"}))
        self.assertTrue(self.decide({"GCP_OAUTH_CLIENT_ID": "id"}))  # half a client is not a client
        self.assertTrue(self.decide({"GCP_OAUTH_CLIENT_SECRET": "secret"}))
        self.assertTrue(self.decide({"GCP_OAUTH_CLIENT_ID": "  ", "GCP_OAUTH_CLIENT_SECRET": "secret"}))

    def test_automatic_off_with_oauth_client(self):
        self.assertFalse(self.decide({"GCP_OAUTH_CLIENT_ID": "id", "GCP_OAUTH_CLIENT_SECRET": "secret"}))
        self.assertFalse(self.decide({"JANUSTOWER_DEMO": ""}, {"GCP_OAUTH_CLIENT_ID": "id", "GCP_OAUTH_CLIENT_SECRET": "secret"}))

    def test_dotenv_values_are_considered_but_the_environment_wins(self):
        env_file = {"GCP_OAUTH_CLIENT_ID": "id", "GCP_OAUTH_CLIENT_SECRET": "secret"}
        self.assertFalse(self.decide({}, env_file))
        self.assertTrue(self.decide({"JANUSTOWER_DEMO": "1"}, env_file))
        self.assertFalse(self.decide({}, {**env_file, "JANUSTOWER_DEMO": "0"}))
        # an empty variable in the real environment is not replaced by the `.env` value (same as config.py)
        self.assertTrue(self.decide({"GCP_OAUTH_CLIENT_ID": ""}, env_file))
        self.assertTrue(self.decide({"JANUSTOWER_DEMO": "1"}, {"JANUSTOWER_DEMO": "0"}))

    def test_dotenv_reader_does_not_touch_the_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# comment\nexport GCP_OAUTH_CLIENT_ID='abc'\nGCP_OAUTH_CLIENT_SECRET=xyz\nJANUSTOWER_DEMO=0\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GCP_OAUTH_CLIENT_ID", None)
                values = self.dm["read_dotenv_values"](str(path))
                self.assertNotIn("GCP_OAUTH_CLIENT_ID", os.environ)
        self.assertEqual(values, {"GCP_OAUTH_CLIENT_ID": "abc", "GCP_OAUTH_CLIENT_SECRET": "xyz", "JANUSTOWER_DEMO": "0"})
        self.assertEqual(self.dm["read_dotenv_values"](str(Path(tmp) / "missing.env")), {})


class TestSwitchIsFixedAtStartup(unittest.TestCase):
    def tearDown(self):
        sup.cleanup_namespace(self.ns)

    def test_the_decision_is_taken_while_the_backend_loads(self):
        self.ns = sup.load_namespace({"JANUSTOWER_DEMO": "1"})
        self.assertTrue(self.ns["is_demo_mode"]())
        with mock.patch.dict(os.environ, {"JANUSTOWER_DEMO": "0", "GCP_OAUTH_CLIENT_ID": "a", "GCP_OAUTH_CLIENT_SECRET": "b"}):
            self.assertTrue(self.ns["is_demo_mode"](), "changing the environment later must not turn the demo off")

    def test_automatic_activation_in_a_fresh_backend(self):
        self.ns = sup.load_namespace({"JANUSTOWER_DEMO": ""})
        self.assertTrue(self.ns["is_demo_mode"]())
        self.assertFalse(self.ns["OAUTH_CONFIGURED_AT_STARTUP"])

    def test_no_http_request_can_flip_the_switch(self):
        self.ns = sup.load_demo_namespace()
        srv = sup.InProcessServer(self.ns)
        try:
            c = sup.Client(srv.port)
            c.get("/api/auth/status")
            for path in ("/api/auth/status?demo=0&JANUSTOWER_DEMO=0", "/api/scan?cached=0&demo=0"):
                c.get(path, headers={"X-JANUSTOWER-DEMO": "0", "X-Demo": "0"})
            c.post("/api/budgets", {"demo": False, "JANUSTOWER_DEMO": "0", "projectId": "acme-ml-lab", "budgetUsd": 5})
            status, _, body = c.get("/api/auth/status")
            self.assertTrue(body["demo"])
            self.assertTrue(self.ns["is_demo_mode"]())
        finally:
            srv.close()


class TestDemoHonoursStartupEnvironment(unittest.TestCase):
    def tearDown(self):
        sup.cleanup_namespace(self.ns)

    def test_host_overrides_are_ignored_in_demo_but_the_bind_address_is_honoured(self):
        self.ns = sup.load_demo_namespace(HOST="0.0.0.0", LOOPBACK_HOST="evil.example.com", PUBLIC_BASE_URL="https://evil.example.com",  # noqa: S104
                                          ALLOWED_HOSTS="evil.example.com")
        # the bind address is honoured (the Docker image needs 0.0.0.0 inside the container; the demo holds only invented data)
        self.assertEqual(self.ns["HOST"], "0.0.0.0")  # noqa: S104
        self.assertEqual(self.ns["LOOPBACK_HOST"], "localhost")
        with mock.patch.dict(os.environ, {"LOOPBACK_HOST": "evil.example.com", "PUBLIC_BASE_URL": "https://evil.example.com", "ALLOWED_HOSTS": "evil.example.com"}):
            self.assertEqual(self.ns["allowed_request_hosts"](), {"localhost", "127.0.0.1", "[::1]"})

    def test_oauth_client_in_the_environment_is_not_kept_in_demo(self):
        self.ns = sup.load_namespace({"JANUSTOWER_DEMO": "1", "GCP_OAUTH_CLIENT_ID": "id.example", "GCP_OAUTH_CLIENT_SECRET": "secret-value"}, drop=())
        self.assertEqual(self.ns["OAUTH_CLIENT_ID"], "")
        self.assertEqual(self.ns["OAUTH_CLIENT_SECRET"], "")
        self.assertTrue(self.ns["OAUTH_CONFIGURED_AT_STARTUP"], "the status still tells that a client exists in the environment")
        self.assertFalse(self.ns["OAUTH_CONFIGURED"])

    def test_dotenv_is_not_read_in_demo(self):
        self.ns = sup.load_namespace({"JANUSTOWER_DEMO": "1"})
        src = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
        self.assertIn("if not is_demo_mode():\n    load_dotenv_file(", src)
        # the demo namespace is the one that did NOT call it: the only `.env` read is the read-only parse of demo_mode.py
        self.assertNotIn("_DEMO_DOTENV", self.ns, "the parsed `.env` content must not stay in memory")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestStartupProcess(unittest.TestCase):
    def test_banner_loopback_bind_and_no_repo_data_access(self):
        before = sup.snapshot_dir(sup.REPO_DATA_DIR)
        port = _free_port()
        env = {k: v for k, v in os.environ.items() if k not in sup.OAUTH_ENV_KEYS}
        env.pop("HOST", None)  # default bind address: loopback only
        env.update({"JANUSTOWER_DEMO": "1", "PORT": str(port), "AUTO_OPEN_BROWSER": "0"})
        proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")], cwd=str(ROOT), env=env,  # noqa: S603
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            body = None
            for _ in range(60):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth/status", timeout=2) as r:  # noqa: S310
                        body = r.read().decode("utf-8")
                    break
                except OSError:
                    time.sleep(0.25)
            self.assertIsNotNone(body, "the demo server did not start")
            self.assertIn('"demo": true', body)
            # not reachable through a non-loopback address of this machine
            others = []
            with contextlib.suppress(OSError):
                others = [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")]
            for addr in others[:1]:
                with self.assertRaises(OSError), socket.create_connection((addr, port), timeout=1):
                    pass
        finally:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
        self.assertIn("DEMO MODE", out)
        self.assertIn(f"Host: 127.0.0.1:{port}", out)
        self.assertEqual(sup.snapshot_dir(sup.REPO_DATA_DIR), before, "the demo process must not touch <repo>/data")


if __name__ == "__main__":
    unittest.main()
