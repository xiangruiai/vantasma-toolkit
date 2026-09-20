"""Compatibility checks use synthetic databases; no user chat data is loaded."""

import importlib
from pathlib import Path
import sqlite3
import tempfile
import unittest


class SearchCompatTests(unittest.TestCase):
    def setUp(self):
        try:
            self.compat = importlib.import_module("vchat_core.search_compat")
        except ModuleNotFoundError:
            self.fail("search_compat must provide content-table compatibility queries")
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)

    def contact_table(self, version, rows, columns=2):
        name = f"contact_fts_v{version}_content"
        cols = ", ".join(f"c{i}" for i in range(columns))
        self.conn.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY, {cols})')
        placeholders = ",".join("?" for _ in range(columns))
        self.conn.executemany(
            f'INSERT INTO "{name}" ({cols}) VALUES ({placeholders})', rows)

    def test_v3_and_v4_contacts_are_supported(self):
        for version in (3, 4):
            with self.subTest(version=version):
                self.contact_table(version, [(f"example-v{version}", 1)])
                self.assertIn(
                    (f"example-v{version}", 1),
                    self.compat.search_contact_content(self.conn, "example"))

    def test_versions_merge_without_exact_duplicates_and_respect_limit(self):
        self.contact_table(3, [("match-old", 1), ("match-shared", 1)])
        self.contact_table(4, [("match-new", 1), ("match-shared", 1)])
        self.assertEqual(
            self.compat.search_contact_content(self.conn, "match", limit=3),
            [("match-new", 1), ("match-shared", 1), ("match-old", 1)])

    def test_empty_later_columns_do_not_duplicate_old_version_results(self):
        self.contact_table(3, [("match-shared", 1)])
        self.contact_table(4, [("match-shared", 1, None, "")], columns=4)
        self.assertEqual(len(self.compat.search_contact_content(self.conn, "match")), 1)

    def test_distinct_contact_ids_with_equal_search_keys_are_preserved(self):
        self.contact_table(3, [("same display name", 1), ("same display name", 1)])
        self.assertEqual(len(self.compat.search_contact_content(self.conn, "same")), 2)

    def test_parameterized_keyword_cannot_change_query(self):
        key = "x' OR 1=1 --"
        self.contact_table(3, [(key, 1), ("unrelated", 1)])
        self.assertEqual(self.compat.search_contact_content(self.conn, key), [(key, 1)])

    def test_fallback_handles_absent_database_missing_tables_and_no_matches(self):
        calls = []

        def fallback(query, limit):
            calls.append((query, limit))
            return [{"username": "wxid-example", "nick_name": "Example",
                     "remark": "", "alias": "alias", "description": "note"}]

        for conn in (None, self.conn):
            self.assertEqual(self.compat.search_contact_content(
                conn, "query", 7, fallback=fallback),
                [("wxid-example", "Example", "", "alias", "note")])
        self.contact_table(3, [("different", 1)])
        self.compat.search_contact_content(self.conn, "query", 7, fallback=fallback)
        self.assertEqual(calls, [("query", 7)] * 3)

    def test_no_fallback_when_content_matches(self):
        self.contact_table(3, [("match", 1)])

        def fallback(query, limit):
            self.fail("fallback must not mix identities with content search-key rows")

        self.assertEqual(self.compat.search_contact_content(
            self.conn, "match", fallback=fallback), [("match", 1)])

    def test_discovery_requires_family_name_real_table_and_columns(self):
        for table in ("message_fts_v4_0_content", "message_fts_v5_10_content",
                      "message_fts_v5_2_content", "message_fts_v4_8_content_extra",
                      'message_fts_v4_0_content";DROP TABLE x;--'):
            self.conn.execute('CREATE TABLE "' + table.replace('"', '""') +
                              '" (id INTEGER PRIMARY KEY, c0, c4, c5, c6)')
        self.conn.execute("CREATE TABLE message_fts_v6_0_content (c0)")
        self.conn.execute("CREATE VIEW message_fts_v7_0_content AS SELECT 'fake' AS c0")
        self.conn.execute("CREATE TABLE fav_fts_v1_content (c0, c1, c2, c3)")
        self.assertEqual(self.compat.discover_content_tables(
            self.conn, "message", required_columns=("c0", "c4", "c5", "c6")),
            ["message_fts_v5_2_content", "message_fts_v5_10_content",
             "message_fts_v4_0_content"])
        self.assertEqual(self.compat.discover_content_tables(self.conn, "favorite"),
                         ["fav_fts_v1_content"])
        with self.assertRaises(ValueError):
            self.compat.discover_content_tables(self.conn, "unknown")

    def test_contacts_without_search_columns_fall_back(self):
        self.conn.execute("CREATE TABLE contact_fts_v5_content (id INTEGER PRIMARY KEY)")
        self.assertEqual(self.compat.search_contact_content(self.conn, "query"), [])

    def test_nonpositive_limit_returns_nothing_without_calling_fallback(self):
        self.contact_table(3, [("match", 1)])
        self.assertEqual(self.compat.search_contact_content(self.conn, "match", 0), [])
        self.assertEqual(self.compat.search_contact_content(self.conn, "match", -1), [])

    def test_quote_identifier_escapes_embedded_quotes(self):
        self.assertEqual(self.compat.quote_identifier('a"b'), '"a""b"')

    def test_shadow_table_read_works_with_unavailable_wechat_tokenizer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.db"
            with sqlite3.connect(path) as seed:
                seed.execute("CREATE VIRTUAL TABLE contact_fts_v3 USING "
                             "fts5(search_key, local_type UNINDEXED)")
                seed.execute("INSERT INTO contact_fts_v3 VALUES (?, ?)", ("sample", 1))
                seed.execute("PRAGMA writable_schema=ON")
                seed.execute("UPDATE sqlite_schema SET sql=replace(sql, 'fts5(', "
                             "'fts5(tokenize=\"MMFtsTokenizer\", ') "
                             "WHERE name='contact_fts_v3'")
            conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
            self.addCleanup(conn.close)
            with self.assertRaisesRegex(sqlite3.OperationalError, "MMFtsTokenizer"):
                conn.execute("SELECT * FROM contact_fts_v3 "
                             "WHERE contact_fts_v3 MATCH 'sample'").fetchall()
            statements = []
            conn.set_trace_callback(statements.append)
            self.assertEqual(self.compat.search_contact_content(conn, "sample"),
                             [("sample", 1)])
            self.assertTrue(all(s.lstrip().upper().startswith(("SELECT", "PRAGMA"))
                                for s in statements))


if __name__ == "__main__":
    unittest.main()
