"""Read WeChat FTS content snapshots without loading its private tokenizer.

These queries provide substring search over stored content. They do not repair
or validate the original FTS index, and cannot reproduce its pinyin tokenizer.
No database, index, or sqlite_schema mutations are performed here.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import re
import sqlite3


_TABLE_PATTERNS = {
    "contact": re.compile(r"contact_fts_v(\d+)_content\Z"),
    "message": re.compile(r"message_fts_v(\d+)_(\d+)_content\Z"),
    "favorite": re.compile(r"fav_fts_v(\d+)_content\Z"),
}


def quote_identifier(name: str) -> str:
    """Quote a SQLite identifier; SQL values must still be bound parameters."""
    return '"' + name.replace('"', '""') + '"'


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(
        f"PRAGMA table_info({quote_identifier(table)})")]


def discover_content_tables(
    conn: sqlite3.Connection,
    family: str,
    required_columns: Iterable[str] = (),
) -> list[str]:
    """Find ordinary shadow content tables with a recognized schema family.

    ``family`` is ``contact``, ``message``, or ``favorite``. Only strictly
    matching names and ordinary CREATE TABLE entries are returned. Optional
    ``required_columns`` are checked without opening the FTS virtual table.
    Tables sort by version descending, then by numeric shard ascending.
    Quote returned names with :func:`quote_identifier` when composing SQL.
    """
    if family not in _TABLE_PATTERNS:
        raise ValueError(f"Unknown content table family: {family}")
    pattern = _TABLE_PATTERNS[family]
    required = set(required_columns)
    found = []
    for name, sql in conn.execute(
        "SELECT name, sql FROM sqlite_schema WHERE type='table'"
    ):
        match = pattern.fullmatch(name)
        if not match or not re.match(r"\s*CREATE\s+TABLE\b", sql or "", re.I):
            continue
        if required and not required.issubset(_columns(conn, name)):
            continue
        version = int(match.group(1))
        shard = int(match.group(2)) if family == "message" else 0
        found.append((-version, shard, name))
    return [name for _, _, name in sorted(found)]


def _dedup_key(values: tuple) -> tuple:
    # Version upgrades may append optional columns; trailing blanks are not a
    # different search result. Do not infer a username from a combined key.
    end = len(values)
    while end and values[end - 1] in (None, ""):
        end -= 1
    return values[:end]


def search_contact_content(
    conn: sqlite3.Connection | None,
    query: str,
    limit: int = 30,
    *,
    fallback: Callable[[str, int], Iterable[Mapping]] | None = None,
) -> list[tuple]:
    """Search compatible contact content tables, returning display tuples.

    v3 stores (combined search_key, local_type); other versions may expose
    additional ``cN`` fields. Search the first six numeric ``cN`` columns, as
    the existing CLI does. Merge versions newest-first and suppress rows with
    both the same shadow document id and equal content, applying ``limit``
    after deduplication. Equal names with different document ids are retained.

    If the database is absent (``conn=None``), has no compatible tables, or
    yields no matches, call ``fallback(query, limit)`` if supplied. The normal
    ``vchat_core.contacts.search_contacts`` function is directly compatible;
    its dicts become (username, nick_name, remark, alias, description) tuples.
    Content hits and fallback rows are not mixed because search_key is not a
    stable contact identity. SQLite errors propagate to the caller.
    """
    if limit <= 0:
        return []
    results = []
    seen = set()
    if conn is not None:
        for table in discover_content_tables(conn, "contact", ("id", "c0")):
            columns = _columns(conn, table)
            text_cols = sorted(
                (c for c in columns if re.fullmatch(r"c\d+", c)),
                key=lambda c: int(c[1:]),
            )[:6]
            selected = ", ".join(quote_identifier(c) for c in text_cols)
            where = " OR ".join(f"{quote_identifier(c)} LIKE ?" for c in text_cols)
            cursor = conn.execute(
                f'SELECT "id", {selected} FROM {quote_identifier(table)} '
                f'WHERE {where} ORDER BY "id"',
                [f"%{query}%"] * len(text_cols),
            )
            try:
                for row in cursor:
                    values = tuple(row)[1:]
                    key = (row[0], _dedup_key(values))
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(values)
                    if len(results) >= limit:
                        return results
            finally:
                cursor.close()
    if results or fallback is None:
        return results
    fields = ("username", "nick_name", "remark", "alias", "description")
    for row in fallback(query, limit):
        values = tuple(row.get(field) or "" for field in fields)
        key = _dedup_key(values)
        if key not in seen:
            seen.add(key)
            results.append(values)
        if len(results) >= limit:
            break
    return results
