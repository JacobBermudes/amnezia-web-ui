#!/bin/sh

yggdrasil -useconffile /etc/yggdrasil/yggdrasil.conf &
sleep 2

SUBNET=$(yggdrasil -useconffile /etc/yggdrasil/yggdrasil.conf -subnet | tr -d '\n')
PREFIX=$(echo "$SUBNET" | cut -d: -f1-4)
NAT64_PREFIX="${PREFIX}:64:ff9b::/96"

echo "[NAT64] Calculated Prefix: $NAT64_PREFIX"

mkdir -p /etc/coredns
cat <<EOF > /etc/coredns/Corefile
.:53 {
    forward . 8.8.8.8 1.1.1.1
    dns64 {
        prefix $NAT64_PREFIX
    }
}
EOF

coredns -conf /etc/coredns/Corefile &

cat <<EOF > /etc/tayga.conf
tun-device nat64
ipv4-addr 10.10.10.1
prefix $NAT64_PREFIX
dynamic-pool 10.10.10.0/24
data-dir /var/db/tayga
EOF

mkdir -p /var/db/tayga
tayga --mktun
ip link set nat64 up

ip addr add 10.10.10.1 dev nat64
ip route add 10.10.10.0/24 dev nat64
ip -6 route add "$NAT64_PREFIX" dev nat64

iptables -t nat -A POSTROUTING -s 10.10.10.0/24 -j MASQUERADE

socat TCP6-LISTEN:80,fork,reuseaddr TCP4:sb-web-ui:80 &

exec tayga -d