"""SQLite reader for already-validated, standalone decrypted snapshots.

These files have no live WAL to replay. Ordinary connections may create WAL/SHM
files even for SELECTs; mode=ro alone can also fail on a WAL-format snapshot.
Keep SQLite's default row factory so legacy CLI callers still receive tuples.
"""
import sqlite3
from pathlib import Path


def connect_snapshot(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)
