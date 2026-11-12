#!/usr/bin/env python3
"""Tests for the mesh status checker. No live network."""

import importlib.util
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("meshstatus", Path(__file__).with_name("status.py"))
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)

BANNED = {"address", "ip", "ips", "url", "error", "body", "host", "hostname", "elapsed"}


def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in BANNED:
                raise AssertionError(key)
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)


def answer_for(request, addresses=("192.0.2.10",)):
    header = bytearray(request[:12])
    header[2:4] = b"\x81\x80"
    header[6:8] = len(addresses).to_bytes(2, "big")
    body = b""
    for address in addresses:
        parts = bytes(int(part) for part in address.split("."))
        body += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x01\x2c\x00\x04" + parts
    return bytes(header) + request[12:] + body


class StatusTests(unittest.TestCase):
    def test_node_state(self):
        self.assertEqual(status.node_state([]), "unchecked")
        self.assertEqual(status.node_state(["up", "up"]), "up")
        self.assertEqual(status.node_state(["down", "down"]), "down")
        self.assertEqual(status.node_state(["up", "down"]), "issues")
        self.assertEqual(status.node_state(["up", "issues"]), "issues")

    def test_judge_http(self):
        up = status.Answer(status=200, elapsed=0.2, body=b"ok")
        self.assertEqual(status.judge_http(up, ""), ("up", "Answered."))
        slow = status.Answer(status=200, elapsed=6, body=b"ok")
        self.assertEqual(status.judge_http(slow, ""), ("issues", "Answered slowly."))
        err = status.Answer(status=500, elapsed=0.2, body=b"no")
        self.assertEqual(status.judge_http(err, ""), ("issues", "Answered with an error."))
        missing = status.Answer(status=404, elapsed=0.2, body=b"no")
        self.assertEqual(
            status.judge_http(missing, "json"),
            ("issues", "The search index is not being served."),
        )
        page = status.Answer(status=200, elapsed=0.2, body=b" <html>")
        self.assertEqual(
            status.judge_http(page, "json"),
            ("issues", "The search index is not being served."),
        )
        catalog = status.Answer(status=200, elapsed=0.2, body=b"\n[")
        self.assertEqual(status.judge_http(catalog, "json"), ("up", "Answered."))
        self.assertEqual(
            status.judge_http(status.Answer(error="timeout"), ""),
            ("down", "Did not answer."),
        )
        self.assertEqual(
            status.judge_http(status.Answer(error="tls"), ""),
            ("issues", "The secure connection failed."),
        )

    def test_judge_names(self):
        self.assertEqual(
            status.judge_names([("hub.nm", "ok"), ("square.nm", "ok")]),
            ("up", "Answered."),
        )
        self.assertEqual(
            status.judge_names([("hub.nm", "timeout"), ("square.nm", "timeout")]),
            ("down", "The name server did not answer."),
        )
        self.assertEqual(
            status.judge_names([("hub.nm", "ok"), ("square.nm", "missing")]),
            ("issues", "square.nm did not resolve."),
        )

    def test_parse_dns(self):
        tid = b"\x12\x34"
        query = status.build_query("hub.nm", tid)
        header = bytearray(query[:12])
        header[2:4] = b"\x81\x80"
        header[6:8] = b"\x00\x01"
        answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x01\x2c\x00\x04\xc0\x00\x02\x0a"
        message = status.parse_dns(bytes(header) + query[12:] + answer, tid)
        self.assertEqual(message.answers, ("192.0.2.10",))
        self.assertEqual(message.rcode, 0)
        self.assertFalse(message.tc)
        with self.assertRaises(ValueError):
            status.parse_dns(bytes(header) + query[12:] + answer, b"\x00\x00")
        pointer = b"\x12\x34\x81\x80\x00\x01\x00\x00\x00\x00\x00\x00\xc0\x0c\x00\x01\x00\x01"
        looped = status.parse_dns(pointer, b"\x12\x34")
        self.assertEqual(looped.answers, ())

    def test_dns_server_parse(self):
        self.assertIsNone(status.parse_dns_server(""))
        self.assertEqual(status.parse_dns_server("192.0.2.10"), ("192.0.2.10", 53))
        self.assertEqual(status.parse_dns_server("192.0.2.10:5353"), ("192.0.2.10", 5353))
        self.assertEqual(status.parse_dns_server("[::1]:53"), ("::1", 53))

    def test_load_nodes_rejects_secrets_and_strangers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nodes.json"
            path.write_text(json.dumps({
                "nodes": [{
                    "id": "x",
                    "name": "X",
                    "place": "Newmarket",
                    "role": "Full node",
                    "summary": "A node.",
                    "address": "192.0.2.10",
                    "checks": [{
                        "id": "web",
                        "name": "Web",
                        "kind": "https",
                        "url": "http://hub.nm/",
                    }],
                }]
            }))
            with self.assertRaises(ValueError):
                status.load_nodes(path)
            path.write_text(json.dumps({
                "nodes": [{
                    "id": "x",
                    "name": "X",
                    "place": "Newmarket",
                    "role": "Full node",
                    "summary": "A node.",
                    "checks": [{
                        "id": "names",
                        "name": "Names",
                        "kind": "dns",
                        "names": ["example.com"],
                    }],
                }]
            }))
            with self.assertRaises(ValueError):
                status.load_nodes(path)

    def test_committed_nodes_are_cities_on_the_map(self):
        nodes = status.load_nodes(ROOT / "hub" / "status" / "nodes.json")
        html = (ROOT / "hub" / "status" / "index.html").read_text()
        self.assertIn("Members, homes, and sensors are not", html)
        raw = (ROOT / "hub" / "status" / "nodes.json").read_text().lower()
        for word in ("latitude", "longitude", "street"):
            self.assertNotIn(word, raw)
        for node in nodes:
            self.assertIn(node["place"] + ":", html)
            self.assertEqual(
                set(node),
                {"id", "name", "place", "role", "summary", "checks"},
            )

    def test_udp_and_tcp_dns(self):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))
        port = udp.getsockname()[1]
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind(("127.0.0.1", port))
        tcp.listen(1)
        udp.settimeout(2)
        tcp.settimeout(2)

        def serve_udp():
            data, addr = udp.recvfrom(512)
            header = bytearray(data[:12])
            header[2:4] = b"\x83\x80"
            header[6:8] = b"\x00\x00"
            udp.sendto(bytes(header) + data[12:], addr)

        def serve_tcp():
            conn, _ = tcp.accept()
            conn.settimeout(2)
            try:
                length = int.from_bytes(status.recv_exact(conn, 2), "big")
                request = status.recv_exact(conn, length)
                response = answer_for(request)
                conn.sendall(len(response).to_bytes(2, "big") + response)
            finally:
                conn.close()

        threads = [
            threading.Thread(target=serve_udp, daemon=True),
            threading.Thread(target=serve_tcp, daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            message = status.query_a(("127.0.0.1", port), "hub.nm", 2)
        finally:
            for thread in threads:
                thread.join(3)
            udp.close()
            tcp.close()
        self.assertEqual(message.answers, ("192.0.2.10",))

    def test_fetch_and_refused(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        closed_port = closed.getsockname()[1]
        closed.close()
        refused = status.fetch(f"https://hub.nm:{closed_port}/", "127.0.0.1", timeout=2)
        self.assertEqual(status.judge_http(refused, ""), ("down", "Did not answer."))

        cert_dir = tempfile.TemporaryDirectory()
        self.addCleanup(cert_dir.cleanup)
        cert = str(Path(cert_dir.name) / "cert.pem")
        key = str(Path(cert_dir.name) / "key.pem")
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key, "-out", cert, "-days", "1", "-nodes",
                "-subj", "/CN=hub.nm",
                "-addext", "subjectAltName=DNS:hub.nm",
            ],
            check=True,
            capture_output=True,
        )

        class Handler(BaseHTTPRequestHandler):
            seen = {}

            def do_GET(self):
                Handler.seen = {key.lower(): value for key, value in self.headers.items()}
                body = b"["
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever)
        thread.daemon = True
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = f"https://hub.nm:{port}/assets/catalog.json"
        untrusted = status.fetch(url, "127.0.0.1", timeout=3)
        self.assertEqual(untrusted.error, "tls")
        previous = os.environ.get("SSL_CERT_FILE")
        os.environ["SSL_CERT_FILE"] = cert
        try:
            trusted = status.fetch(url, "127.0.0.1", timeout=3)
        finally:
            if previous is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = previous
        self.assertEqual(trusted.status, 200)
        self.assertEqual(trusted.body, b"[")
        self.assertEqual(Handler.seen.get("accept-encoding"), "identity")
        self.assertEqual(status.judge_http(trusted, "json"), ("up", "Answered."))

    def test_report_has_no_addresses(self):
        nodes = status.load_nodes(ROOT / "hub" / "status" / "nodes.json")

        def resolve(host):
            if host.endswith(".nm"):
                return ("ok", ("192.0.2.10",))
            return ("ok", ("198.51.100.4",))

        def fetch_url(url, address):
            self.assertIn(address, ("192.0.2.10", "198.51.100.4"))
            body = b"[" if url.endswith("catalog.json") else b"ok"
            return status.Answer(status=200, elapsed=0.05, body=body)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "status.json"
            when = datetime(2026, 10, 31, 22, 15, tzinfo=timezone.utc)
            payload = status.once(nodes, out, resolve, fetch_url, now=when)
        self.assertNotIn("192.0.2", payload)
        self.assertNotIn("198.51.100", payload)
        report = json.loads(payload)
        walk(report)
        self.assertEqual(report["checked"], "2026-10-31T22:15:00Z")
        self.assertEqual([item["state"] for item in report["results"]], ["up", "up"])

    def test_partial_outage_is_issues(self):
        nodes = [{
            "id": "newmarket",
            "name": "Newmarket node",
            "place": "Newmarket",
            "role": "Full node",
            "summary": "Serves the hub.",
            "checks": [
                {"id": "hub", "name": "Hub", "kind": "https", "url": "https://hub.nm/"},
                {"id": "square", "name": "Square", "kind": "https", "url": "https://square.nm/"},
            ],
        }]

        def resolve(host):
            return ("ok", ("192.0.2.10",))

        def fetch_url(url, address):
            if "square" in url:
                return status.Answer(error="connect", elapsed=0.1)
            return status.Answer(status=200, elapsed=0.1, body=b"ok")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "status.json"
            payload = status.once(nodes, out, resolve, fetch_url)
        report = json.loads(payload)
        self.assertEqual(report["results"][0]["state"], "issues")
        states = {item["id"]: item["state"] for item in report["results"][0]["checks"]}
        self.assertEqual(states, {"hub": "up", "square": "down"})
        self.assertNotIn("192.0.2", payload)


if __name__ == "__main__":
    unittest.main()
