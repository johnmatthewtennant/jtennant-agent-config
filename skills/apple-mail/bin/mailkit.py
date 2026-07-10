#!/usr/bin/env python3
"""Helpers for local Apple Mail evidence and native draft work."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import Path


def mail_root() -> Path:
    root = Path.home() / "Library" / "Mail"
    versions = sorted((p for p in root.iterdir() if p.name.startswith("V")), key=lambda p: p.name)
    if not versions:
        raise SystemExit(f"no Mail V* directory under {root}")
    return versions[-1]


def mail_db(root: Path) -> Path:
    return root / "MailData" / "Envelope Index"


def connect(root: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"{mail_db(root).as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def find_emlx(root: Path, rowid: int) -> Path | None:
    for suffix in (".emlx", ".partial.emlx"):
        hits = list(root.rglob(f"{rowid}{suffix}"))
        if hits:
            return hits[0]
    return None


def rowid_from_path(path: str) -> int | None:
    match = re.search(r"/Messages/(\d+)(?:\.partial)?\.emlx$", path)
    return int(match.group(1)) if match else None


def path_info(path: Path | None) -> dict:
    return {
        "path": str(path) if path else None,
        "downloaded": path is not None,
        "partial": bool(path and ".partial." in path.name),
    }


def body_text(path: Path) -> str:
    data = path.read_bytes()
    first, sep, rest = data.partition(b"\n")
    if sep and first.strip().isdigit():
        data = rest

    msg = BytesParser(policy=policy.default).parsebytes(data)
    parts = msg.walk() if msg.is_multipart() else [msg]
    texts: list[str] = []
    for part in parts:
        if part.get_content_maintype() == "multipart":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            text = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/html":
            text = re.sub(r"<(br|/p|/div)[^>]*>", "\n", text, flags=re.I)
            text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            texts.append(text)
    return "\n\n--- part ---\n\n".join(texts)


def metadata(con: sqlite3.Connection, ids: list[int]) -> dict[int, sqlite3.Row]:
    if not ids:
        return {}
    q = ",".join("?" for _ in ids)
    rows = con.execute(
        f"""
        select m.rowid id,
               datetime(m.date_sent, 'unixepoch') sent,
               datetime(m.date_received, 'unixepoch') received,
               coalesce(a.address, '') sender_email,
               coalesce(a.comment, '') sender_name,
               s.subject,
               mb.url mailbox,
               m.read,
               m.flagged
        from messages m
        left join subjects s on s.rowid = m.subject
        left join addresses a on a.rowid = m.sender
        left join mailboxes mb on mb.rowid = m.mailbox
        where m.rowid in ({q})
        """,
        ids,
    ).fetchall()
    return {int(r["id"]): r for r in rows}


def row_record(root: Path, meta: dict[int, sqlite3.Row], rowid: int, matches: list[dict] | None = None) -> dict:
    row = meta.get(rowid)
    item = dict(row) if row else {"id": rowid}
    item.update(path_info(find_emlx(root, rowid)))
    if matches:
        item["matches"] = matches
    return item


def print_json(rows) -> None:
    print(json.dumps(rows, indent=2, ensure_ascii=False))


def write_table(rows: list[dict]) -> None:
    if not rows:
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)


def ids_from_args(args: argparse.Namespace) -> list[int]:
    ids = list(args.rowids)
    source = getattr(args, "ids_from", None)
    if source:
        try:
            text = sys.stdin.read() if source == "-" else Path(source).read_text()
        except OSError as exc:
            raise SystemExit(f"could not read ids from {source}: {exc}") from exc
        ids.extend(int(match.group(0)) for match in re.finditer(r"\d+", text))
    seen = set()
    deduped = []
    for rowid in ids:
        if rowid in seen:
            continue
        seen.add(rowid)
        deduped.append(rowid)
    return deduped


def command_meta(args: argparse.Namespace) -> None:
    rowids = ids_from_args(args)
    root = mail_root()
    con = connect(root)
    meta = metadata(con, rowids)
    rows = [row_record(root, meta, rowid) for rowid in rowids]
    print_json(rows) if args.json else write_table(rows)


def command_show(args: argparse.Namespace) -> None:
    rowids = ids_from_args(args)
    root = mail_root()
    con = connect(root)
    meta = metadata(con, rowids)
    for rowid in rowids:
        row = meta.get(rowid)
        path = find_emlx(root, rowid)
        print(f"===== {rowid} {path or 'not downloaded'} =====")
        if row:
            print(f"From: {row['sender_name']} <{row['sender_email']}>")
            print(f"Sent: {row['sent']}")
            print(f"Subject: {row['subject']}")
            print()
        if path:
            print(body_text(path)[: args.limit])
        print()


def snippet_key(hit: str) -> str:
    key = hit.lower().replace("--- part ---", " ").replace(">", " ")
    return re.sub(r"[^a-z0-9%]+", " ", key).strip()


def snippets(text: str, term: str, context: int) -> list[str]:
    hits = []
    seen = set()
    for match in re.finditer(re.escape(term), text, flags=re.I):
        start = max(0, match.start() - context)
        end = min(len(text), match.end() + context)
        hit = re.sub(r"\s+", " ", text[start:end].strip())
        key = snippet_key(hit)
        if key in seen or any(key in old or old in key for old in seen):
            continue
        seen.add(key)
        hits.append(hit)
    return hits


def command_excerpt(args: argparse.Namespace) -> None:
    rowids = ids_from_args(args)
    root = mail_root()
    con = connect(root)
    meta = metadata(con, rowids)
    rows = []
    for rowid in rowids:
        path = find_emlx(root, rowid)
        text = body_text(path) if path else ""
        hits = snippets(text, args.term, args.context) if path else []
        matches = [{"source": "body", "term": args.term, "excerpt": hit} for hit in hits[: args.max_hits]]
        rows.append(row_record(root, meta, rowid, matches))
    print_json(rows)


def command_packet(args: argparse.Namespace) -> None:
    rowids = ids_from_args(args)
    root = mail_root()
    con = connect(root)
    meta = metadata(con, rowids)
    print("# Apple Mail source packet\n")
    print(f"Mail root: `{root}`\n")
    for rowid in rowids:
        row = meta.get(rowid)
        path = find_emlx(root, rowid)
        print(f"## Row {rowid}\n")
        if row:
            print(f"- Sent: {row['sent']}")
            print(f"- From: {row['sender_name']} <{row['sender_email']}>")
            print(f"- Subject: {row['subject']}")
        print(f"- Path: `{path or 'not downloaded'}`\n")
        if path:
            text = body_text(path)
            if args.term:
                for hit in snippets(text, args.term, args.context)[: args.max_hits]:
                    print(f"> {hit}\n")
            else:
                print("```text")
                print(text[: args.limit])
                print("```\n")


def command_coverage(_: argparse.Namespace) -> None:
    root = mail_root()
    con = connect(root)
    indexed = con.execute("select count(*) from messages where deleted = 0").fetchone()[0]
    full = partial = 0
    for path in root.rglob("*.emlx"):
        partial += ".partial." in path.name
        full += ".partial." not in path.name
    print_json(
        {
            "mail_root": str(root),
            "mail_db": str(mail_db(root)),
            "indexed": indexed,
            "local_total": full + partial,
            "full": full,
            "partial": partial,
        }
    )


def parse_emlx(path: Path):
    data = path.read_bytes()
    first, sep, rest = data.partition(b"\n")
    if sep and first.strip().isdigit():
        data = rest
    return BytesParser(policy=policy.default).parsebytes(data)


def shortcut_store_binary() -> Path:
    source = Path(__file__).with_name("mail_reply_shortcut_store.m")
    if not source.exists():
        raise SystemExit(f"missing helper source: {source}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    cache_dir = Path.home() / "Library" / "Caches" / "claude-apple-mail"
    cache_dir.mkdir(parents=True, exist_ok=True)
    binary = cache_dir / f"mail-reply-shortcut-store-{digest}"
    if binary.exists():
        return binary
    proc = subprocess.run(
        ["clang", "-fblocks", "-framework", "Foundation", str(source), "-o", str(binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise SystemExit(f"could not compile Mail reply helper:\n{proc.stderr.strip()}")
    return binary


def reply_target(con: sqlite3.Connection, rowid: int) -> sqlite3.Row:
    row = con.execute(
        """
        select m.rowid id,
               m.global_message_id,
               s.subject,
               coalesce(a.address, '') sender_email,
               coalesce(a.comment, '') sender_name,
               mgd.message_id_header,
               mb.url mailbox
        from messages m
        left join subjects s on s.rowid = m.subject
        left join addresses a on a.rowid = m.sender
        left join message_global_data mgd on mgd.rowid = m.global_message_id
        left join mailboxes mb on mb.rowid = m.mailbox
        where m.rowid = ? and m.deleted = 0
        """,
        [rowid],
    ).fetchone()
    if not row:
        raise SystemExit(f"Mail message row {rowid} was not found")
    if not row["message_id_header"]:
        raise SystemExit(f"Mail message row {rowid} has no RFC Message-ID")
    return row


def draft_rows_after(con: sqlite3.Connection, rowid: int) -> list[sqlite3.Row]:
    return con.execute(
        """
        select m.rowid id,
               s.subject,
               mgd.message_id_header,
               mb.url mailbox
        from messages m
        left join subjects s on s.rowid = m.subject
        left join message_global_data mgd on mgd.rowid = m.global_message_id
        left join mailboxes mb on mb.rowid = m.mailbox
        where m.rowid > ?
          and mb.url like '%/Drafts'
        order by m.rowid
        """,
        [rowid],
    ).fetchall()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def verify_reply_draft(root: Path, row: sqlite3.Row, target: sqlite3.Row, body: str) -> dict | None:
    path = find_emlx(root, int(row["id"]))
    if not path:
        return None
    message = parse_emlx(path)
    expected_message_id = target["message_id_header"].strip()
    in_reply_to = str(message.get("In-Reply-To", "")).strip()
    references = str(message.get("References", "")).strip()
    html_body = ""
    for part in message.walk():
        if part.get_content_type() == "text/html":
            html_body = part.get_content()
            break
    expected_body = normalize_text(body)
    if in_reply_to != expected_message_id:
        return None
    if expected_message_id not in references:
        return None
    if "AppleOriginalContents" not in html_body or '<blockquote type="cite">' not in html_body:
        return None
    new_content = html_body.split("AppleOriginalContents", 1)[0]
    if "</style>" in new_content:
        new_content = new_content.rsplit("</style>", 1)[1]
    new_content = re.sub(r"<(br|/p|/div)[^>]*>", "\n", new_content, flags=re.I)
    new_content = html.unescape(re.sub(r"<[^>]+>", " ", new_content))
    if not normalize_text(new_content).startswith(expected_body):
        return None
    return {
        "rowid": int(row["id"]),
        "message_id": str(message.get("Message-ID", "")).strip(),
        "subject": str(message.get("Subject", "")),
        "to": str(message.get("To", "")),
        "in_reply_to": in_reply_to,
        "references": references,
        "path": str(path),
        "native_quote_preserved": True,
        "body_starts_with": body.splitlines()[0] if body.splitlines() else "",
    }


def delete_draft_message(message_id: str) -> int:
    normalized = message_id.strip().strip("<>")
    script = """
