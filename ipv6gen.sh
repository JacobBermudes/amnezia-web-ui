mkdir -p ygg-data
docker run --rm ghcr.io/yggdrasil-network/yggdrasil:latest -genconf > ygg-data/yggdrasil.conf
grep IPv6Address ygg-data/yggdrasil.conf