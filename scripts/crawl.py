#!/usr/bin/env python3
"""Walk the .nm zone and write the search index.

Each pass reads the zone and fetches every site name over HTTPS.
It follows links that stay on those names. The name server is not a site.
"""

import json
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
ZONE = Path(os.environ.get("CRAWL_ZONE", ROOT / "deploy/lab/dns/nm.zone"))
HOST = "hub.nm"
RECORD_TYPES = {"A", "AAAA", "CNAME"}
SKIP_PREFIXES = ("/assets/", "/api/", "/if/")
# Newmarket Square is Lemmy with the Photon frontend. Forms, accounts, and admin
# pages are not results, and they would use up MAX_PAGES before the posts.
SQUARE = "square.nm"
SQUARE_SKIP_PREFIXES = (
    "/api/", "/pictrs/", "/feeds/", "/login", "/signup", "/accounts", "/create",
    "/settings", "/theme", "/inbox", "/saved", "/profile", "/moderation", "/admin",
    "/password_change", "/verify_email", "/u/", "/search", "/modlog", "/instances",
    "/registration_applications", "/reports", "/legal", "/util", "/go/", "/translators",
)
# A site's front page joins a category here when the page cannot carry the meta tag.
FRONT_PAGE_CATEGORY = {SQUARE: "Community"}
# The directory is the index itself, so it is not a search result.
UNINDEXED = {"/directory"}
MAX_PAGES = 200
ALLOWED_HOSTS = {HOST}


def outputs():
    raw = os.environ.get("CRAWL_OUTS", "")
    if raw.strip():
        return [Path(part) for part in raw.split(",") if part.strip()]
    return [
        ROOT / "hub" / "assets" / "catalog.json",
        ROOT / "portal" / "directory" / "catalog.json",
    ]


def qualify(name, origin):
    name = name.strip().lower()
    if name == "@":
        return origin.rstrip(".")
    if name.endswith("."):
        return name.rstrip(".")
    return f"{name}.{origin.rstrip('.')}"


def load_hosts(path):
    origin = "nm."
    owner = None
    hosts = set()
    if not path.is_file():
        print(f"zone missing ({path}), crawling {HOST} only", flush=True)
        return {HOST}
    for raw in path.read_text().splitlines():
        stripped = raw.split(";", 1)[0].rstrip()
        if not stripped.strip():
            continue
        if stripped.lstrip().upper().startswith("$ORIGIN"):
            origin = stripped.split()[1].strip()
            if not origin.endswith("."):
                origin += "."
            owner = None
            continue
        if stripped.lstrip().startswith("$"):
            continue
        parts = stripped.split()
        if raw[:1].isspace():
            name = owner
        else:
            name = parts.pop(0)
            owner = name
        if not name:
            continue
        tokens = [part.upper() for part in parts]
        while tokens and (tokens[0].isdigit() or tokens[0] in {"IN", "CH", "HS"}):
            tokens.pop(0)
        if not tokens or tokens[0] not in RECORD_TYPES:
            continue
        host = qualify(name, origin)
        if host in {origin.rstrip("."), f"ns.{origin.rstrip('.')}"}:
            continue
        hosts.add(host)
    return hosts or {HOST}


# Icons, menus, and controls are not page text. An icon's <title> is not the page title.
SKIPPED_TAGS = ("script", "style", "noscript", "header", "footer", "nav", "svg", "select", "button")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []
        self.links = []
        self.title = []
        self.in_title = False
        self.h1 = []
        self.in_h1 = False
        self.category = ""
        self.summary = ""

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag in SKIPPED_TAGS:
            self.skip += 1
        if tag == "title" and not self.skip:
            self.in_title = True
        if tag == "h1" and not self.skip:
            self.in_h1 = True
        if tag == "meta":
            name = (fields.get("name") or "").lower()
            content = (fields.get("content") or "").strip()
            if name == "mesh-category":
                self.category = content
            elif name == "mesh-summary":
                self.summary = content
        if tag == "a":
            href = fields.get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS and self.skip:
            self.skip -= 1
        if tag == "title":
            self.in_title = False
        if tag == "h1":
            self.in_h1 = False

    def handle_data(self, data):
        if self.skip:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self.in_title:
            self.title.append(text)
            return
        if self.in_h1:
            self.h1.append(text)
        self.parts.append(text)


