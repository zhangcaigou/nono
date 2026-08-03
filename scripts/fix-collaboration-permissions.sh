#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
current_user="$(id -un)"

# A user may change ACLs only on files they own. Each collaborator runs this
# after creating/replacing files; existing default ACLs cover normal creation,
# while these commands also repair restrictive modes such as mktemp/chmod 600.
find "${project_root}" -xdev \( -type d ! -executable -prune \) -o \
    \( -user "${current_user}" -type f ! -perm /111 \
    -exec setfacl -m u:zyf:rw,u:qpd:rw,u:mph:rw,m::rw {} + \)
find "${project_root}" -xdev \( -type d ! -executable -prune \) -o \
    \( -user "${current_user}" -type f -perm /111 \
    -exec setfacl -m u:zyf:rwx,u:qpd:rwx,u:mph:rwx,m::rwx {} + \)
find "${project_root}" -xdev \( -type d ! -executable -prune \) -o \
    \( -user "${current_user}" -type d -exec setfacl \
        -m u:zyf:rwx,u:qpd:rwx,u:mph:rwx,m::rwx \
        -m d:u:zyf:rwx,d:u:qpd:rwx,d:u:mph:rwx,d:m::rwx {} + \)

echo "Collaboration ACLs repaired for files owned by ${current_user}"
