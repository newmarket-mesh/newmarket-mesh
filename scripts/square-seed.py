#!/usr/bin/env python3
"""Set up Newmarket Square: house rules, sign-up, and the starter communities.

Safe to run again. A community that already exists is left as it is.
Usage, from the repo root: scripts/square-seed.py [http://127.0.0.1:8094]
"""

import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8094").rstrip("/")

DESCRIPTION = "The community board for the Newmarket mesh."

SIDEBAR = """\
A board for neighbours on the Newmarket mesh. It is only reachable on the mesh.

**House rules**

1. Write about events, places, and work. Do not post about a person who has not done the thing. A name, a household, or a rumour is not a subject.
2. Do not publish where someone lives. No street addresses, coordinates, or map pins for a member or a sensor.
3. A removal or a warning can be appealed. The appeal goes to a moderator who did not make the decision, and you get a short written reason either way.

Moderators are members who take a shift. The shift rotates.
"""

COMMUNITIES = [
    ("around_town", "Around Town", "General talk about Newmarket. Openings, closings, questions, and news."),
    ("events", "Events", "Things happening in town. Put the date and the place in the title."),
    ("lost_and_found", "Lost and Found", "Pets, keys, and parcels. Say where it was found, not where you live."),
    ("free_and_for_sale", "Free and For Sale", "Give away, sell, or borrow. Meet somewhere public."),
    ("recommendations", "Recommendations", "Trades, shops, and services neighbours have used."),
    ("notices", "Notices", "Road closures, outages, weather, and town notices."),
    ("mesh", "Mesh Help", "Running a node, joining the mesh, and what is on the network."),
]


def env():
    values = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path}: {error.code} {detail}") from None


def exists(name, token):
    try:
        call("GET", f"/api/v3/community?name={quote(name)}", token=token)
    except RuntimeError as error:
        if "couldnt_find_community" in str(error):
            return False
        raise
    return True


WELCOME_TITLE = "Welcome to Newmarket Square"
WELCOME_BODY = """\
This is the board for neighbours on the Newmarket mesh. Nothing here is on the public internet.

Pick a community on the right and join it to see its posts on the front page:

- **Around Town** for general talk
- **Events** for things happening, with the date and place in the title
- **Lost and Found**, **Free and For Sale**, and **Recommendations**
- **Notices** for closures, outages, and weather
- **Mesh Help** for running a node

Read the house rules in the sidebar before you post. A moderator will remove a post that names a person or shows where someone lives.
"""


def welcome(token):
    community = call("GET", "/api/v3/community?name=around_town", token=token)["community_view"]["community"]
    posts = call("GET", f"/api/v3/post/list?community_id={community['id']}&sort=Old&limit=50", token=token)["posts"]
    if any(view["post"]["name"] == WELCOME_TITLE for view in posts):
        print("kept welcome post")
        return
    post = call("POST", "/api/v3/post", {
        "name": WELCOME_TITLE,
        "body": WELCOME_BODY,
        "community_id": community["id"],
    }, token=token)["post_view"]["post"]
    call("POST", "/api/v3/post/feature", {"post_id": post["id"], "featured": True, "feature_type": "Local"}, token=token)
    print("created welcome post")


def main():
    settings = env()
    login = call("POST", "/api/v3/user/login", {
        "username_or_email": settings.get("SQUARE_ADMIN_USER", "operator"),
        "password": settings["SQUARE_ADMIN_PASS"],
    })
    token = login["jwt"]

    call("PUT", "/api/v3/site", {
        "description": DESCRIPTION,
        "sidebar": SIDEBAR,
        # The mesh invitation is the gate. There is no mail server for verification.
        "registration_mode": "Open",
        "require_email_verification": False,
        "federation_enabled": False,
        "enable_downvotes": True,
    }, token=token)
    print("site settings saved")

    for name, title, description in COMMUNITIES:
        if exists(name, token):
            print(f"kept c/{name}")
            continue
        call("POST", "/api/v3/community", {
            "name": name,
            "title": title,
            "description": description,
        }, token=token)
        print(f"created c/{name}")

    welcome(token)


if __name__ == "__main__":
    main()
