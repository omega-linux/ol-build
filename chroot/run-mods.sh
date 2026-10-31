#!/bin/bash
set -Eeuo pipefail
trap 'rc=$?; printf "\e[1;31mERROR:\e[0m command failed (exit %s) at %s:%s: %s\n" "${rc}" "${BASH_SOURCE[0]:-$0}" "${LINENO}" "${BASH_COMMAND}" >&2; exit "${rc}"' ERR

set -a
source "${ROOT_DIR}/config.sh"
set +a
export DEBIAN_FRONTEND=noninteractive

mods_dir="${ROOT_DIR}/mods"

log()  { printf '\e[1;32m  ->\e[0m %s\n' "$*"; }
warn() { printf '\e[1;33mWARN:\e[0m %s\n' "$*" >&2; }
die()  { printf '\e[1;31mERROR:\e[0m %s\n' "$*" >&2; exit 1; }

mod_display_name() {
    local dir=$1 name=""
    if [[ -f ${mods_dir}/${dir}/info ]]; then
        name=$(sed -n 's/^[[:space:]]*name[[:space:]]*:[[:space:]]*//p' "${mods_dir}/${dir}/info" | head -n1)
        name=${name%"${name##*[![:space:]]}"}
    fi
    if [[ -z ${name} ]]; then
        warn "mod '${dir}' has no name in ${dir}/info, using the directory name"
        name=${dir}
    fi
    printf '%s\n' "${name}"
}

mods=()
while IFS= read -r line || [[ -n ${line} ]]; do
    line=${line%%#*}
    line=${line#"${line%%[![:space:]]*}"}
    line=${line%"${line##*[![:space:]]}"}
    [[ -n ${line} ]] || continue
    [[ ${line} != */* && ${line} != .* ]] || die "invalid mod name in order: '${line}'"
    [[ -f ${mods_dir}/${line}/do.sh ]] || die "mod '${line}' has no do.sh (${mods_dir}/${line}/do.sh)"
    mods+=("${line}")
done < "${mods_dir}/order"

mod_env="${ROOT_DIR}/mod-env.sh"
cat > "${mod_env}" <<'EOF'
unset BASH_ENV
set -Ee -o pipefail
trap 'rc=$?; printf "\e[1;31mERROR:\e[0m command failed (exit %s) at %s:%s: %s\n" "${rc}" "${BASH_SOURCE[0]:-do.sh}" "${LINENO}" "${BASH_COMMAND}" >&2; exit "${rc}"' ERR
EOF

# Mods are free to install packages, so start with fresh package lists.
apt-get update

for dir in "${mods[@]}"; do
    name=$(mod_display_name "${dir}")
    log "Processing \"${name}\""
    rc=0
    (
        cd "${mods_dir}/${dir}"
        MOD_NAME=${dir} MOD_DIR=${mods_dir}/${dir} BASH_ENV=${mod_env} bash ./do.sh
    ) || rc=$?
    [[ ${rc} -eq 0 ]] || die "mod \"${name}\" (${dir}) failed with exit code ${rc}, stopping the build"
    log "Done processing \"${name}\""
done
