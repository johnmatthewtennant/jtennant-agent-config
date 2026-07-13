---
name: apple-mail
description: Search, inspect, or mutate Apple Mail on macOS using local files and Mail.app. Use for Apple Mail, Mac Mail, local mail, email bodies, downloaded mail, .emlx files, Mail's Envelope Index, sqlite3, rg, Mail.app search diagnostics, drafting, sending, moving, archiving, flagging, or marking messages read/unread.
---

# Apple Mail local search

Use local Mail files. Avoid AppleScript for broad search: it is slow, timeout-prone, and hides permission/indexing problems.

## Setup

Requires Full Disk Access for the terminal/agent app. If `~/Library/Mail` is empty, unreadable, or SQLite says `unable to open database file`, stop and have the user grant Full Disk Access:

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
```

`bin/mail-find` wraps SQLite or `rg` and returns compact rowid records. `bin/mail-read` consumes rowids for metadata, normalized bodies, excerpts, packets, and coverage. Keep search strategy in the skill/agent; use helpers for stable rowid IO.

## Sync first

Before any Apple Mail operation — search, read, verify, draft, send, delete, or move — force a background Mail sync. Do not foreground Mail just to sync.

```bash
osascript <<'APPLESCRIPT'
tell application "Mail"
  repeat with acct in accounts
    try
      synchronize with acct
    end try
  end repeat
end tell
APPLESCRIPT
```

After syncing, query Mail's Envelope Index or re-run the relevant helper. If waiting for a just-sent external confirmation email, allow a short delay after sync before checking the index.

## What to search

- SQLite metadata: `~/Library/Mail/V*/MailData/Envelope Index`
  - Fast, complete for indexed mail, works even when bodies are not downloaded.
  - Use for sender, subject, date, read/flagged state, mailbox, labels, row ids.
- Body files: `~/Library/Mail/V*/**/*.emlx`
  - Includes `.partial.emlx` files. Partial files can contain useful text, but are best effort.
  - Use for downloaded bodies only.

## Candidate discovery

Thin wrappers preserve the native search shape and add the metadata users usually fetch next:

```bash
MAIL_ROOT="$HOME/Library/Mail/$(ls "$HOME/Library/Mail" | grep '^V[0-9]' | sort -V | tail -1)"
"{{SKILL_DIR}}/bin/mail-find" describe
"{{SKILL_DIR}}/bin/mail-find" sql "s.subject like '%invoice%' collate nocase" --order-by "m.date_received desc" --limit 50
"{{SKILL_DIR}}/bin/mail-find" rg 'contract term' --limit 50
rg -l 'project name' "$MAIL_ROOT" -g '*.emlx' | "{{SKILL_DIR}}/bin/mail-find" paths
```

`mail-find describe` shows SQL aliases, output shape, and common columns. `mail-find rg` returns raw `rg` path/line/text plus rowid, dates, sender, subject, mailbox, path, downloaded, and partial. `mail-find sql` runs a transparent metadata `WHERE` clause with optional raw `--order-by` and adds path/download status. For anything unusual, use SQLite/`rg` directly.

Common metadata filters:

```bash
"{{SKILL_DIR}}/bin/mail-find" sql "m.date_received >= strftime('%s','now','-7 days')" --limit 20
"{{SKILL_DIR}}/bin/mail-find" sql "m.read = 0" --limit 20
"{{SKILL_DIR}}/bin/mail-find" sql "m.read = 0 and m.date_received >= strftime('%s','now','-7 days')" --limit 20
```

Newer than a last-seen row id:

```bash
LAST_SEEN=12345
"{{SKILL_DIR}}/bin/mail-find" sql "m.rowid > $LAST_SEEN" --order-by "m.rowid asc" --limit 50
```

For polling, keep the largest returned `id` as the next `last_seen`.

## Rowid primitives

Use these after metadata/body search identifies relevant row ids:

```bash
"{{SKILL_DIR}}/bin/mail-read" meta 12345 12346
"{{SKILL_DIR}}/bin/mail-read" show 12345 --limit 8000
"{{SKILL_DIR}}/bin/mail-read" excerpt 'contract term' 12345 12346 --context 500
"{{SKILL_DIR}}/bin/mail-read" packet 12345 12346 --term 'contract term' > source-packet.md
"{{SKILL_DIR}}/bin/mail-read" coverage
```

`mail-read` handles `.emlx` byte-count lines, MIME parts, transfer encodings, HTML noise, rowid-to-path mapping, and JSON/markdown output. It accepts `--ids-from -` for pipelines:

```bash
"{{SKILL_DIR}}/bin/mail-find" sql "s.subject like '%invoice%' collate nocase" \
  | jq -r '.[].id' \
  | "{{SKILL_DIR}}/bin/mail-read" packet --ids-from -
