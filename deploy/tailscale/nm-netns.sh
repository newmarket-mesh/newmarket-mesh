#!/bin/sh
# A second Tailscale node for the community tailnet.
# It can reach the hub and the public internet. It cannot open the rest of the LAN.
# HUB_IP is the hub's LAN address, set in /etc/default/nm-netns.
set -eu
: "${HUB_IP:?set HUB_IP in /etc/default/nm-netns}"
if ! ip netns list | awk '{print $1}' | grep -qx nm; then
  ip netns add nm
fi
if ! ip link show nm-host >/dev/null 2>&1; then
  ip link add nm-host type veth peer name nm-ns
  ip link set nm-ns netns nm
fi
ip addr replace 172.31.250.1/30 dev nm-host
ip link set nm-host up
ip netns exec nm ip addr replace 172.31.250.2/30 dev nm-ns
ip netns exec nm ip link set nm-ns up
ip netns exec nm ip link set lo up
ip netns exec nm ip route replace default via 172.31.250.1
ip netns exec nm ip route replace "$HUB_IP/32" via 172.31.250.1
ip netns exec nm sysctl -q -w net.ipv4.ip_forward=1
mkdir -p /etc/netns/nm /var/lib/tailscale-nm
printf 'nameserver 9.9.9.9\n' > /etc/netns/nm/resolv.conf
# Without this, lookups in the namespace go through the host's systemd-resolved
# and the house resolver instead of the resolv.conf above.
printf 'passwd: files\ngroup: files\nshadow: files\nhosts: files dns\nnetworks: files\nprotocols: files\nservices: files\n' > /etc/netns/nm/nsswitch.conf
chmod 0750 /var/lib/tailscale-nm
nft delete table inet nmbridge 2>/dev/null || true
nft -f - <<EOF
table inet nmbridge {
	chain forward {
		type filter hook forward priority 0; policy accept;
		ip saddr 172.31.250.2 ip daddr $HUB_IP tcp dport { 80, 443 } accept
		ip saddr 172.31.250.2 ip daddr $HUB_IP udp dport 53 accept
		ip saddr 172.31.250.2 ip daddr 10.0.0.0/8 drop
		ip saddr 172.31.250.2 ip daddr 172.16.0.0/12 drop
		ip saddr 172.31.250.2 ip daddr 192.168.0.0/16 drop
	}

	chain postrouting {
		type nat hook postrouting priority 100; policy accept;
		ip saddr 172.31.250.2 masquerade
	}
}
EOF
# Docker and the host firewall drop forwarded traffic unless it is allowed here.
while iptables -D FORWARD -s 172.31.250.2 -j NM-BRIDGE 2>/dev/null; do :; done
iptables -N NM-BRIDGE 2>/dev/null || iptables -F NM-BRIDGE
iptables -A NM-BRIDGE -d "$HUB_IP" -p tcp -m multiport --dports 80,443 -j ACCEPT
iptables -A NM-BRIDGE -d "$HUB_IP" -p udp --dport 53 -j ACCEPT
iptables -A NM-BRIDGE -d 10.0.0.0/8 -j DROP
iptables -A NM-BRIDGE -d 172.16.0.0/12 -j DROP
iptables -A NM-BRIDGE -d 192.168.0.0/16 -j DROP
iptables -A NM-BRIDGE -j ACCEPT
iptables -C FORWARD -d 172.31.250.2 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || iptables -I FORWARD 1 -d 172.31.250.2 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -C FORWARD -s 172.31.250.2 -j NM-BRIDGE 2>/dev/null || iptables -I FORWARD 2 -s 172.31.250.2 -j NM-BRIDGE
