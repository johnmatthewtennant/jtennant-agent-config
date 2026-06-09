#!/usr/bin/env bash
set -euo pipefail

repo="${JTENNANT_AGENT_CONFIG_REPO:-https://github.com/johnmatthewtennant/jtennant-agent-config.git}"
dir="${JTENNANT_AGENT_CONFIG_DIR:-$HOME/.local/share/jtennant-agent-config}"
skills_dir="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
plugin="jtennant-agent-config"

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
owned_link() { [ -L "$1" ] && case "$(readlink "$1")" in "$dir"|"$dir"/*) true;; *) false;; esac; }
brew_ensure() { brew list --formula "$1" >/dev/null 2>&1 || brew install "johnmatthewtennant/tap/$1"; }

need git
need brew
mkdir -p "$(dirname "$dir")" "$skills_dir"

brew tap johnmatthewtennant/tap >/dev/null
brew_ensure reminderkit-cli
brew_ensure notekit-cli
brew upgrade reminderkit-cli notekit-cli || true
reminderkit install-skill --claude --force
notekit install-skill --claude --force

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
  old="$skills_dir/$(basename "$skill")"
  owned_link "$old" && rm "$old"
done

target="$skills_dir/$plugin"
if [ -e "$target" ] || [ -L "$target" ]; then
  if owned_link "$target"; then rm "$target"; else echo "skip plugin: $target exists" >&2; exit 1; fi
fi
ln -s "$dir" "$target"
echo "plugin: $plugin"
