# Newmarket community mesh

A neighbourhood network for Newmarket, Ontario. Members join with the Tailscale app, then reach each other and the community services by name. Everyone keeps their own internet connection. The mesh never carries anyone's home internet for someone else.

How it runs, what it stores, and who can see what: [TRANSPARENCY.md](TRANSPARENCY.md). House rules: [MODERATION.md](MODERATION.md).

## Pieces

- **Login server**: [Headscale](https://github.com/juanfont/headscale) 0.29.7 at https://login.newmarket.network. Devices that joined under the first name, `nm-mesh.daddar.io`, still reach it there. It decides which devices are on the mesh. Config in `deploy/headscale/`.
- **Relays**: Tailscale's public DERP servers, used only when two devices cannot connect directly. They forward encrypted packets.
- **Hub**: https://hub.newmarket.network on the mesh. Search across every `.nm` site, plus the directory. [Homer](https://github.com/bastienwirtz/homer) v26.08.3 behind Caddy 2.11.7.
- **Newmarket Square**: https://square.nm-mesh.daddar.io on the mesh. The community board. [Lemmy](https://join-lemmy.org/) 0.19.21 with the [Photon](https://github.com/Xyphyn/photon) frontend.
- **Names**: every device on the mesh is `name.nm`. `hub.nm` is the hub machine. `square.nm` is a mesh DNS record for the same address. CoreDNS on the hub answers the rest of `.nm`.

`hub.newmarket.network` and `square.nm-mesh.daddar.io` resolve publicly to the hub's mesh address, `100.64.0.1`. Anyone can look the names up. Only devices on the mesh can reach that address.

Versions, checked 31 Oct 2026 (America/Toronto): Headscale `0.29.7`, Homer `v26.08.3`, Caddy `2.11.7`, Lemmy `0.19.21`, Photon `v2.4.3`, pict-rs `0.5.25`, PostgreSQL `16.15`, CoreDNS `1.12.3`.

## Run a hub

From the repo root:

```bash
cp .env.example .env
cp deploy/lab/dns/nm.zone.example deploy/lab/dns/nm.zone
```

Set `LAB_BIND` in `.env` to this host's own address. On the mesh VM that is `10.11.66.10`. The names in `nm.zone` stay `100.64.0.1`. Then:

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

The hub runs in a VM on the Proxmox host `void`. Tailscale runs in the VM, as `hub`, at `100.64.0.1`. Caddy listens on that address and on `LAB_BIND`. `deploy/tailscale/` is the desktop rollback. Leave it until the VM is confirmed.

The VM is Debian 13: 2 vCPU, 6 GB RAM, 40 GB disk. Its NIC is `vmbr0`, VLAN tag 66. Address `10.11.66.10/24`, gateway `10.11.66.1`, DNS `9.9.9.9` and `1.1.1.1`. `void` has no address on VLAN 66.

On the switch, tag VLAN 66 on the trunks that already carry 11, 22, 33, 44, and 55. On `void`, add 66 to `vmbr0` `bridge-vids` and apply it.

pfSense interface `igc1.66`, `10.11.66.1/24`. No DHCP. No port forward. Outbound NAT includes `10.11.66.0/24`.

MESH rules, top to bottom:

1. Pass ICMP from MESH to `10.11.66.1`.
2. Block MESH to this firewall on TCP 22, 80, 443, 2222, and 10443.
3. Pass MESH to `9.9.9.9` and `1.1.1.1`, TCP and UDP 53.
4. Block MESH to `10.0.0.0/8`, `172.16.0.0/12`, and `192.168.0.0/16`.
5. Pass MESH to any, TCP 80 and 443.
6. Pass MESH to any, UDP.
7. Pass MESH to any, ICMP.

HOME rules, above the allow-any:

1. Pass HOME to `10.11.66.10` TCP 22.
2. Block HOME to `10.11.66.0/24`.

Install Tailscale 1.102.3 or newer in the VM. Copy `/var/lib/tailscale-nm/tailscaled.state` from the desktop into the VM state directory. Do not log in as a new node, and do not log the old one out. Start Tailscale, confirm the address is `100.64.0.1`, then run `tailscale serve reset`.

Set `LAB_BIND=10.11.66.10`. Copy Postgres, the pict-rs data, `deploy/lab/acme/`, and `.env` from container 106. `.env` stays out of git. Start with `scripts/mesh-up.sh`.

The public A records stay `100.64.0.1`. Set their TTL to 300 before the cutover.

Rollback: stop Tailscale on the VM, start the stack on container 106, and start `tailscaled-nm` on the desktop.

## Run the login server

`deploy/headscale/` is a Compose file for a host with a public address behind Traefik. Relays stay Tailscale's. `policy.hujson` is the access policy: every member can reach every other member, and exit routes are never approved.

## Layout

- `deploy/headscale/`: the login server and the access policy
- `deploy/tailscale/`: desktop rollback, until the VM is confirmed
- `deploy/lab/compose.yml`: Caddy for the portal
- `deploy/lab/hub.yml`: the hub
- `deploy/lab/names.yml`: the name gate (Caddy on 80 and 443), the `.nm` DNS server, and the crawler
- `deploy/lab/square.yml`: Newmarket Square. Lemmy, Photon, pict-rs for pictures, PostgreSQL, and a Caddy gate on 8094. pict-rs strips location data from uploaded photos.
- `portal/`: the portal and the directory
- `hub/`: the hub and its search page
- `scripts/crawl.py`: walks every HTTPS name in the `.nm` zone every minute and rewrites the search index when a page changes. A page joins a directory category with `<meta name="mesh-category" content="Name">`.
- `scripts/square-seed.py`: site settings and starter communities for the Square
- `scripts/mesh-up.sh`: starts the stack after `100.64.0.1` is up

## Stop

```bash
scripts/lab.sh down
```

## License

Code and configuration: [GNU AGPL-3.0](LICENSE). If you run a modified version for other people, you publish your changes.

Documentation and house rules (`*.md`): [CC BY-SA 4.0](LICENSES/CC-BY-SA-4.0.txt).
