#!/usr/bin/env bash
set -euo pipefail

authorized_key_source=/run/secrets/dev_authorized_keys
authorized_key_target=/home/dev/.ssh/authorized_keys

if [[ ! -s "${authorized_key_source}" ]]; then
    printf 'Missing or empty SSH public-key file: %s\n' \
        "${authorized_key_source}" >&2
    exit 1
fi

install -d -m 0700 -o dev -g dev /home/dev/.ssh
install -m 0600 -o dev -g dev \
    "${authorized_key_source}" \
    "${authorized_key_target}"

# Generate per-container host keys rather than baking one shared host identity
# into the image.
ssh-keygen -A

/usr/sbin/sshd -t

exec "$@"