on run argv
  set targetID to item 1 of argv
  tell application "Mail"
    set matches to every message of drafts mailbox whose message id is targetID
    set deletedCount to count of matches
    repeat with m in matches
      delete m
    end repeat
    return deletedCount
  end tell
end run
"""
    proc = subprocess.run(
        ["osascript", "-e", script, normalized],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise SystemExit(f"could not delete stale draft {message_id}: {proc.stderr.strip()}")
    return int(proc.stdout.strip() or "0")


def native_reply_subject(subject: str) -> str:
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def open_composer_state(subject: str) -> dict:
    script = r'''
on run argv
  set expectedSubject to item 1 of argv
  set unitSeparator to character id 31
  set recordSeparator to character id 30
  set outgoingCount to 0
  set actualSubject to ""
  set recipientList to ""
  tell application "Mail"
    set matches to every outgoing message whose subject is expectedSubject
    set outgoingCount to count matches
    if outgoingCount > 0 then
      set msg to item 1 of matches
      set actualSubject to subject of msg
      repeat with recipientItem in to recipients of msg
        if recipientList is not "" then set recipientList to recipientList & recordSeparator
        set recipientList to recipientList & (address of recipientItem)
      end repeat
    end if
  end tell

  set windowName to ""
  set firstBodyText to ""
  set bodyTexts to ""
  set quotePresent to false
  tell application "System Events"
    if exists process "Mail" then
      tell process "Mail"
        repeat with candidate in windows
          if (name of candidate) contains expectedSubject then
            set windowName to name of candidate
            set insideBody to false
            set elementsList to entire contents of candidate
            repeat with elementItem in elementsList
              try
                set elementRole to role of elementItem
                if elementRole is "AXWebArea" then
                  set insideBody to true
                else if insideBody and elementRole is "AXStaticText" then
                  set elementValue to value of elementItem as text
                  if elementValue is not "" then
                    if firstBodyText is "" then set firstBodyText to elementValue
                    if bodyTexts is not "" then set bodyTexts to bodyTexts & recordSeparator
                    set bodyTexts to bodyTexts & elementValue
                    if elementValue contains " wrote:" then set quotePresent to true
                  end if
                end if
              end try
            end repeat
            exit repeat
          end if
        end repeat
      end tell
    end if
  end tell
  return (outgoingCount as text) & unitSeparator & actualSubject & unitSeparator & recipientList & unitSeparator & windowName & unitSeparator & firstBodyText & unitSeparator & (quotePresent as text) & unitSeparator & bodyTexts
end run
'''
    proc = subprocess.run(
        ["osascript", "-e", script, subject],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        return {"error": proc.stderr.strip(), "outgoing_count": 0}
    fields = proc.stdout.rstrip("\n").split(chr(31), 6)
    if len(fields) != 7:
        return {"error": f"unexpected composer state: {proc.stdout!r}", "outgoing_count": 0}
    count, actual_subject, recipients, window, first_body, quote, body_texts = fields
    return {
        "outgoing_count": int(count or "0"),
        "subject": actual_subject,
        "recipients": [value for value in recipients.split(chr(30)) if value],
        "window": window,
        "first_body_text": first_body,
        "quote_present": quote == "true",
        "body_texts": [value for value in body_texts.split(chr(30)) if value],
    }


def draft_send_state(subject: str, recipient: str, body: str) -> dict:
    script = r'''
on run argv
  set expectedSubject to item 1 of argv
  set expectedRecipient to item 2 of argv
  set expectedBody to item 3 of argv
  set unitSeparator to character id 31
  set recordSeparator to character id 30
  tell application "Mail"
    set matched to {}
    repeat with msg in messages of drafts mailbox
      if subject of msg is expectedSubject then
        set recipientMatches to 0
        repeat with recipientItem in to recipients of msg
          if address of recipientItem is expectedRecipient then set recipientMatches to recipientMatches + 1
        end repeat
        if recipientMatches is 1 then
          set draftContent to content of msg as text
          if expectedBody is "" or draftContent starts with expectedBody then set end of matched to msg
        end if
      end if
    end repeat
    if (count matched) is not 1 then
      return (count matched as text) & unitSeparator & "" & unitSeparator & ""
    end if
    set selectedDraft to item 1 of matched
    set recipientList to ""
    repeat with recipientItem in to recipients of selectedDraft
      if recipientList is not "" then set recipientList to recipientList & recordSeparator
      set recipientList to recipientList & (address of recipientItem)
    end repeat
    return "1" & unitSeparator & (message id of selectedDraft) & unitSeparator & recipientList
  end tell
end run
'''
    proc = subprocess.run(
        ["osascript", "-e", script, subject, recipient, body],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        return {"count": 0, "error": proc.stderr.strip()}
    fields = proc.stdout.rstrip("\n").split(chr(31), 2)
    if len(fields) != 3:
        return {"count": 0, "error": f"unexpected draft state: {proc.stdout!r}"}
    count, message_id, recipients = fields
    count_match = re.search(r"\d+", count)
    return {
        "count": int(count_match.group(0)) if count_match else 0,
        "message_id": message_id,
        "recipients": [value for value in recipients.split(chr(30)) if value],
    }


def click_composer_send(subject: str) -> None:
    script = r'''
on run argv
  set expectedSubject to item 1 of argv
  tell application "Mail" to activate
  delay 0.2
  tell application "System Events"
    tell process "Mail"
      set frontmost to true
      set matchedWindows to {}
      repeat with candidate in windows
        if name of candidate is expectedSubject then
          try
            set toolbarItem to first UI element of candidate whose role is "AXToolbar"
            set sendButtons to every button of toolbarItem whose description is "Send" and enabled is true
            if (count sendButtons) is 1 then set end of matchedWindows to candidate
          end try
        end if
      end repeat
      if (count matchedWindows) is not 1 then error "Expected exactly one enabled Send button for " & expectedSubject & "; found " & (count matchedWindows)
      set selectedWindow to item 1 of matchedWindows
      if (count sheets of selectedWindow) is not 0 then error "Composer has an open sheet"
      set toolbarItem to first UI element of selectedWindow whose role is "AXToolbar"
      set sendButton to first button of toolbarItem whose description is "Send" and enabled is true
      click sendButton
    end tell
  end tell
end run
'''
    proc = subprocess.run(
        ["osascript", "-e", script, subject],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise SystemExit(f"could not click Mail's Send button: {proc.stderr.strip()}")


def sent_rows_after(con: sqlite3.Connection, rowid: int, subject: str, recipient: str) -> list[sqlite3.Row]:
    database_subject = re.sub(r"^(re|fwd?):\s*", "", subject, flags=re.I)
    return con.execute(
        """
        select distinct m.rowid id,
               s.subject,
               mgd.message_id_header,
               mb.url mailbox
        from messages m
        left join subjects s on s.rowid = m.subject
        left join message_global_data mgd on mgd.rowid = m.global_message_id
        left join mailboxes mb on mb.rowid = m.mailbox
        where m.rowid > ?
          and s.subject = ?
          and (mb.url like '%/Sent' or mb.url like '%/All%20Mail')
          and exists (
            select 1
            from recipients r
            join addresses a on a.rowid = r.address
            where r.message = m.rowid and lower(a.address) = lower(?)
          )
        order by m.rowid desc
        """,
        [rowid, database_subject, recipient],
    ).fetchall()


def composer_window_exists(subject: str) -> bool:
    script = r'''
on run argv
  set expectedSubject to item 1 of argv
  tell application "System Events"
    if not (exists process "Mail") then return false
    tell process "Mail"
      repeat with candidate in windows
        if name of candidate is expectedSubject then return true
      end repeat
    end tell
  end tell
  return false
end run
'''
    proc = subprocess.run(
        ["osascript", "-e", script, subject],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def command_send_composer(args: argparse.Namespace) -> None:
    body = Path(args.body_file).read_text() if args.body_file else (args.body or "")
    deadline = time.monotonic() + args.timeout
    draft = {"count": 0}
    while time.monotonic() < deadline:
        draft = draft_send_state(args.subject, args.to, body)
        if draft.get("count") == 1:
            break
        time.sleep(0.25)
    if draft.get("count") != 1:
        detail = f": {draft['error']}" if draft.get("error") else ""
        raise SystemExit(f"expected exactly one matching autosaved draft{detail}")
    if not composer_window_exists(args.subject):
        raise SystemExit(f"no open Mail composer named {args.subject!r}")

    root = mail_root()
    con = connect(root)
    before_max = int(con.execute("select coalesce(max(rowid), 0) from messages").fetchone()[0])
    click_composer_send(args.subject)

    sent: sqlite3.Row | None = None
    while time.monotonic() < deadline:
        current = connect(root)
        try:
            rows = sent_rows_after(current, before_max, args.subject, args.to)
            if rows:
                sent = rows[0]
        finally:
            current.close()
        draft_gone = draft_send_state(args.subject, args.to, body).get("count") == 0
        if sent and draft_gone and not composer_window_exists(args.subject):
            break
        time.sleep(0.25)
    if not sent:
        raise SystemExit("Mail closed the composer but no matching sent message was indexed before timeout")

    print_json(
        {
            "sent": True,
            "subject": args.subject,
            "to": args.to,
            "message_id": sent["message_id_header"],
            "mailbox": sent["mailbox"],
            "composer_closed": not composer_window_exists(args.subject),
            "draft_removed": draft_send_state(args.subject, args.to, body).get("count") == 0,
            "send_control": "Mail Accessibility Send button",
        }
    )


def command_reply_composer(args: argparse.Namespace) -> None:
    root = mail_root()
    con = connect(root)
    target = reply_target(con, args.rowid)
    body = Path(args.body_file).read_text() if args.body_file else args.body
    if not body or not body.strip():
        raise SystemExit("reply body is empty")

    expected_subject = native_reply_subject(target["subject"] or "")
    existing = open_composer_state(expected_subject)
    if existing.get("outgoing_count", 0):
        raise SystemExit(f"an outgoing Mail composer for {expected_subject!r} is already open")

    before_max = int(con.execute("select coalesce(max(rowid), 0) from messages").fetchone()[0])
    helper = shortcut_store_binary()
    shortcut_id = str(uuid.uuid4()).upper()
    shortcut_name = f"Claude Mail Reply Composer {shortcut_id[:8]}"
    entity_id = f"1%1%3%{target['global_message_id']}%{target['id']}"
    body_path = helper.parent / f"reply-body-{shortcut_id}.txt"
    body_path.write_text(body)
    runner: subprocess.Popen | None = None
    state: dict | None = None
    draft_result: dict | None = None
    shortcut_removed = False

    try:
        environment = os.environ.copy()
        environment["MAIL_REPLY_ONLY"] = "1"
        create = subprocess.run(
            [str(helper), "create", shortcut_id, shortcut_name, str(body_path), entity_id],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
        )
        if create.returncode:
            raise SystemExit(f"could not create temporary Mail reply shortcut:\n{create.stderr.strip()}")

        visibility_deadline = time.monotonic() + min(args.timeout, 20)
        while time.monotonic() < visibility_deadline:
            listed = subprocess.run(
                ["shortcuts", "list", "--show-identifiers"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if shortcut_id in listed.stdout:
                break
            time.sleep(0.25)
        else:
            raise SystemExit("temporary Mail reply shortcut was not visible to the Shortcuts runner")

        runner = subprocess.Popen(
            ["shortcuts", "run", shortcut_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        first_line = next((line for line in body.splitlines() if line), "")
        expected_lines = [line for line in body.splitlines() if line]
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            state = open_composer_state(expected_subject)
            body_dump = "\n".join(state.get("body_texts", []))
            accessibility_verified = (
                state.get("first_body_text") == first_line
                and all(line in body_dump for line in expected_lines)
                and state.get("quote_present")
            )
            current = connect(root)
            try:
                for row in draft_rows_after(current, before_max):
                    draft_result = verify_reply_draft(root, row, target, body)
                    if draft_result:
                        break
            finally:
                current.close()
            if state.get("window") and (accessibility_verified or draft_result):
                break
            if runner.poll() is not None and runner.returncode:
                stdout, stderr = runner.communicate()
                raise SystemExit(
                    f"Mail ReplyMessageIntent failed with exit {runner.returncode}"
                    + (f"\n{stderr.strip()}" if stderr.strip() else "")
                    + (f"\n{stdout.strip()}" if stdout.strip() else "")
                )
            time.sleep(0.2)
        else:
            raise SystemExit("Mail ReplyMessageIntent did not open a verified composer before timeout")

        recipients = state.get("recipients") or ([draft_result["to"]] if draft_result else [])
        if not recipients:
            raise SystemExit("Mail composer has no recipient")

        if args.replace_draft_message_id:
            deleted = delete_draft_message(args.replace_draft_message_id)
            if deleted == 0:
                raise SystemExit(f"stale draft {args.replace_draft_message_id} was not found in Drafts")

        delete_temporary_shortcut(helper, shortcut_id)
        shortcut_removed = True
        print_json(
            {
                "subject": state["subject"] or (draft_result["subject"] if draft_result else expected_subject),
                "to": recipients,
                "window": state["window"],
                "body_starts_with": state.get("first_body_text") or first_line,
                "native_quote_preserved": True,
                "target_rowid": int(target["id"]),
                "target_message_id": target["message_id_header"],
                "api": "com.apple.mail.ReplyMessageIntent",
                "save_mode": "Mail autosave while composer remains open",
                "temporary_shortcut_removed": True,
            }
        )
    finally:
        if runner and runner.poll() is None:
            try:
                runner.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if not shortcut_removed:
            try:
                delete_temporary_shortcut(helper, shortcut_id)
            except RuntimeError as exc:
                print(f"warning: {exc}", file=sys.stderr)
        body_path.unlink(missing_ok=True)


def delete_temporary_shortcut(helper: Path, shortcut_id: str) -> None:
    database = Path.home() / "Library" / "Shortcuts" / "Shortcuts.sqlite"
    for _ in range(10):
        subprocess.run(
            [str(helper), "delete", shortcut_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            con = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
            try:
                present = con.execute(
                    "select 1 from ZSHORTCUT where ZWORKFLOWID = ? and ZTOMBSTONED = 0",
                    [shortcut_id],
                ).fetchone()
            finally:
                con.close()
        except sqlite3.Error:
            present = True
        if not present:
            return
        time.sleep(0.5)
    raise RuntimeError(f"temporary shortcut {shortcut_id} remained after cleanup")


def command_reply_draft(args: argparse.Namespace) -> None:
    root = mail_root()
    con = connect(root)
    target = reply_target(con, args.rowid)
    body = Path(args.body_file).read_text() if args.body_file else args.body
    if not body or not body.strip():
        raise SystemExit("reply body is empty")

    entity_id = f"1%1%3%{target['global_message_id']}%{target['id']}"
    before_max = int(con.execute("select coalesce(max(rowid), 0) from messages").fetchone()[0])
    helper = shortcut_store_binary()
    shortcut_id = str(uuid.uuid4()).upper()
    shortcut_name = f"Claude Mail Reply {shortcut_id[:8]}"
    cache_dir = helper.parent
    body_path = cache_dir / f"reply-body-{shortcut_id}.txt"
    body_path.write_text(body)
    runner: subprocess.Popen | None = None
    result: dict | None = None

    try:
        create = subprocess.run(
            [str(helper), "create", shortcut_id, shortcut_name, str(body_path), entity_id],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if create.returncode:
            raise SystemExit(f"could not create temporary Mail reply shortcut:\n{create.stderr.strip()}")

        visibility_deadline = time.monotonic() + min(args.timeout, 20)
        while time.monotonic() < visibility_deadline:
            listed = subprocess.run(
                ["shortcuts", "list", "--show-identifiers"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if shortcut_id in listed.stdout:
                break
            time.sleep(0.5)
        else:
            raise SystemExit("temporary Mail reply shortcut was not visible to the Shortcuts runner")

        runner = subprocess.Popen(
            ["shortcuts", "run", shortcut_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + args.timeout
        runner_stdout = runner_stderr = ""
        while time.monotonic() < deadline and result is None:
            if runner.poll() is not None and not (runner_stdout or runner_stderr):
                runner_stdout, runner_stderr = runner.communicate()
            current = connect(root)
            try:
                for row in draft_rows_after(current, before_max):
                    result = verify_reply_draft(root, row, target, body)
                    if result:
                        break
            finally:
                current.close()
            if result is None:
                if runner.poll() is not None and runner.returncode:
                    break
                time.sleep(0.25)
        if result is None:
            if runner.poll() is not None and not (runner_stdout or runner_stderr):
                runner_stdout, runner_stderr = runner.communicate()
            raise SystemExit(
                "Mail ReplyMessageIntent did not create a verified draft before timeout"
                + (f"\nrunner exit: {runner.returncode}" if runner.poll() is not None else "")
                + (f"\n{runner_stderr.strip()}" if runner_stderr.strip() else "")
                + (f"\n{runner_stdout.strip()}" if runner_stdout.strip() else "")
            )

        if args.replace_draft_message_id:
            if args.replace_draft_message_id.strip("<>") == result["message_id"].strip("<>"):
                raise SystemExit("replacement draft Message-ID unexpectedly matches the stale draft")
            deleted = delete_draft_message(args.replace_draft_message_id)
            if deleted == 0:
                raise SystemExit(f"stale draft {args.replace_draft_message_id} was not found in Drafts")
            result["replaced_message_id"] = args.replace_draft_message_id
            result["deleted_stale_drafts"] = deleted

        result.update(
            {
                "target_rowid": int(target["id"]),
                "target_message_id": target["message_id_header"],
                "target_subject": target["subject"],
                "api": "com.apple.mail.ReplyMessageIntent",
                "save_api": "com.apple.mail.SaveDraftIntent",
            }
        )
        print_json(result)
    finally:
        if runner and runner.poll() is None:
            try:
                os.killpg(runner.pid, signal.SIGTERM)
                runner.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(runner.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            delete_temporary_shortcut(helper, shortcut_id)
        except RuntimeError as exc:
            print(f"warning: {exc}", file=sys.stderr)
        body_path.unlink(missing_ok=True)


def reject_statement_clause(name: str, clause: str) -> None:
    if ";" in clause:
        raise SystemExit(f"{name} must be a single SQL clause, not a statement")


def command_find_sql(args: argparse.Namespace) -> None:
    reject_statement_clause("where", args.where)
    reject_statement_clause("order-by", args.order_by)
    root = mail_root()
    con = connect(root)
    rows = con.execute(
        f"""
        select m.rowid id
        from messages m
        left join subjects s on s.rowid = m.subject
        left join addresses a on a.rowid = m.sender
        left join mailboxes mb on mb.rowid = m.mailbox
        where m.deleted = 0 and ({args.where})
        order by {args.order_by}
        limit ?
        """,
        [args.limit],
    ).fetchall()
    ids = [int(r["id"]) for r in rows]
    meta = metadata(con, ids)
    match = {"source": "metadata", "where": args.where, "order_by": args.order_by}
    records = [row_record(root, meta, rowid, [match]) for rowid in ids]
    print_json(records)


def command_find_describe(_: argparse.Namespace) -> None:
    print("""mail-find sql uses these aliases:
  m  messages
  s  subjects       left join subjects s on s.rowid = m.subject
  a  sender address left join addresses a on a.rowid = m.sender
  mb mailbox        left join mailboxes mb on mb.rowid = m.mailbox

