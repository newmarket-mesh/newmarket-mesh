# How the mesh runs

What each part does, where it runs, what it keeps, and who can see it. Checked 31 Oct 2026. If anything here stops being true, this page changes in the same commit.

## Who runs it

One operator today. The operator holds admin on the login server, the hub, and Newmarket Square. A second operator, and a second copy of the hub, come when a member is willing to run a full node.

## The login server

https://login.newmarket.network (first named https://nm-mesh.daddar.io, which still works) runs [Headscale](https://github.com/juanfont/headscale) on a rented server in Toronto (Linode). That server also hosts the operator's web-hosting business.

It decides which devices are on the mesh. For each device it stores the owner's mesh username, the device name, its mesh addresses, its public keys, its operating system and Tailscale version, the public address and port it was last reachable on, and when it was last seen. It does not see what devices send to each other.

It logs warnings only. Those logs rotate at 30 MB.

The web proxy in front of it, Traefik, logs every request to the server with the device's public IP address, the time, and the path. That log is shared with the other sites on the same server, is kept for about 14 days, and is readable by the server's administrator. Traefik 3.0 cannot turn it off for one site.

If the login server is down, devices already on the mesh keep reaching each other. New devices cannot join and nothing can change until it is back.

The status checker on the Newmarket node requests `/health` once a minute. That request is in this same log.

## Traffic between devices

Devices talk to each other directly, encrypted with WireGuard. To connect directly, every device on the mesh learns the public IP address and port of the devices it talks to. That is how a direct connection is made. It is the same in any Tailscale network.

When two devices cannot connect directly, Tailscale's public relays (DERP) carry the traffic. The relays forward encrypted packets. They see the public addresses of the two devices and how much they send. They cannot read it. Tailscale, the company, runs those relays.

Nobody's home internet is carried for someone else. The access policy never approves exit routes.

## Who can reach what

[deploy/headscale/policy.hujson](deploy/headscale/policy.hujson) is the whole policy. Every member's device can reach every other member's device, on any port. Do not run anything on a device on the mesh that you would not show a neighbour.

## The hub and Newmarket Square

The hub (https://hub.newmarket.network) and the Square (https://square.nm-mesh.daddar.io) run in a container on a home server in Newmarket. The operator's desktop carries them onto the mesh. That desktop's mesh connection can reach only the hub's web and DNS ports and the public internet. It cannot reach anything else on that home network. See [deploy/tailscale/](deploy/tailscale/).

When that home server or that desktop is off, the hub and the Square are offline.

The hub's page server logs each request with the time, the page, and the browser's name. It never sees who asked: every request reaches it from the hub's own gate, so that is the only address in the log. The gates in front of the hub and the Square keep no access logs. All container logs rotate at 30 MB.

The search index is built every minute from public pages on `.nm` sites, including Square posts. It is not published here.

The status page at https://hub.newmarket.network/status/ shows the Newmarket node and the login server. A checker on the Newmarket node runs every minute. It asks this node's name server for `hub.nm` and `square.nm`, and it opens the hub, the Square, and the search index over HTTPS. It also opens `https://login.newmarket.network/health`. For each check it keeps the time, a state (up, issues, or down), and a short reason such as "Answered." or "Did not answer." It does not keep addresses, and it does not list devices.

The map marks Newmarket and Toronto, the cities already named here. It is a diagram, not a street map. It has no member, no home, and no sensor. The latest result stays on the hub for anyone on the mesh who can open the hub. It is not in this repository. This page is served by the Newmarket node. If that node is shut down, the page is off with it.

The hub, directory, and status pages load nothing from outside the mesh. No analytics, no fonts, no trackers.

On the Square, the operator can read everything posted, the same as any forum admin. There is no mail server, so the Square has no email addresses unless a member types one in. Photos lose their location data when uploaded.

## Names and certificates

`hub.newmarket.network` and `square.nm-mesh.daddar.io` are public DNS records that point at the hub's mesh address. Anyone can look them up. Only devices on the mesh can open them. The old hub name, `hub.nm-mesh.daddar.io`, redirects to the new one.

Their certificates come from Let's Encrypt. Let's Encrypt cannot reach a mesh address, so ownership is proven with a temporary TXT record in the name's zone. That proof is public, as all certificates are, through Certificate Transparency logs.

## What is not in this repository

Secrets and running data stay on the servers: passwords, private keys, certificate keys, the login server's database, and the Square's database. Each full node's own LAN addresses stay in its `.env` and settings files.
