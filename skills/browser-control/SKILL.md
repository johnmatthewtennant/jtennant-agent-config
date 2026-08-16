---
name: browser-control
description: Control Google Chrome or other Chromium-based browsers. Use for browsing, debugging, navigating, filling forms, screenshots, scraping, testing web apps, CDP, accessibility snapshots, JavaScript evaluation, or AppleScript control of Chrome.
---

# Browser control

Use Chrome. Prefer a copied, **temporary** side-car profile plus CDP for automation. Use AppleScript only when CDP is not usable.

## Install

```bash
command -v agent-browser >/dev/null 2>&1 || brew install agent-browser
```

## Launch side-car Chrome

Use the included helper. It makes a temporary copied profile, reaps abandoned
ones first, starts Chrome, and prints the exact connection details as JSON.

```bash
/Users/jtennant/.agents/skills/browser-control/scripts/agent-browser-sidecar launch
# Example output:
# {"port":34567,"session":"chrome-34567","profile_dir":"/tmp/agent-browser-profiles/chrome-cdp-34567.abcd12","pid":45678}
```

## Control with agent-browser

`agent-browser` uses CDP under the hood. Use a session name tied to the port.

```bash
agent-browser --session "$SESSION" --cdp "$PORT" open https://example.com
agent-browser --session "$SESSION" --cdp "$PORT" wait --load networkidle
agent-browser --session "$SESSION" --cdp "$PORT" snapshot -i --json
agent-browser --session "$SESSION" --cdp "$PORT" click @e1
agent-browser --session "$SESSION" --cdp "$PORT" fill @e2 "text"
agent-browser --session "$SESSION" --cdp "$PORT" eval --stdin <<'EOF'
document.title
EOF
```

Prefer snapshots over screenshots. Use screenshots only for visual rendering or inaccessible content.

## End a temporary side-car session

When the task is complete, close the side-car and remove its profile. Replace
the port with the one printed by the launch step. This is also the fallback
when a task ends before another browser launch gets a chance to reap it.

```bash
/Users/jtennant/.agents/skills/browser-control/scripts/agent-browser-sidecar cleanup --port 34567
```

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

- Copy the real Chrome profile. Empty profiles cause setup noise. The helper creates the copy in the system temporary directory, reaping abandoned profiles whenever another side-car is launched.
- Run the end-of-session cleanup after the final browser command. A shell exit trap is unsuitable here because browser-control commands run in separate shells.
- For a session that must survive across tasks, save only the necessary auth state with `agent-browser state save ~/.agent-browser/auth-<environment>-<account>.json`; do not preserve the whole browser profile.
- Use a unique port and `--user-data-dir` per side-car.
- Do not kill the user's main Chrome.
- Use `--cdp <port>` instead of relying on saved agent-browser session state.

## Network requests for repeatable automation

Browser automation is fine for a first pass through a flow. When authoring a reusable skill or script, inspect the page's network requests and prefer reproducing the underlying requests where practical. This usually creates a faster and more repeatable workflow than clicking through the UI.

If the requests are authenticated, capture the required token, cookie, or header from the browser session and use it explicitly when reproducing the request.
