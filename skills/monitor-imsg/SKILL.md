---
name: monitor-imsg
description: Watch a single iMessage conversation from Claude Code using the `imsg` CLI and Monitor tool, and send replies with `imsg send`. Use when the user wants Claude to monitor, watch, listen to, follow, or reply in an iMessage conversation, including self conversations.
allowed-tools:
  - Monitor
  - Bash(brew install steipete/formulae/imsg)
  - Bash(imsg chats *)
  - Bash(imsg watch *)
  - Bash(imsg send *)
---

# Monitor iMessage

Use this for a single-conversation iMessage monitor in Claude Code.

## Prerequisites

Install `imsg` if it is not already available:

```bash
brew install steipete/formulae/imsg
```

If macOS prompts for permissions, tell the user to grant their Terminal Full Disk Access and Messages automation access.

## Choose the conversation

Participant matching is convenient when you are okay watching any chat that includes that email or phone number; it can include group chats with that participant:

```bash
imsg watch --participants person@example.com
imsg watch --participants +15551234567
```

When the user needs exactly one conversation, list recent chats and use the chat row id:

```bash
imsg chats --limit 20
imsg watch --chat-id <ROWID>
```

## Start the monitor

Start a persistent Monitor so each incoming iMessage line appears as an event in Claude Code.

Participant form:

```python
Monitor(
  persistent=True,
  command="imsg watch --participants person@example.com"
)
```

Chat id form:

```python
Monitor(
  persistent=True,
  command="imsg watch --chat-id <ROWID>"
)
```

Keep the monitor command narrow to one conversation so Claude only sees the intended message stream.

## Replying

By participant:

```bash
imsg send --to person@example.com --text "hello"
```

By chat row id:

```bash
imsg send --chat-id <ROWID> --text "hello"
```

## Self conversation mode

Use this when the agent and user both send and receive iMessages from the same account, for example from `user@example.com` to `user@example.com`. This is common when the agent operates the user's computer and the user messages the agent from their phone.

Do not rely on `is_from_me`, `incoming`, or message direction to distinguish speakers. Instead, use an exact chat row id and have the agent prefix its own replies, for example:

```bash
imsg send --chat-id <ROWID> --text "Agent: <reply>"
```

Ignore monitor events that start with the agent prefix so the agent does not reply to itself.

## Streaming vs polling clients

Claude Code supports streaming via Monitor. Use the persistent Monitor shown above: each incoming message arrives as an event, and the agent may end its turn between messages.

Non-streaming clients (Codex, Goose) have no Monitor tool. Run `imsg watch` as a foreground command instead; it blocks until messages arrive. If the harness enforces a command timeout, re-run it in a loop, passing the last seen rowid so repeated runs do not replay messages:

```bash
imsg watch --chat-id <ROWID> --since-rowid <N>
```

Non-streaming clients must NEVER END TURN WHILE WAITING FOR A MESSAGE. Otherwise the conversation stalls and the user's reply goes unanswered. Poll continuously: keep re-running the watch command until new input arrives, respond, then resume polling.
