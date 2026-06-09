# agent-toolkit

Personal Claude Code skills and agent configuration that can be installed with one command.

## Install or update

```bash
curl -fsSL https://raw.githubusercontent.com/johnmatthewtennant/agent-toolkit/main/install.sh | bash
```

The installer clones or updates this repo at:

```text
~/.local/share/agent-toolkit
```

Then it symlinks skills into:

```text
~/.claude/skills
```

Re-run the install command anytime to pull the latest version and refresh symlinks.

## Safety behavior

The installer is conservative:

- It updates the local clone with `git pull --ff-only`.
- It only manages skill symlinks that point into the local `agent-toolkit` checkout.
- If a skill directory already exists and is not managed by this repo, it skips it and prints a warning.
- It does not install secrets or machine-specific settings.

## Local development

This repo lives at:

```text
/Volumes/1TBSD/Development/agent-toolkit
```

It is symlinked into:

```text
~/Development/agent-toolkit
```

Skills live under `skills/`.
