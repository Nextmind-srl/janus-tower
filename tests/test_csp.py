"""Content-Security-Policy della pagina: niente unsafe-inline/unsafe-eval negli script, hash dello script reale, host coperti."""

import base64
import hashlib
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import server

ROOT = Path(server.__file__).resolve().parent


def directive(csp, name):
    for part in csp.split(";"):
        part = part.strip()
        if part.startswith(name + " ") or part == name:
            return part
    return ""


class TestCsp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_csp = staticmethod(server.build_csp)
        cls.csp_header_name = staticmethod(server.csp_header_name)
        cls.html = (ROOT / "index.html").read_bytes()
        cls.csp = cls.build_csp(cls.html)

    def test_script_src_senza_unsafe(self):
        s = directive(self.csp, "script-src")
        self.assertNotIn("'unsafe-inline'", s)
        self.assertNotIn("'unsafe-eval'", s)
        self.assertNotIn("*", s)

    def test_hash_corrisponde_allo_script_inline_reale(self):
        inline = re.findall(rb"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", self.html, re.S)
        self.assertEqual(len(inline), 1, "index.html deve avere un solo script inline")
        h = "'sha256-" + base64.b64encode(hashlib.sha256(inline[0]).digest()).decode() + "'"
        self.assertIn(h, directive(self.csp, "script-src"))

    def test_l_hash_cambia_se_lo_script_cambia(self):
        modificato = self.html.replace(b"let globalScanData = null;", b"let globalScanData = 1;", 1)
        self.assertNotEqual(modificato, self.html)
        self.assertNotEqual(self.build_csp(modificato), self.csp)

    def test_html_senza_script_inline_non_autorizza_nulla_di_inline(self):
        csp = self.build_csp(b"<html><script src='https://cdn.jsdelivr.net/x.js'></script></html>")
        self.assertNotIn("sha256-", csp)
        self.assertNotIn("'unsafe-inline'", directive(csp, "script-src"))

    def test_ogni_host_esterno_dichiarato_in_index_e_coperto(self):
        html = self.html.decode("utf-8")
        for tag, attr, direct in (("script", "src", "script-src"), ("link", "href", "style-src")):
            for m in re.finditer(rf"<{tag}\b[^>]*\b{attr}=\"(https://[^\"/]+)", html):
                if tag == "link" and "stylesheet" not in m.group(0):
                    continue
                self.assertIn(m.group(1), directive(self.csp, direct), m.group(0)[:100])
        self.assertIn("https://fonts.gstatic.com", directive(self.csp, "font-src"))

    def test_direttive_di_chiusura(self):
        self.assertEqual(directive(self.csp, "default-src"), "default-src 'none'")
        self.assertEqual(directive(self.csp, "connect-src"), "connect-src 'self'")
        self.assertEqual(directive(self.csp, "object-src"), "object-src 'none'")
        self.assertEqual(directive(self.csp, "base-uri"), "base-uri 'none'")
        self.assertEqual(directive(self.csp, "frame-ancestors"), "frame-ancestors 'self'")

    def test_nome_header_e_modalita_report_only(self):
        with mock.patch.dict(os.environ, {"CSP_REPORT_ONLY": ""}):
            self.assertEqual(self.csp_header_name(), "Content-Security-Policy")
        with mock.patch.dict(os.environ, {"CSP_REPORT_ONLY": "1"}):
            self.assertEqual(self.csp_header_name(), "Content-Security-Policy-Report-Only")

    def test_crlf_nel_file_non_cambia_l_hash(self):
        crlf = self.html.replace(b"\n", b"\r\n")
        self.assertEqual(self.build_csp(crlf), self.csp)

    def test_server_reale_invia_la_csp_solo_sulla_pagina(self):
        import http.client
        import threading

        srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.MonitorHandler)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            def get(path):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                c.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
                r = c.getresponse()
                r.read()
                c.close()
                return r
            home = get("/")
            self.assertEqual(home.status, 200)
            self.assertEqual(home.getheader("Content-Security-Policy"), self.csp)
            self.assertIsNone(home.getheader("Content-Security-Policy-Report-Only"))
            with mock.patch.dict(os.environ, {"CSP_REPORT_ONLY": "1"}):
                ro = get("/index.html")
            self.assertIsNone(ro.getheader("Content-Security-Policy"))
            self.assertEqual(ro.getheader("Content-Security-Policy-Report-Only"), self.csp)
            self.assertIsNone(get("/api/non-esiste").getheader("Content-Security-Policy"))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
