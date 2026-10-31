#!/usr/bin/env python3
"""Check the machines that run the mesh and write a status file.

The machines are the full node in Newmarket and the login server in Toronto,
listed in hub/status/nodes.json. Member devices are not checked and are not
written into the file. The file records a state and a short reason. It does
not record addresses.

A check is up, issues, or down. A node is down when every one of its checks
is down, and having issues when any check is down or having issues.
"""

import http.client
import json
import os
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DNS_TIMEOUT = 3
HTTP_TIMEOUT = 8
SLOW_SECONDS = 5
ID = re.compile(r"^[a-z0-9-]{1,40}$")


class Answer(object):
    def __init__(self, status=None, elapsed=0.0, error=None, body=b""):
        self.status = status
        self.elapsed = elapsed
        self.error = error
        self.body = body or b""


class DnsMessage(object):
    def __init__(self, rcode, tc, answers):
        self.rcode = rcode
        self.tc = tc
        self.answers = tuple(answers)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a chosen address and keep the name for the certificate."""

    def __init__(self, host, address, port, timeout, context):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned = address
        self._context = context

    def connect(self):
        raw = socket.create_connection((self._pinned, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def stamp(now=None):
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def node_state(states):
    if not states or any(state != "up" for state in states):
        if states and all(state == "down" for state in states):
            return "down"
        return "issues" if states else "unchecked"
    return "up"


def judge_lookup(kind):
    if kind == "unconfigured":
        return "issues", "The checker has no name server configured."
    if kind == "timeout":
        return "down", "The name server did not answer."
    if kind == "bad":
        return "issues", "The name server's reply could not be read."
    if kind == "missing":
        return "down", "The name did not resolve."
    return "issues", "The check did not finish."


def judge_names(outcomes):
    kinds = [kind for _, kind in outcomes]
    if not kinds:
        return "issues", "The check did not finish."
    if any(kind == "unconfigured" for kind in kinds):
        return "issues", "The checker has no name server configured."
    if all(kind == "timeout" for kind in kinds):
        return "down", "The name server did not answer."
    if any(kind == "bad" for kind in kinds):
        return "issues", "The name server's reply could not be read."
    missing = [name for name, kind in outcomes if kind == "missing"]
    timed = [name for name, kind in outcomes if kind == "timeout"]
    if missing or timed:
        parts = [f"{name} did not resolve." for name in missing]
        parts += [f"{name} did not get an answer." for name in timed]
        return "issues", " ".join(parts)
    if all(kind == "ok" for kind in kinds):
        return "up", "Answered."
    return "issues", "The check did not finish."


def judge_http(answer, expect):
    if answer is None:
        return "down", "Did not answer."
    if answer.error == "tls":
        return "issues", "The secure connection failed."
    if answer.error == "protocol":
        return "issues", "Answered with an error."
    if answer.error in ("timeout", "connect"):
        return "down", "Did not answer."
    if answer.error:
        return "issues", "The check did not finish."
    if answer.status is None or answer.status >= 400:
        if expect == "json":
            return "issues", "The search index is not being served."
        return "issues", "Answered with an error."
    if expect == "json":
        sample = answer.body.lstrip()
        if not sample[:1] in (b"[", b"{"):
            return "issues", "The search index is not being served."
    if answer.elapsed > SLOW_SECONDS:
        return "issues", "Answered slowly."
    return "up", "Answered."


def need_text(obj, key, limit):
    value = obj.get(key)
    if not isinstance(value, str):
        raise ValueError("nodes")
    value = " ".join(value.split())
    if not value or len(value) > limit:
        raise ValueError("nodes")
    return value


def clean_https(check, ident, name):
    parsed = urlparse(check.get("url") or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
        or not host
        or ":" in host
        or host.replace(".", "").isdigit()
    ):
        raise ValueError("nodes")
    path = parsed.path or "/"
    if not path.startswith("/"):
        raise ValueError("nodes")
    expect = check.get("expect") or ""
    if expect not in ("", "json"):
        raise ValueError("nodes")
    item = {"id": ident, "name": name, "kind": "https", "url": f"https://{host}{path}"}
    if expect:
        item["expect"] = expect
    return item


def clean_dns(check, ident, name):
    names = check.get("names")
    if not isinstance(names, list) or not names or len(names) > 8:
        raise ValueError("nodes")
    cleaned = []
    for item in names:
        if not isinstance(item, str):
            raise ValueError("nodes")
        host = item.strip().lower().rstrip(".")
        if (
            not host.endswith(".nm")
            or "/" in host
            or ":" in host
            or " " in host
            or len(host) > 253
        ):
            raise ValueError("nodes")
        cleaned.append(host)
    return {"id": ident, "name": name, "kind": "dns", "names": cleaned}


def clean_check(check, seen):
    if not isinstance(check, dict):
        raise ValueError("nodes")
    ident = check.get("id")
    if not isinstance(ident, str) or not ID.match(ident) or ident in seen:
        raise ValueError("nodes")
    seen.add(ident)
    name = need_text(check, "name", 40)
    kind = check.get("kind")
    if kind == "dns":
        return clean_dns(check, ident, name)
    if kind == "https":
        return clean_https(check, ident, name)
    raise ValueError("nodes")


def load_nodes(path):
    data = json.loads(Path(path).read_text())
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes")
    seen = set()
    cleaned = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("nodes")
        ident = node.get("id")
        if not isinstance(ident, str) or not ID.match(ident) or ident in seen:
            raise ValueError("nodes")
        seen.add(ident)
        checks = node.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError("nodes")
        check_ids = set()
        cleaned.append({
            "id": ident,
            "name": need_text(node, "name", 80),
            "place": need_text(node, "place", 40),
            "role": need_text(node, "role", 40),
            "summary": need_text(node, "summary", 400),
            "checks": [clean_check(check, check_ids) for check in checks],
        })
    return cleaned


def encode_qname(name):
    labels = name.rstrip(".").lower().split(".")
    if not labels or len(name) > 253:
        raise ValueError("dns")
    out = bytearray()
    for label in labels:
        raw = label.encode("ascii")
        if not raw or len(raw) > 63:
            raise ValueError("dns")
        out.append(len(raw))
        out.extend(raw)
    out.append(0)
    return bytes(out)


def build_query(qname, tid):
    if len(tid) != 2:
        raise ValueError("dns")
    header = tid + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    return header + encode_qname(qname) + b"\x00\x01\x00\x01"


def skip_name(packet, offset):
    hops = 0
    while True:
        if hops > 20 or offset < 0 or offset >= len(packet):
            raise ValueError("dns")
        length = packet[offset]
        hops += 1
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError("dns")
            return offset + 2
        if length & 0xC0:
            raise ValueError("dns")
        offset += 1 + length


def parse_dns(packet, tid):
    if not isinstance(packet, (bytes, bytearray)) or len(packet) < 12 or packet[:2] != tid:
        raise ValueError("dns")
    flags = int.from_bytes(packet[2:4], "big")
    rcode = flags & 0x0F
    tc = bool(flags & 0x0200)
    questions = int.from_bytes(packet[4:6], "big")
    answers_n = int.from_bytes(packet[6:8], "big")
    offset = 12
    for _ in range(questions):
        offset = skip_name(packet, offset)
        if offset + 4 > len(packet):
            raise ValueError("dns")
        offset += 4
    answers = []
    for _ in range(answers_n):
        offset = skip_name(packet, offset)
        if offset + 10 > len(packet):
            raise ValueError("dns")
        kind = int.from_bytes(packet[offset:offset + 2], "big")
        length = int.from_bytes(packet[offset + 8:offset + 10], "big")
        offset += 10
        if length < 0 or offset + length > len(packet):
            raise ValueError("dns")
        data = packet[offset:offset + length]
        offset += length
        if kind == 1 and len(data) == 4:
            answers.append(".".join(str(byte) for byte in data))
    return DnsMessage(rcode, tc, answers)


def recv_exact(sock, count):
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise ValueError("dns")
        buf.extend(chunk)
    return bytes(buf)


def query_tcp(server, packet, tid, timeout):
    sock = socket.create_connection(server, timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall(len(packet).to_bytes(2, "big") + packet)
        length = int.from_bytes(recv_exact(sock, 2), "big")
        if length < 12 or length > 4096:
            raise ValueError("dns")
        return parse_dns(recv_exact(sock, length), tid)
    finally:
        sock.close()


def query_a(server, qname, timeout):
    tid = os.urandom(2)
    packet = build_query(qname, tid)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(timeout)
    try:
        udp.sendto(packet, server)
        data, _ = udp.recvfrom(2048)
    finally:
        udp.close()
    parsed = parse_dns(data, tid)
    if parsed.tc:
        return query_tcp(server, packet, tid, timeout)
    return parsed


def sort_v4(addresses):
    return tuple(sorted(addresses, key=lambda addr: ":" in addr))


def lookup_mesh(server, qname, timeout, cache):
    if qname in cache:
        return cache[qname]
    if server is None:
        result = ("unconfigured", ())
    else:
        try:
            message = query_a(server, qname, timeout)
        except TimeoutError:
            result = ("timeout", ())
        except OSError:
            result = ("timeout", ())
        except ValueError:
            result = ("bad", ())
        else:
            if message.rcode != 0 or not message.answers:
                result = ("missing", ())
            else:
                result = ("ok", sort_v4(message.answers))
    cache[qname] = result
    return result


def lookup_public(host):
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return ("missing", ())
    addresses = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        return ("missing", ())
    return ("ok", sort_v4(addresses))


def parse_dns_server(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("["):
        host, _, rest = raw[1:].partition("]")
        port = rest[1:] if rest.startswith(":") and rest[1:].isdigit() else "53"
        return host, int(port)
    if raw.count(":") == 1:
        host, port = raw.rsplit(":", 1)
        if port.isdigit():
            return host, int(port)
    return raw, 53


def fetch(url, address, timeout=HTTP_TIMEOUT):
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    context = ssl.create_default_context()
    started = time.monotonic()
    conn = PinnedHTTPSConnection(host, address, port, timeout, context)
    try:
        conn.request(
            "GET",
            path,
            headers={
                "User-Agent": "newmarket-mesh-status",
                "Accept-Encoding": "identity",
                "Accept": "*/*",
                "Connection": "close",
            },
        )
        response = conn.getresponse()
        body = response.read(256)
        return Answer(status=response.status, elapsed=time.monotonic() - started, body=body)
    except TimeoutError:
        return Answer(error="timeout", elapsed=time.monotonic() - started)
    except ssl.SSLError:
        return Answer(error="tls", elapsed=time.monotonic() - started)
    except http.client.HTTPException:
        return Answer(error="protocol", elapsed=time.monotonic() - started)
    except OSError:
        return Answer(error="connect", elapsed=time.monotonic() - started)
    finally:
        conn.close()


def run_dns(check, resolve):
    outcomes = []
    for name in check["names"]:
        found = resolve(name)
        outcomes.append((name, found[0]))
    return judge_names(outcomes)


def run_https(check, resolve, fetch_url):
    host = urlparse(check["url"]).hostname
    found = resolve(host)
    if found[0] != "ok" or not found[1]:
        return judge_lookup(found[0] if found[0] != "ok" else "missing")
    answer = None
    for address in found[1]:
        answer = fetch_url(check["url"], address)
        if answer.error not in ("timeout", "connect"):
            break
    return judge_http(answer, check.get("expect") or "")


def run_check(check, resolve, fetch_url):
    try:
        if check["kind"] == "dns":
            return run_dns(check, resolve)
        return run_https(check, resolve, fetch_url)
    except Exception as error:
        print(f"check {check['id']} error ({type(error).__name__})", flush=True)
        return "issues", "The check did not finish."


def once(nodes, out, resolve, fetch_url, now=None):
    results = []
    for node in nodes:
        checks = []
        for check in node["checks"]:
            state, detail = run_check(check, resolve, fetch_url)
            print(f"check {node['id']}/{check['id']} {state}", flush=True)
            checks.append({"id": check["id"], "state": state, "detail": detail})
        rolled = node_state([item["state"] for item in checks])
        print(f"node {node['id']} {rolled}", flush=True)
        results.append({"id": node["id"], "state": rolled, "checks": checks})
    payload = json.dumps({"checked": stamp(now), "results": results}, indent=2) + "\n"
    publish(Path(out), payload)
    return payload


def publish(path, payload):
    if path.is_file() and path.read_text() == payload:
        print("status unchanged", flush=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    print(f"wrote status to {path}", flush=True)


def main():
    interval = int(os.environ.get("STATUS_INTERVAL", "0"))
    if interval < 0:
        interval = 0
    nodes_path = Path(os.environ.get("STATUS_NODES", ROOT / "hub" / "status" / "nodes.json"))
    out = Path(os.environ.get("STATUS_OUT", ROOT / "hub" / "assets" / "status.json"))
    while True:
        try:
            nodes = load_nodes(nodes_path)
            server = parse_dns_server(os.environ.get("STATUS_DNS", ""))
            cache = {}

            def resolve(host, cache=cache, server=server):
                if host.endswith(".nm"):
                    return lookup_mesh(server, host, DNS_TIMEOUT, cache)
                return lookup_public(host)

            once(nodes, out, resolve, fetch)
        except ValueError:
            print("node list rejected", flush=True)
        except Exception as error:
            print(f"status check failed ({type(error).__name__})", flush=True)
        if interval <= 0:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
