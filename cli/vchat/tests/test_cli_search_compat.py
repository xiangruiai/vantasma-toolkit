import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("vchat_search_cli_tests", str(ROOT / "vchat"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class SearchCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def database(self, relative, statements):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
        conn.close()

    def invoke(self, function, args, fallback=None):
        out = io.StringIO()
        with patch.object(cli, "check_freshness"), \
                patch("vchat_core.cache.default_cache", return_value=SimpleNamespace(_root=self.root)), \
                patch("vchat_core.contacts.search_contacts", return_value=fallback or []) as search, \
                patch("vchat_core._compat.get_contact_names", return_value={}), \
                contextlib.redirect_stdout(out):
            function(args)
        return out.getvalue(), search

    def test_contacts_fast_reads_current_v3_content_table(self):
        self.database("contact/contact_fts.db", [
            ("CREATE TABLE contact_fts_v3_content(id INTEGER PRIMARY KEY, c0, c1)", ()),
            ("INSERT INTO contact_fts_v3_content VALUES(1, ?, 1)", ("synthetic_person",)),
        ])
        out, fallback = self.invoke(cli.cmd_contacts_fast, SimpleNamespace(query="synthetic", n=10))
        self.assertIn("synthetic_person", out)
        fallback.assert_not_called()

    def test_contacts_fast_falls_back_when_index_is_missing(self):
        out, fallback = self.invoke(
            cli.cmd_contacts_fast, SimpleNamespace(query="synthetic", n=10),
            [{"username": "synthetic_user", "nick_name": "Synthetic Name"}],
        )
        self.assertIn("Synthetic Name", out)
        fallback.assert_called_once_with("synthetic", 10)

    def test_fast_message_search_discovers_shards_after_four(self):
        self.database("message/message_fts.db", [
            ("CREATE TABLE name2id(username TEXT)", ()),
            ("INSERT INTO name2id VALUES ('test_session')", ()),
            ("CREATE TABLE message_fts_v4_5_content(id INTEGER PRIMARY KEY,c0,c4,c5,c6)", ()),
            ("INSERT INTO message_fts_v4_5_content VALUES(1, ?, 1, 1, 1)", ("synthetic_message",)),
        ])
        out, _ = self.invoke(cli.cmd_search_fast, SimpleNamespace(keyword="synthetic", n=10))
        self.assertIn("synthetic_message", out)

    def test_favorite_search_discovers_content_table_version(self):
        self.database("favorite/favorite_fts.db", [
            ("CREATE TABLE fav_fts_v2_content(id INTEGER PRIMARY KEY,c0,c1,c2,c3)", ()),
            ("INSERT INTO fav_fts_v2_content VALUES(1, ?, 7, 1, 1)", ("synthetic_favorite",)),
        ])
        out, _ = self.invoke(cli.cmd_fav_search, SimpleNamespace(query="synthetic", n=10))
        self.assertIn("synthetic_favorite", out)

    def test_message_search_keeps_distinct_identical_messages(self):
        self.database("message/message_fts.db", [
            ("CREATE TABLE name2id(username TEXT)", ()),
            ("INSERT INTO name2id VALUES ('test_session')", ()),
            ("CREATE TABLE message_fts_v4_0_content(id INTEGER PRIMARY KEY,c0,c4,c5,c6)", ()),
            ("INSERT INTO message_fts_v4_0_content VALUES(1, 'same_message', 1, 1, 1)", ()),
            ("INSERT INTO message_fts_v4_0_content VALUES(2, 'same_message', 1, 1, 1)", ()),
        ])
        out, _ = self.invoke(cli.cmd_search_fast, SimpleNamespace(keyword="same_message", n=10))
        self.assertEqual(sum(line.startswith("  [") for line in out.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
