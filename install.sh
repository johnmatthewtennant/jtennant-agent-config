#!/usr/bin/env bash
set -euo pipefail

repo="${JTENNANT_AGENT_CONFIG_REPO:-https://github.com/johnmatthewtennant/jtennant-agent-config.git}"
dir="${JTENNANT_AGENT_CONFIG_DIR:-$HOME/.local/share/jtennant-agent-config}"
skills_dir="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
owned_link() { [ -L "$1" ] && case "$(readlink "$1")" in "$dir"/*) true;; *) false;; esac; }

need git
mkdir -p "$(dirname "$dir")" "$skills_dir"

if [ -d "$dir/.git" ]; then
  git -C "$dir" pull --ff-only
elif [ -e "$dir" ]; then
  echo "exists, not a git checkout: $dir" >&2
  exit 1
else
  git clone "$repo" "$dir"
fi

for skill in "$dir"/skills/*; do
  [ -d "$skill" ] || continue
  name=$(basename "$skill")
  target="$skills_dir/$name"
  if [ -e "$target" ] || [ -L "$target" ]; then
    if owned_link "$target"; then rm "$target"; else echo "skip: $name" >&2; continue; fi
  fi
  ln -s "$skill" "$target"
  echo "skill: $name"
done
