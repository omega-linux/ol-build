#!/bin/bash
build_deps=()
for p in make gettext; do
    dpkg-query -W -f='${db:Status-Status}' "${p}" 2>/dev/null | grep -qx installed || build_deps+=("${p}")
done
apt-get install -y --no-install-recommends make gettext
make -C src clean deb
apt-get install -y --no-install-recommends ./src/build/ol-settings_*_all.deb
[[ ${#build_deps[@]} -eq 0 ]] || apt-mark auto "${build_deps[@]}" >/dev/null
