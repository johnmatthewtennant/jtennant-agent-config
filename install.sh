#!/usr/bin/env bash
set -euo pipefail

# Compatibility bootstrap for the former public repository name. Keep this
# file available so existing raw.githubusercontent.com install commands migrate
# instead of depending on a GitHub redirect.
repo="${JTENNANT_AGENT_CONFIG_REPO:-https://github.com/johnmatthewtennant/jtennant-agent-config-public.git}"
dir="${JTENNANT_AGENT_CONFIG_DIR:-$HOME/Development/jtennant-agent-config-public}"

command -v git >/dev/null || { echo 'missing: git' >&2; exit 1; }
mkdir -p "$(dirname "$dir")"

if [[ -d "$dir/.git" ]]; then
  git -C "$dir" remote set-url origin "$repo"
  git -C "$dir" pull --ff-only
elif [[ -e "$dir" ]]; then
  echo "exists, not a git checkout: $dir" >&2
  exit 1
else
  git clone "$repo" "$dir"
fi

exec "$dir/install.sh" "$@"
