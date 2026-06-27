#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

exec sh "$repo_dir/install-nixos.sh" --force "$@"