#!/bin/bash
mkdir -p ygg-data
docker run --rm jacobbermudes/yggdrasil:latest yggdrasil -genconf > ygg-data/yggdrasil.conf
docker run --rm -v $PWD/ygg-data/yggdrasil.conf:/yggdrasil.conf jacobbermudes/yggdrasil:latest yggdrasil -useconffile /yggdrasil.conf -address