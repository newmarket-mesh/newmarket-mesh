# Newmarket community mesh

A neighbourhood network for Newmarket, Ontario. Members join with the Tailscale app, then reach each other and the community services by name. Everyone keeps their own internet connection. The mesh never carries anyone's home internet for someone else.

How it runs, what it stores, and who can see what: [TRANSPARENCY.md](TRANSPARENCY.md). House rules: [MODERATION.md](MODERATION.md).

## Pieces

- **Login server**: [Headscale](https://github.com/juanfont/headscale) 0.29.7 at https://login.newmarket.network. Devices that joined under the first name, `nm-mesh.daddar.io`, still reach it there. It decides which devices are on the mesh. Config in `deploy/headscale/`.
- **Relays**: Tailscale's public DERP servers, used only when two devices cannot connect directly. They forward encrypted packets.
- **Hub**: https://hub.newmarket.network on the mesh. Search across every `.nm` site, plus the directory. [Homer](https://github.com/bastienwirtz/homer) v26.08.3 behind Caddy 2.11.7.
- **Newmarket Square**: https://square.nm-mesh.daddar.io on the mesh. The community board. [Lemmy](https://join-lemmy.org/) 0.19.21 with the [Photon](https://github.com/Xyphyn/photon) frontend.
- **Names**: every device on the mesh is `name.nm`. On a full node's LAN, CoreDNS answers `.nm` for the sites on that node.

`hub.newmarket.network` and `square.nm-mesh.daddar.io` resolve publicly to the hub's mesh address, `100.64.0.1`. Anyone can look the names up. Only devices on the mesh can reach that address.

Versions, checked 31 Oct 2026 (America/Toronto): Headscale `0.29.7`, Homer `v26.08.3`, Caddy `2.11.7`, Lemmy `0.19.21`, Photon `v2.4.3`, pict-rs `0.5.25`, PostgreSQL `16.15`, CoreDNS `1.12.3`.

## Run a hub

From the repo root:

```bash
cp .env.example .env
cp deploy/lab/dns/nm.zone.example deploy/lab/dns/nm.zone
```

Set `LAB_BIND` in `.env` to this host's LAN address, and put the same address in `nm.zone`. Then:

```bash
scripts/lab.sh up -d
```

Do not forward these ports on your router. `LAB_BIND` has to be an address already configured on this host.

The pages listen on `127.0.0.1` and `LAB_BIND`:

- Portal: http://127.0.0.1:8090/
- Directory: http://127.0.0.1:8090/directory/
- Hub: http://127.0.0.1:8092/
- Square: http://127.0.0.1:8094/
- With names, from the same LAN: https://hub.nm/ and https://square.nm/ (Caddy's local certificate)

### Certificates

Let's Encrypt cannot reach a mesh address, so the mesh names are proven through a TXT record in their zone (`newmarket.network` for the hub, `daddar.io` for the Square), with [acme.sh](https://github.com/acmesh-official/acme.sh) in manual DNS mode. The certificates live in `deploy/lab/acme/`, which is never committed. They are renewed by hand before they expire.

### Newmarket Square

Fill the four `SQUARE_` values in `.env` before the first start. Lemmy reads the admin name and password once, when the database is empty. After the first start:

```bash
scripts/square-seed.py
```

That writes the house rules into the sidebar, opens sign-up, turns federation off, and creates the starter communities: Around Town, Events, Lost and Found, Free and For Sale, Recommendations, Notices, and Mesh Help. Running it again leaves existing communities alone.

Sign-up is open because the mesh invitation is already the gate. There is no mail server, so there is no email verification and no password reset by mail. The operator resets a password from the admin page.

Lemmy's hostname is fixed at the first start. Changing it later breaks every link and account already made. Photon renders pages on the server through the mesh name, so the Photon container resolves `square.nm-mesh.daddar.io` to `LAB_BIND` and needs the name gate up with a valid certificate. Without it, pages fail with a 500.

## Put the hub on the mesh

`deploy/tailscale/` runs a second Tailscale daemon in its own network namespace, so a desktop can carry the hub onto the mesh without joining its own tailnet to it. The namespace can reach the hub's ports 80, 443, and 53 and the public internet. It cannot reach anything else on the LAN.

1. Install `nm-netns.default` as `/etc/default/nm-netns` with `HUB_IP` set to the hub's LAN address.
2. Install `nm-netns.sh` as `/usr/local/sbin/nm-netns.sh`, and the two `.service` files under `/etc/systemd/system/`. Enable both.
3. Log the namespace daemon in with a key from the login server, as `hub`, and forward its ports 80 and 443 to the hub with `tailscale serve --tcp`.

## Run the login server

`deploy/headscale/` is a Compose file for a host with a public address behind Traefik. Relays stay Tailscale's. `policy.hujson` is the access policy: every member can reach every other member, and exit routes are never approved.

## Layout

- `deploy/headscale/`: the login server and the access policy
- `deploy/tailscale/`: the namespace that carries the hub onto the mesh
- `deploy/lab/compose.yml`: Caddy for the portal
- `deploy/lab/hub.yml`: the hub
- `deploy/lab/names.yml`: the name gate (Caddy on 80 and 443), the `.nm` DNS server, and the crawler
- `deploy/lab/square.yml`: Newmarket Square. Lemmy, Photon, pict-rs for pictures, PostgreSQL, and a Caddy gate on 8094. pict-rs strips location data from uploaded photos.
- `portal/`: the portal and the directory
- `hub/`: the hub and its search page
- `scripts/crawl.py`: walks every HTTPS name in the `.nm` zone every minute and rewrites the search index when a page changes. A page joins a directory category with `<meta name="mesh-category" content="Name">`.
- `scripts/square-seed.py`: site settings and starter communities for the Square

## Stop

```bash
scripts/lab.sh down
```

## License

Code and configuration: [GNU AGPL-3.0](LICENSE). If you run a modified version for other people, you publish your changes.

Documentation and house rules (`*.md`): [CC BY-SA 4.0](LICENSES/CC-BY-SA-4.0.txt).