```

## Source packet workflow

For evidence work:

1. Search metadata for candidate row ids.
2. Search bodies only for terms metadata misses.
3. Use `mail-read` only on selected row ids.
4. Quote exact headers and excerpts. Do not infer from raw `rg` snippets alone.

Useful targeted query for a date window plus people/subjects:

```bash
MAIL_ROOT="$HOME/Library/Mail/$(ls "$HOME/Library/Mail" | grep '^V[0-9]' | sort -V | tail -1)"
MAIL_DB="$MAIL_ROOT/MailData/Envelope Index"
sqlite3 -readonly -header -csv "$MAIL_DB" <<'SQL'
select m.rowid id,
       datetime(m.date_sent, 'unixepoch') sent,
       coalesce(a.address, '') sender_email,
       coalesce(a.comment, '') sender_name,
       s.subject
from messages m
left join subjects s on s.rowid = m.subject
left join addresses a on a.rowid = m.sender
where m.deleted = 0
  and m.date_sent between strftime('%s','2022-01-01') and strftime('%s','2023-01-01')
  and (s.subject like '%project%' collate nocase
       or a.address like '%example.com%' collate nocase
       or a.comment like '%Example Name%' collate nocase)
order by m.date_sent;
SQL
```

## Coverage

Check indexed mail versus downloaded bodies before claiming body-search completeness:

```bash
python3 - <<'PY'
import sqlite3
from pathlib import Path
root = Path.home() / 'Library/Mail'
mail_root = root / sorted(p.name for p in root.iterdir() if p.name.startswith('V'))[-1]
con = sqlite3.connect(f'file:{mail_root / "MailData/Envelope Index"}?mode=ro', uri=True)
indexed = con.execute('select count(*) from messages where deleted=0').fetchone()[0]
full = partial = 0
for p in mail_root.rglob('*.emlx'):
    partial += '.partial.' in p.name
    full += '.partial.' not in p.name
print({'indexed': indexed, 'local_total': full + partial, 'full': full, 'partial': partial})
PY
```

## Mutations

For Apple Mail mutations, use Mail.app APIs, never mutate Mail SQLite or `.emlx` files. Use AppleScript only for exact object deletion or inspection when no Mail AppIntent covers the operation.

### Native reply composer

Before running, verify the original message's row id, account/mailbox, sender, subject, and RFC Message-ID. Tell the user that Mail will open a compose window.

```bash
python3 {{SKILL_DIR}}/bin/mailkit.py \
  reply-composer ORIGINAL_ROW_ID --body-file /path/to/reply.txt
```

This opens a verified native reply composer and leaves it open for review and Mail autosave. Do not run it when another composer with the same reply subject is open.

### Send an open composer

After the user explicitly approves sending, target the exact subject, recipient, and expected body:

```bash
python3 {{SKILL_DIR}}/bin/mailkit.py send-composer \
  --subject 'Re: EXACT SUBJECT' \
  --to 'recipient@example.com' \
  --body-file /path/to/reply.txt
```

This clicks the unique enabled Send button in the matching Mail composer, then verifies that the composer closed, the draft disappeared, and a matching sent message was indexed.

### Revise a reply

Replace the composer rather than updating it in place:

1. Record the stale autosaved draft's exact RFC Message-ID.
2. Close the old composer, choosing Save if Mail asks.
3. Open and verify the replacement with `reply-composer`.
4. Delete the stale draft by exact Message-ID after the replacement verifies.
5. Confirm exactly one replacement draft and no temporary Shortcut remain.

```bash
python3 {{SKILL_DIR}}/bin/mailkit.py \
  reply-composer ORIGINAL_ROW_ID \
  --body-file /path/to/revised-reply.txt \
  --replace-draft-message-id '<STALE-DRAFT-RFC-MESSAGE-ID>'
```

### Save immediately

Use only when the user wants an immediately persisted draft and accepts Mail's save confirmation UI:

```bash
python3 {{SKILL_DIR}}/bin/mailkit.py \
  reply-draft ORIGINAL_ROW_ID --body-file /path/to/reply.txt
```

## Traps

- On this Mac, `date_sent` and `date_received` are Unix timestamps. Do not add the Apple epoch unless verified.
- `document_id` may be binary-ish and useless for locating files. Use `rowid -> **/Messages/<rowid>.emlx`.
- Raw MIME contains HTML, quoted-printable, quoted thread history, duplicate parts, and encoding artifacts. Normalize before citing.
- `.partial.emlx` can be enough for evidence, but absence from body files is not absence from Mail.
- Never mutate Mail's SQLite database. Use Mail.app AppleScript or an account API for mutations.
