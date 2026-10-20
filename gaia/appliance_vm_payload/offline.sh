#!/bin/sh
set -eu
/usr/sbin/nft -f /core/nftables.conf
for path in /sys/class/net/*; do
    name=${path##*/}
    [ "$name" = lo ] || /usr/sbin/ip link set dev "$name" down
done
