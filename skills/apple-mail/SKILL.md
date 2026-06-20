---
name: apple-mail
description: Search and inspect Apple Mail on macOS using no new dependencies. Use for read-only Apple Mail, Mac Mail, local mail, email bodies, downloaded mail, .emlx files, Mail's Envelope Index, sqlite3, rg, or Mail.app search diagnostics. Do not use for sending or mutation.
---

# Apple Mail local search

Use local Mail files. Avoid AppleScript for broad search: it is slow, timeout-prone, and hides permission/indexing problems.

## Setup

Requires Full Disk Access for the terminal/agent app. If `~/Library/Mail` is empty, unreadable, or SQLite says `unable to open database file`, stop and have the user grant Full Disk Access:

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
```

Set paths once:

```bash
MAIL_ROOT="$HOME/Library/Mail/$(ls "$HOME/Library/Mail" | grep '^V[0-9]' | sort -V | tail -1)"
MAIL_DB="$MAIL_ROOT/MailData/Envelope Index"
MAIL_FIND="${CLAUDE_SKILL_ROOT:-$(pwd)}/bin/mail-find"
MAIL_READ="${CLAUDE_SKILL_ROOT:-$(pwd)}/bin/mail-read"
```

`bin/mail-find` wraps SQLite or `rg` and returns compact rowid records. `bin/mail-read` consumes rowids for metadata, normalized bodies, excerpts, packets, and coverage. Keep search strategy in the skill/agent; use helpers for stable rowid IO.

## What to search

- SQLite metadata: `$MAIL_DB`
  - Fast, complete for indexed mail, works even when bodies are not downloaded.
  - Use for sender, subject, date, read/flagged state, mailbox, labels, row ids.
- Body files: `$MAIL_ROOT/**/*.emlx`
  - Includes `.partial.emlx` files. Partial files can contain useful text, but are best effort.
  - Use for downloaded bodies only.

## Candidate discovery

Thin wrappers preserve the native search shape and add the metadata users usually fetch next:

```bash
"$MAIL_FIND" describe
"$MAIL_FIND" sql "s.subject like '%invoice%' collate nocase" --order-by "m.date_received desc" --limit 50
"$MAIL_FIND" rg 'contract term' --limit 50
rg -l 'project name' "$MAIL_ROOT" -g '*.emlx' | "$MAIL_FIND" paths
```

`mail-find describe` shows SQL aliases, output shape, and common columns. `mail-find rg` returns raw `rg` path/line/text plus rowid, dates, sender, subject, mailbox, path, downloaded, and partial. `mail-find sql` runs a transparent metadata `WHERE` clause with optional raw `--order-by` and adds path/download status. For anything unusual, use SQLite/`rg` directly.

Common metadata filters:

```bash
"$MAIL_FIND" sql "m.date_received >= strftime('%s','now','-7 days')" --limit 20
"$MAIL_FIND" sql "m.read = 0" --limit 20
"$MAIL_FIND" sql "m.read = 0 and m.date_received >= strftime('%s','now','-7 days')" --limit 20
```

Newer than a last-seen row id:

```bash
last_seen=12345
"$MAIL_FIND" sql "m.rowid > $last_seen" --order-by "m.rowid asc" --limit 50
```

For polling, keep the largest returned `id` as the next `last_seen`.

## Rowid primitives

Use these after metadata/body search identifies relevant row ids:

```bash
"$MAIL_READ" meta 12345 12346
"$MAIL_READ" show 12345 --limit 8000
"$MAIL_READ" excerpt 'contract term' 12345 12346 --context 500
"$MAIL_READ" packet 12345 12346 --term 'contract term' > source-packet.md
"$MAIL_READ" coverage
```

`mail-read` handles `.emlx` byte-count lines, MIME parts, transfer encodings, HTML noise, rowid-to-path mapping, and JSON/markdown output. It accepts `--ids-from -` for pipelines:

```bash
"$MAIL_FIND" sql "s.subject like '%invoice%' collate nocase" | jq -r '.[].id' | "$MAIL_READ" packet --ids-from -
```

## Source packet workflow

For evidence work:

1. Search metadata for candidate row ids.
2. Search bodies only for terms metadata misses.
3. Use `mail-read` only on selected row ids.
4. Quote exact headers and excerpts. Do not infer from raw `rg` snippets alone.

Useful targeted query for a date window plus people/subjects:

```bash
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

## Labels and coverage

Gmail labels are usually in `labels`, not `messages.mailbox`:

```bash
sqlite3 -readonly -header -column "$MAIL_DB" <<'SQL'
select mb.rowid, mb.url, mb.total_count, mb.unread_count, count(l.message_id) label_count
from mailboxes mb
left join labels l on l.mailbox_id = mb.rowid
group by mb.rowid
order by max(mb.total_count, label_count) desc;
SQL
```

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

## Traps

- On this Mac, `date_sent` and `date_received` are Unix timestamps. Do not add the Apple epoch unless verified.
- `document_id` may be binary-ish and useless for locating files. Use `rowid -> **/Messages/<rowid>.emlx`.
- Raw MIME contains HTML, quoted-printable, quoted thread history, duplicate parts, and encoding artifacts. Normalize before citing.
- `.partial.emlx` can be enough for evidence, but absence from body files is not absence from Mail.
- Never mutate Mail's SQLite database. For sending, deleting, moving, flagging, or marking read, use a safe tool, not this skill.
