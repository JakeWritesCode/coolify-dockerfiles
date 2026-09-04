#!/bin/sh
set -eu

: "${HERMES_HOME:=/home/hermes/.hermes}"
source_dir=/usr/local/share/hermes-plugins/usage-meter
target_dir="$HERMES_HOME/plugins/usage-meter"

if [ ! -f "$source_dir/plugin.yaml" ]; then
    echo "usage-meter plugin manifest missing from image" >&2
    exit 1
fi

mkdir -p "$HERMES_HOME/plugins"
rm -rf "$target_dir"
cp -a "$source_dir" "$target_dir"
chmod -R a+rX "$target_dir"

exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
