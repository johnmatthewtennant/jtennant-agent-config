---
name: browser-control
description: Control Google Chrome from Claude Code. Use for browsing, debugging, navigating, filling forms, screenshots, scraping, testing web apps, CDP, accessibility snapshots, JavaScript evaluation, or AppleScript control of Chrome.
---

# Browser control

Use Chrome. Prefer a copied side-car profile plus CDP for automation. Use AppleScript only when CDP is not usable.

## Install

```bash
command -v agent-browser >/dev/null 2>&1 || brew install agent-browser
```

## Launch side-car Chrome

```bash
PORT=$(python3 - <<'PY'
import random
print(random.randint(20000, 60999))
PY
)
while curl -fsS "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; do PORT=$((PORT+1)); done
PROFILE_DIR="$HOME/.agent-browser/chrome-cdp-$PORT"
rm -rf "$PROFILE_DIR"
mkdir -p "$PROFILE_DIR"
rsync -a --ignore-errors \
  --exclude='Singleton*' --exclude='lockfile' \
  --exclude='*Cache*' --exclude='*GPUCache*' --exclude='*.log' \
  "$HOME/Library/Application Support/Google/Chrome/" \
  "$PROFILE_DIR/" 2>/dev/null || true

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run >/tmp/chrome-cdp-$PORT.log 2>&1 &

sleep 3
curl -s "http://127.0.0.1:$PORT/json/version"
```

## Control with agent-browser

Use a session name tied to the port.

```bash
agent-browser --session chrome-$PORT --cdp $PORT open https://example.com
agent-browser --session chrome-$PORT --cdp $PORT wait --load networkidle
agent-browser --session chrome-$PORT --cdp $PORT snapshot -i --json
agent-browser --session chrome-$PORT --cdp $PORT click @e1
agent-browser --session chrome-$PORT --cdp $PORT fill @e2 "text"
agent-browser --session chrome-$PORT --cdp $PORT eval --stdin <<'EOF'
document.title
EOF
```

Prefer snapshots over screenshots. Use screenshots only for visual rendering or inaccessible content.

## Raw CDP fallback

```bash
curl -s http://127.0.0.1:$PORT/json/version
curl -s http://127.0.0.1:$PORT/json
curl -s http://127.0.0.1:$PORT/json/protocol
```

Open the target `webSocketDebuggerUrl` and send CDP messages. Useful domains: `Runtime`, `Page`, `DOM`, `Accessibility`, `Input`, `Network`.

## AppleScript for running Chrome

Use this only when CDP is not usable.

```applescript
tell application "Google Chrome"
  activate
  open location "https://example.com"
  execute javascript "document.title" in active tab of front window
end tell
```

If JavaScript Apple Events fail, enable Chrome's **Allow JavaScript from Apple Events** and macOS Developer Tools access for the terminal.

## Gotchas

- Copy the real Chrome profile. Empty profiles cause setup noise.
- Use a unique port and `--user-data-dir` per side-car.
- Do not kill the user's main Chrome.
- Use `--cdp <port>` instead of relying on saved agent-browser session state.
