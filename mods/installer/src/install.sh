#!/bin/bash
set -Eeuo pipefail
dest=${1:-}
src=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lib=${dest}/usr/lib/system-installer
install -Dm755 "${src}/main.py" "${lib}/main.py"
for f in backend.py partitioning.py i18n.py util.py; do
    install -Dm644 "${src}/${f}" "${lib}/${f}"
done
install -Dm755 "${src}/cleanup.sh" "${lib}/cleanup.sh"
install -d "${lib}/po"
install -m644 "${src}"/po/*.po "${lib}/po/"
install -Dm755 "${src}/system-installer" "${dest}/usr/bin/system-installer"
install -Dm644 "${src}/system-installer.desktop" "${dest}/usr/share/applications/system-installer.desktop"
install -Dm644 "${src}/org.systeminstaller.policy" "${dest}/usr/share/polkit-1/actions/org.systeminstaller.policy"
