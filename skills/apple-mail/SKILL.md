---
name: apple-mail
description: Search and inspect Apple Mail on macOS using no new dependencies. Use this whenever the user asks to search Apple Mail, Mac Mail, local mail, email bodies, downloaded mail, .emlx files, Mail's Envelope Index, or wants to compare AppleScript, sqlite3, rg, rw-mail, Gmail, or Mail.app search approaches. Prefer this skill for read-only Mail search and diagnostics before using AppleScript or building a CLI.
---

# Apple Mail local search

Use Apple Mail's local files directly for read-only search. This avoids AppleScript slowness and avoids new auth.

## Data sources

- Metadata index: `~/Library/Mail/V*/MailData/Envelope Index`
  - SQLite database.
  - Contains indexed messages, subjects, senders, dates, read state, flagged state, mailboxes, and Gmail labels.
  - Covers messages even when the body file is not downloaded.
- Body files: `~/Library/Mail/V*/**/*.emlx`
  - Includes full `.emlx` and `.partial.emlx` files.
  - `*.partial.emlx` often contains searchable text, but treat it as best effort.
  - Body search only covers local files that Mail has downloaded.

Prefer the newest Mail version directory that exists, usually `V10` or `V11`.

```bash
MAIL_ROOT="$HOME/Library/Mail/$(ls "$HOME/Library/Mail" | grep '^V[0-9]' | sort -V | tail -1)"
MAIL_DB="$MAIL_ROOT/MailData/Envelope Index"
```

## Fast body search with rg

Use `rg` for body search across downloaded full and partial `.emlx` files:

```bash
rg -i -n 'search term' "$MAIL_ROOT" -g '*.emlx'
```

Notes:

- `*.partial.emlx` matches `*.emlx`, so partial files are included.
- Search is raw MIME text. Quoted-printable and encoded headers can affect exact matching.
- `rg` returns file paths and line matches, not normalized metadata.
- Extract the Mail row id from the filename. Example: `.../Messages/22.emlx` means row id `22`; `.../Messages/10.partial.emlx` means row id `10`.

## Metadata search with sqlite3

Use SQLite for structured metadata. It is much faster and more complete than AppleScript.

Basic all-mail subject/sender search:

```bash
sqlite3 -readonly -header -column "$MAIL_DB" <<'SQL'
select
  m.rowid as id,
  datetime(m.date_received, 'unixepoch') as received,
  coalesce(a.comment, '') || ' <' || coalesce(a.address, '') || '>' as sender,
  s.subject,
  m.read,
  m.flagged
from messages m
left join subjects s on s.rowid = m.subject
left join addresses a on a.rowid = m.sender
where m.deleted = 0
  and (
    s.subject like '%SEARCH_TERM%' collate nocase
    or a.address like '%SEARCH_TERM%' collate nocase
    or a.comment like '%SEARCH_TERM%' collate nocase
  )
order by m.date_received desc
limit 50;
SQL
```

List mailboxes and labels:

```bash
sqlite3 -readonly -header -column "$MAIL_DB" <<'SQL'
select mb.rowid, mb.url, mb.total_count, mb.unread_count,
       count(l.message_id) as label_count
from mailboxes mb
left join labels l on l.mailbox_id = mb.rowid
group by mb.rowid
order by max(mb.total_count, label_count) desc;
SQL
```

Gmail labels are usually in the `labels` table, not `messages.mailbox`. To search a label such as Amazon, first find its `mailboxes.rowid`, then join through `labels`:

```bash
sqlite3 -readonly -header -column "$MAIL_DB" <<'SQL'
select
  m.rowid as id,
  datetime(m.date_received, 'unixepoch') as received,
  coalesce(a.comment, '') || ' <' || coalesce(a.address, '') || '>' as sender,
  s.subject
from labels l
join messages m on m.rowid = l.message_id
left join subjects s on s.rowid = m.subject
left join addresses a on a.rowid = m.sender
where l.mailbox_id = 10
  and s.subject like '%order%' collate nocase
order by m.date_received desc
limit 50;
SQL
```

## Join rg body hits back to metadata

When `rg` finds body hits, derive row ids from filenames and query SQLite for metadata.

Example shell pattern:

```bash
rg -i -l 'Track package' "$MAIL_ROOT" -g '*.emlx' \
  | python3 - <<'PY'
import re, sqlite3, sys, os
from pathlib import Path
mail_root = Path(os.environ.get('MAIL_ROOT', Path.home() / 'Library/Mail/V10'))
db = Path(os.environ.get('MAIL_DB', mail_root / 'MailData/Envelope Index'))
ids = []
for line in sys.stdin:
    m = re.search(r'/Messages/(\d+)(?:\.partial)?\.emlx$', line.strip())
    if m:
        ids.append(int(m.group(1)))
if not ids:
    raise SystemExit
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
con.row_factory = sqlite3.Row
q = ','.join('?' for _ in ids)
for r in con.execute(f'''
    select m.rowid, datetime(m.date_received, 'unixepoch') received,
           coalesce(a.comment, '') sender_name, coalesce(a.address, '') sender_email,
           s.subject, m.read, m.flagged
    from messages m
    left join subjects s on s.rowid=m.subject
    left join addresses a on a.rowid=m.sender
    where m.rowid in ({q})
    order by m.date_received desc
    limit 50
''', ids):
    print(dict(r))
PY
```

## Coverage diagnostics

Count indexed messages versus local body files:

```bash
python3 - <<'PY'
import sqlite3
from pathlib import Path
root = Path.home() / 'Library/Mail'
version = sorted([p for p in root.iterdir() if p.name.startswith('V')])[-1]
db = version / 'MailData/Envelope Index'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
indexed = con.execute('select count(*) from messages where deleted=0').fetchone()[0]
full = partial = 0
for p in version.rglob('*.emlx'):
    if '.partial.' in p.name: partial += 1
    else: full += 1
print({'indexed': indexed, 'local_total': full + partial, 'full': full, 'partial': partial})
PY
```

## Observed behavior on this Mac, 2026-06-08

- AppleScript broad search over large mailboxes timed out at 120s.
- SQLite metadata searches over about 68k messages completed in around 0.01 to 0.07s.
- `rg` body search over local `.emlx` files completed in around 0.2s.
- Mail was actively downloading bodies after the account was enabled. Local body coverage rose during the session.
- Recent and unread mail was more likely to have local body files. Older read Gmail All Mail messages were often metadata-only until Mail downloaded them.

## When not to use this

- For sending, deleting, moving, flagging, or marking read, do not mutate the SQLite database. Use AppleScript or a purpose-built safe tool.
- For guaranteed body search across messages not downloaded locally, use Gmail API or IMAP with separate auth, or wait for Mail to finish downloading bodies.
- Do not try to reuse Mail.app's Gmail OAuth tokens directly. Treat Mail's auth as private to Mail.
