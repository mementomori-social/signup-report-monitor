"""Tiny persistent map: Matrix event_id -> the Mastodon object it reviews.

Used by the reaction worker to resolve which pending account or report a
moderator acted on by reacting to a review message. `kind` is 'account' or
'report'; `target_id` is the account id or report id. sqlite3 is stdlib, so
still zero external dependencies.
"""

import os
import sqlite3
import time


class Store:
    def __init__(self, state_dir):
        os.makedirs(state_dir, exist_ok=True)
        self.path = os.path.join(state_dir, "signup-report-monitor.db")
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS review_messages ("
            " event_id TEXT PRIMARY KEY,"
            " kind TEXT NOT NULL,"
            " target_id TEXT NOT NULL,"
            " label TEXT,"
            " created_at INTEGER NOT NULL,"
            " resolved TEXT)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        self._conn.commit()

    def _record(self, event_id, kind, target_id, label):
        if not event_id or not target_id:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO review_messages"
            " (event_id, kind, target_id, label, created_at, resolved)"
            " VALUES (?, ?, ?, ?, ?, NULL)",
            (event_id, kind, str(target_id), label, int(time.time())),
        )
        self._conn.commit()

    def record_account(self, event_id, account_id, username):
        self._record(event_id, "account", account_id, username)

    def record_report(self, event_id, report_id, label):
        self._record(event_id, "report", report_id, label)

    def lookup(self, event_id):
        row = self._conn.execute(
            "SELECT kind, target_id, label, resolved FROM review_messages"
            " WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            return None
        return {"kind": row[0], "target_id": row[1], "label": row[2], "resolved": row[3]}

    def mark_resolved(self, event_id, action):
        self._conn.execute(
            "UPDATE review_messages SET resolved = ? WHERE event_id = ?",
            (action, event_id),
        )
        self._conn.commit()

    def get_meta(self, key, default=None):
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()