Canonical output columns:
  id, sent, received, sender_email, sender_name, subject, mailbox, read, flagged,
  path, downloaded, partial, matches

Canonical query shape:
  select m.rowid id
  from messages m
  left join subjects s on s.rowid = m.subject
  left join addresses a on a.rowid = m.sender
  left join mailboxes mb on mb.rowid = m.mailbox
  where m.deleted = 0 and (<where>)
  order by <order-by>
  limit ?

Common columns:
  m.rowid, m.date_sent, m.date_received, m.read, m.flagged, m.deleted
  s.subject
  a.address, a.comment
  mb.url, mb.total_count, mb.unread_count

Examples:
  mail-find sql "m.read = 0" --order-by "m.date_received desc"
  mail-find sql "m.rowid > 12345" --order-by "m.rowid asc"
""")


def command_find_rg(args: argparse.Namespace) -> None:
    root = mail_root()
    proc = subprocess.run(
        ["rg", "-i", "-n", args.term, str(root), "-g", "*.emlx"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise SystemExit(proc.stderr.strip())

    by_id: dict[int, list[dict]] = {}
    for line in proc.stdout.splitlines():
        match = re.match(r"(.*/Messages/(\d+)(?:\.partial)?\.emlx):(\d+):(.*)", line)
        if not match:
            continue
        path, rowid_s, line_s, text = match.groups()
        rowid = int(rowid_s)
        by_id.setdefault(rowid, [])
        if len(by_id[rowid]) < args.max_hits:
            by_id[rowid].append(
                {
                    "source": "rg",
                    "term": args.term,
                    "path": path,
                    "line": int(line_s),
                    "raw": line,
                    "raw_excerpt": text[: args.excerpt_chars],
                }
            )
        if len(by_id) >= args.limit:
            break

    con = connect(root)
    meta = metadata(con, list(by_id))
    print_json([row_record(root, meta, rowid, by_id[rowid]) for rowid in by_id])


def command_find_paths(args: argparse.Namespace) -> None:
    paths = args.paths or [line.strip() for line in sys.stdin if line.strip()]
    ids = []
    for path in paths:
        rowid = rowid_from_path(path)
        if rowid is not None and rowid not in ids:
            ids.append(rowid)
    root = mail_root()
    con = connect(root)
    meta = metadata(con, ids)
    print_json([row_record(root, meta, rowid) for rowid in ids])


def build_read_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Read Apple Mail evidence by row id")
    sub = parser.add_subparsers(dest="command", required=True)

    meta_p = sub.add_parser("meta", help="show metadata for Mail row ids")
    meta_p.add_argument("rowids", nargs="*", type=int)
    meta_p.add_argument("--ids-from", help="read row ids from file, or '-' for stdin")
    meta_p.add_argument("--json", action="store_true")
    meta_p.set_defaults(func=command_meta)

    show_p = sub.add_parser("show", help="show normalized bodies for Mail row ids")
    show_p.add_argument("rowids", nargs="*", type=int)
    show_p.add_argument("--ids-from", help="read row ids from file, or '-' for stdin")
    show_p.add_argument("--limit", type=int, default=8000)
    show_p.set_defaults(func=command_show)

    ex_p = sub.add_parser("excerpt", help="emit JSON snippets around a term")
    ex_p.add_argument("term")
    ex_p.add_argument("rowids", nargs="*", type=int)
    ex_p.add_argument("--ids-from", help="read row ids from file, or '-' for stdin")
    ex_p.add_argument("--context", type=int, default=500)
    ex_p.add_argument("--max-hits", type=int, default=5)
    ex_p.set_defaults(func=command_excerpt)

    packet_p = sub.add_parser("packet", help="emit markdown source packet")
    packet_p.add_argument("rowids", nargs="*", type=int)
    packet_p.add_argument("--ids-from", help="read row ids from file, or '-' for stdin")
    packet_p.add_argument("--term")
    packet_p.add_argument("--context", type=int, default=500)
    packet_p.add_argument("--max-hits", type=int, default=5)
    packet_p.add_argument("--limit", type=int, default=3000)
    packet_p.set_defaults(func=command_packet)

    coverage_p = sub.add_parser("coverage", help="show index/body coverage diagnostics")
    coverage_p.set_defaults(func=command_coverage)
    return parser


def build_send_composer_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Send one verified open Apple Mail composer")
    parser.add_argument("--subject", required=True, help="exact composer subject, including Re: when present")
    parser.add_argument("--to", required=True, help="exact recipient email address")
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body", help="expected leading response body text")
    body.add_argument("--body-file", help="UTF-8 file containing expected leading response body text")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.set_defaults(func=command_send_composer)
    return parser


def build_reply_composer_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Open a populated native Apple Mail reply composer")
    parser.add_argument("rowid", type=int, help="row id of the original Mail message")
    body = parser.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="reply body text")
    body.add_argument("--body-file", help="UTF-8 file containing the reply body")
    parser.add_argument(
        "--replace-draft-message-id",
        help="delete this exact stale Drafts RFC Message-ID after the composer verifies",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.set_defaults(func=command_reply_composer)
    return parser


def build_reply_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Create a native Apple Mail reply draft")
    parser.add_argument("rowid", type=int, help="row id of the original Mail message")
    body = parser.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="reply body text")
    body.add_argument("--body-file", help="UTF-8 file containing the reply body")
    parser.add_argument(
        "--replace-draft-message-id",
        help="delete this exact stale Drafts RFC Message-ID after the replacement verifies",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.set_defaults(func=command_reply_draft)
    return parser


def build_find_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Find Apple Mail candidate row ids")
    sub = parser.add_subparsers(dest="command", required=True)

    describe_p = sub.add_parser("describe", help="show SQL aliases, output shape, and common columns")
    describe_p.set_defaults(func=command_find_describe)

    sql_p = sub.add_parser("sql", help="run a metadata WHERE clause and return compact row records")
    sql_p.add_argument("where")
    sql_p.add_argument("--limit", type=int, default=50)
    sql_p.add_argument("--order-by", default="m.date_received desc")
    sql_p.set_defaults(func=command_find_sql)

    rg_p = sub.add_parser("rg", help="run rg over .emlx bodies and join hits to metadata")
    rg_p.add_argument("term")
    rg_p.add_argument("--limit", type=int, default=50)
    rg_p.add_argument("--max-hits", type=int, default=3)
    rg_p.add_argument("--excerpt-chars", type=int, default=500)
    rg_p.set_defaults(func=command_find_rg)

    paths_p = sub.add_parser("paths", help="read .emlx paths from args/stdin and join to metadata")
    paths_p.add_argument("paths", nargs="*")
    paths_p.set_defaults(func=command_find_paths)
    return parser


def main() -> None:
    prog = Path(sys.argv[0]).name
    if prog == "mail-find":
        parser = build_find_parser(prog)
    elif prog == "mail-read":
        parser = build_read_parser(prog)
    elif prog == "mail-reply-draft":
        parser = build_reply_parser(prog)
    elif prog == "mail-reply-composer":
        parser = build_reply_composer_parser(prog)
    elif prog == "mail-send-composer":
        parser = build_send_composer_parser(prog)
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        sub = parser.add_subparsers(dest="helper", required=True)
        sub.add_parser("find", help="candidate discovery", add_help=False).set_defaults(_helper="find")
        sub.add_parser("read", help="rowid evidence extraction", add_help=False).set_defaults(_helper="read")
        sub.add_parser("reply-composer", help="open a native Mail reply composer", add_help=False).set_defaults(_helper="reply-composer")
        sub.add_parser("send-composer", help="send a verified Mail composer", add_help=False).set_defaults(_helper="send-composer")
        sub.add_parser("reply-draft", help="create a saved native Mail reply draft", add_help=False).set_defaults(_helper="reply-draft")
        args, rest = parser.parse_known_args()
        if args._helper == "find":
            helper_parser = build_find_parser("mailkit.py find")
        elif args._helper == "read":
            helper_parser = build_read_parser("mailkit.py read")
        elif args._helper == "reply-composer":
            helper_parser = build_reply_composer_parser("mailkit.py reply-composer")
        elif args._helper == "send-composer":
            helper_parser = build_send_composer_parser("mailkit.py send-composer")
        else:
            helper_parser = build_reply_parser("mailkit.py reply-draft")
        helper_args = helper_parser.parse_args(rest)
        helper_args.func(helper_args)
        return
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
