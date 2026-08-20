#!/usr/bin/env bash
set -euo pipefail

repo="${JTENNANT_AGENT_CONFIG_REPO:-https://github.com/johnmatthewtennant/jtennant-agent-config.git}"
dir="${JTENNANT_AGENT_CONFIG_DIR:-$HOME/Development/jtennant-agent-config}"
claude_skills_dir="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
agents_skills_dir="${AGENTS_SKILLS_DIR:-$HOME/.agents/skills}"
plugin="jtennant-agent-config"
mode="${1:-all}"

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
brew_ensure() { brew list --formula "$1" >/dev/null 2>&1 || brew install "johnmatthewtennant/tap/$1"; }
link() {
  local src="$1" dest="$2"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    [ -L "$dest" ] || { echo "exists, not a symlink: $dest" >&2; exit 1; }
    rm "$dest"
  fi
  ln -s "$src" "$dest"
}

need git
mkdir -p "$(dirname "$dir")" "$claude_skills_dir" "$agents_skills_dir"

if [ "$mode" != "--links-only" ]; then
  need brew
  # Refresh Homebrew and all taps once up front so upgrades see new releases,
  # then disable per-command auto-update so the installs below stay fast.
  brew update || true
  export HOMEBREW_NO_AUTO_UPDATE=1
  brew tap johnmatthewtennant/tap >/dev/null
  brew_ensure reminderkit-cli
  brew_ensure notekit-cli
  brew upgrade reminderkit-cli notekit-cli || true
  # brew-prefixed paths so stale copies earlier on PATH can't run instead;
  # no target flag = install to both ~/.claude/skills and ~/.agents/skills
  "$(brew --prefix)/bin/reminderkit" install-skill --force
  "$(brew --prefix)/bin/notekit" install-skill --force

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
fi

[ -d "$dir/.git" ] || { echo "missing git checkout: $dir" >&2; exit 1; }

# Claude reads the repo as a plugin
link "$dir" "$claude_skills_dir/$plugin"

# Codex doesn't understand the plugin layout, so link each skill individually
for skill in "$dir"/skills/*/; do
  link "${skill%/}" "$agents_skills_dir/$(basename "$skill")"
done

# prune broken symlinks into the repo (skills removed/renamed, repo relocated)
for d in "$claude_skills_dir" "$agents_skills_dir"; do
  for l in "$d"/*; do
    [ -L "$l" ] && [ ! -e "$l" ] || continue
    case "$(readlink "$l")" in "$dir"|"$dir"/*) rm "$l" ;; esac
  done
done

echo "claude plugin: $claude_skills_dir/$plugin"
echo "codex skills: $(cd "$dir/skills" && ls | tr '\n' ' ')"
