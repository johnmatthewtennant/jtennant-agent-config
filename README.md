# jtennant-agent-config

Personal agent config with shared skills and setup, installed for both Claude Code and Codex.

## Install/update

```bash
curl -fsSL https://raw.githubusercontent.com/johnmatthewtennant/jtennant-agent-config/main/install.sh | bash
```

Installs CLIs and runs their skill installers (which target both `~/.claude/skills` and `~/.agents/skills`), clones to `~/Development/jtennant-agent-config`, symlinks the plugin to `~/.claude/skills/jtennant-agent-config` for Claude Code, and symlinks each skill into `~/.agents/skills/` for Codex.
