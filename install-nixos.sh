#!/bin/sh
set -eu

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but was not found in PATH." >&2
    exit 1
fi

find_nix_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            python_path=$(command -v "$candidate")
            resolved_path=$(readlink -f "$python_path" 2>/dev/null || printf '%s\n' "$python_path")
            case "$resolved_path" in
                /nix/store/*)
                    printf '%s\n' "$resolved_path"
                    return 0
                    ;;
            esac
        fi
    done

    return 1
}

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! nix_python=$(find_nix_python); then
    cat >&2 <<'EOF'
Could not find a Nix-provided Python interpreter in PATH.

Install one first, for example:
  nix shell nixpkgs#uv nixpkgs#python3 --command sh ./install-nixos.sh
EOF
    exit 1
fi

exec env UV_NO_MANAGED_PYTHON=1 uv tool install --python "$nix_python" "$@" "$repo_dir"