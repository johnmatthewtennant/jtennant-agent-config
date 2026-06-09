#!/usr/bin/env bash
set -euo pipefail

repo="${JTENNANT_AGENT_CONFIG_REPO:-https://github.com/johnmatthewtennant/jtennant-agent-config.git}"
dir="${JTENNANT_AGENT_CONFIG_DIR:-$HOME/Development/jtennant-agent-config}"
skills_dir="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
plugin="jtennant-agent-config"

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
brew_ensure() { brew list --formula "$1" >/dev/null 2>&1 || brew install "johnmatthewtennant/tap/$1"; }

need git
need brew
mkdir -p "$(dirname "$dir")" "$skills_dir"

export HOMEBREW_NO_AUTO_UPDATE=1
brew tap johnmatthewtennant/tap >/dev/null
brew_ensure reminderkit-cli
brew_ensure notekit-cli
brew upgrade reminderkit-cli notekit-cli || true
reminderkit install-skill --claude --force
notekit install-skill --claude --force

if [ -d "$dir/.git" ]; then
  if git -C "$dir" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    git -C "$dir" pull --ff-only
  fi
elif [ -e "$dir" ]; then
  echo "exists, not a git checkout: $dir" >&2
  exit 1
else
  git clone "$repo" "$dir"
fi

target="$skills_dir/$plugin"
if [ -e "$target" ] || [ -L "$target" ]; then
  [ -L "$target" ] || { echo "exists, not a symlink: $target" >&2; exit 1; }
  rm "$target"
fi
ln -s "$dir" "$target"
echo "plugin: $plugin"