def host_of(url):
    return (urlparse(url).hostname or "").lower().rstrip(".")


def allowed(url):
    parsed = urlparse(url)
    host = host_of(url)
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        return False
    if parsed.port not in (None, 443):
        return False
    if host == HOST and any(parsed.path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    if host == SQUARE and any(parsed.path.startswith(prefix) for prefix in SQUARE_SKIP_PREFIXES):
        return False
    return True


def canonical(url):
    bare = url.split("#", 1)[0]
    parsed = urlparse(bare)
    host = host_of(bare)
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS or parsed.port not in (None, 443):
        return bare
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return f"https://{host}{path}"


class Stay(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(canonical(newurl)):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = build_opener(Stay)


def fetch(url):
    request = Request(url, headers={"User-Agent": "newmarket-mesh-crawl"})
    try:
        response = OPENER.open(request, timeout=8)
    except HTTPError as error:
        if error.code in (301, 302, 303, 307, 308, 404):
            return None
        raise
    with response:
        final = canonical(response.geturl())
        if not allowed(final):
            return None
        kind = response.headers.get("Content-Type", "")
        if "html" not in kind:
            return None
        return final, response.read().decode("utf-8", "replace")


def seeds(hosts):
    found = []
    for host in sorted(hosts):
        found.append(f"https://{host}/")
        if host == HOST:
            found.append(f"https://{host}/directory/")
            found.append(f"https://{host}/search/")
            found.append(f"https://{host}/status/")
    return found


def crawl():
    global ALLOWED_HOSTS
    ALLOWED_HOSTS = load_hosts(ZONE)
    print(f"sites {', '.join(sorted(ALLOWED_HOSTS))}", flush=True)
    seen = set()
    queue = seeds(ALLOWED_HOSTS)
    pages = []
    while queue and len(pages) < MAX_PAGES:
        url = canonical(queue.pop(0).split("#", 1)[0])
        if url in seen or not allowed(url):
            continue
        seen.add(url)
        try:
            fetched = fetch(url)
        except Exception as error:
            print(f"skip {url} ({error})")
            continue
        if not fetched:
            continue
        final, html = fetched
        if final != url and final in seen:
            continue
        seen.add(final)
        page = Page()
        page.feed(html)
        parsed = urlparse(final)
        title = " ".join(page.h1) or " ".join(page.title) or parsed.path
        title = re.sub(r"\s*·\s*Newmarket community mesh", "", title, flags=re.I).strip()
        text = " ".join(page.parts)
        text = re.sub(r"\s+", " ", text).strip()
        if page.summary and page.summary not in text:
            text = (page.summary + " " + text).strip()
        text = text[:1200]
        on_hub_index = host_of(final) == HOST and parsed.path.rstrip("/") in UNINDEXED
        category = page.category
        if not category and parsed.path == "/":
            category = FRONT_PAGE_CATEGORY.get(host_of(final), "")
        if not on_hub_index:
            pages.append({
                "url": final,
                "title": title,
                "category": category,
                "summary": page.summary,
                "text": text,
            })
            print(f"indexed {final}")
        for href in page.links:
            joined = canonical(urljoin(final, href).split("#", 1)[0])
            if joined not in seen and allowed(joined):
                queue.append(joined)
    return pages


def publish(pages):
    payload = json.dumps(pages, indent=2) + "\n"
    wrote = False
    for out in outputs():
        if out.is_file() and out.read_text() == payload:
            continue
        out.write_text(payload)
        wrote = True
        print(f"wrote {len(pages)} pages to {out}", flush=True)
    if not wrote:
        print(f"index unchanged, {len(pages)} pages", flush=True)


def main():
    interval = int(os.environ.get("CRAWL_INTERVAL", "0"))
    while True:
        try:
            pages = crawl()
        except Exception as error:
            print(f"crawl failed ({error})", flush=True)
        else:
            if pages:
                publish(pages)
            else:
                print("no pages found, keeping the current index", flush=True)
        if interval <= 0:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
