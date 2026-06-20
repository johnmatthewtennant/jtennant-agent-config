#!/usr/bin/env python3
"""Read-only helpers for local Apple Mail evidence work."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
import subprocess
import sys
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
    con = sqlite3.connect(f"file:{mail_db(root)}?mode=ro", uri=True)
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
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        sub = parser.add_subparsers(dest="helper", required=True)
        sub.add_parser("find", help="candidate discovery").set_defaults(_helper="find")
        sub.add_parser("read", help="rowid evidence extraction").set_defaults(_helper="read")
        args, rest = parser.parse_known_args()
        helper_parser = build_find_parser("mailkit.py find") if args._helper == "find" else build_read_parser("mailkit.py read")
        helper_args = helper_parser.parse_args(rest)
        helper_args.func(helper_args)
        return
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
