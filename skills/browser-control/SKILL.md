---
name: browser-control
description: Control Google Chrome for browsing, debugging, navigation, form entry, screenshots, scraping, testing web apps, CDP, accessibility snapshots, and JavaScript evaluation.
---

# Browser control

Use Google Chrome. Prefer a copied, **temporary** side-car profile plus CDP for automation.

## Install

```bash
command -v agent-browser >/dev/null 2>&1 || brew install agent-browser
```

## Launch side-car Chrome

Create a temporary copied profile, then start Chrome with a unique CDP port.

```bash
PORT=$(python3 - <<'PY'
import random
print(random.randint(20000, 60999))
PY
)
while curl -fsS "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; do PORT=$((PORT + 1)); done
PROFILE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/chrome-cdp-$PORT.XXXXXX")
rsync -a --ignore-errors \
  --exclude='Singleton*' --exclude='lockfile' \
  --exclude='*Cache*' --exclude='*GPUCache*' --exclude='*.log' \
  "$HOME/Library/Application Support/Google/Chrome/" \
  "$PROFILE_DIR/" 2>/dev/null || true

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run >"${TMPDIR:-/tmp}/chrome-cdp-$PORT.log" 2>&1 &

sleep 3
curl -s "http://127.0.0.1:$PORT/json/version"
```

## Control with agent-browser

`agent-browser` uses CDP under the hood. Use a session name tied to the port.

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

## Clean up

After the final browser command, close the side-car and remove its temporary profile.

```bash
pkill -f -- "--user-data-dir=$PROFILE_DIR" 2>/dev/null || true
rm -rf "$PROFILE_DIR"
```

## Raw CDP fallback

```bash
curl -s http://127.0.0.1:$PORT/json/version
curl -s http://127.0.0.1:$PORT/json
curl -s http://127.0.0.1:$PORT/json/protocol
```

Open the target `webSocketDebuggerUrl` and send CDP messages. Useful domains: `Runtime`, `Page`, `DOM`, `Accessibility`, `Input`, `Network`.

## Gotchas

- Copy the real Chrome profile. Empty profiles cause setup noise.
- Use a temporary profile and clean it up after the final browser command.
- For a session that must survive across tasks, save only the necessary auth state with `agent-browser state save ~/.agent-browser/auth-<environment>-<account>.json`; do not preserve the whole browser profile.
- Use a unique port and `--user-data-dir` per side-car.
- Do not kill the user's main Chrome.
- Use `--cdp <port>` instead of relying on saved agent-browser session state.

## Network requests for repeatable automation

Browser automation is fine for a first pass through a flow. When authoring a reusable skill or script, inspect the page's network requests and prefer reproducing the underlying requests where practical. This usually creates a faster and more repeatable workflow than clicking through the UI.

If the requests are authenticated, capture the required token, cookie, or header from the browser session and use it explicitly when reproducing the request.
