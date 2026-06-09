#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${AGENT_TOOLKIT_REPO:-https://github.com/johnmatthewtennant/agent-toolkit.git}"
INSTALL_DIR="${AGENT_TOOLKIT_INSTALL_DIR:-$HOME/.local/share/agent-toolkit}"
SKILLS_TARGET="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

log() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'error: required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

is_ours_symlink() {
  local target=$1
  [ -L "$target" ] || return 1
  local resolved
  resolved=$(readlink "$target")
  case "$resolved" in
    "$INSTALL_DIR"/*) return 0 ;;
    *) return 1 ;;
  esac
}

install_repo() {
  require_cmd git
  mkdir -p "$(dirname "$INSTALL_DIR")"

  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
  elif [ -e "$INSTALL_DIR" ]; then
    printf 'error: %s exists but is not a git checkout\n' "$INSTALL_DIR" >&2
    exit 1
  else
    log "Cloning $REPO_URL to $INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi
}

install_skills() {
  local source_dir="$INSTALL_DIR/skills"
  if [ ! -d "$source_dir" ]; then
    warn "no skills directory found at $source_dir"
    return 0
  fi

  mkdir -p "$SKILLS_TARGET"

  local installed=0
  local skipped=0
  for skill in "$source_dir"/*; do
    [ -d "$skill" ] || continue
    local name
    name=$(basename "$skill")
    local target="$SKILLS_TARGET/$name"

    if [ -e "$target" ] || [ -L "$target" ]; then
      if is_ours_symlink "$target"; then
        rm "$target"
      else
        warn "skipping $name because $target already exists and is not managed by agent-toolkit"
        skipped=$((skipped + 1))
        continue
      fi
    fi

    ln -s "$skill" "$target"
    log "Installed skill: $name"
    installed=$((installed + 1))
  done

  log "Skills installed or refreshed: $installed"
  log "Skills skipped: $skipped"
}

main() {
  install_repo
  install_skills
  log "Done. Re-run this installer anytime to update agent-toolkit."
}

main "$@"
