"""Reaction worker (2C): approve/reject pending signups from Matrix.

Runs a Matrix /sync loop. When a moderator reacts to one of our signup review
messages with an approve or reject emoji, we call the Mastodon admin API and
confirm back in a thread. Only reactions to messages we posted (tracked in the
store) are acted on; the bot's own reactions and already-resolved messages are
ignored.
"""

import logging
import time
import urllib.error

from .mastodon import MastodonAdmin
from .matrix import MatrixError


def _describe(exc, noun):
    """Human-readable reason for a failed admin call, for the Matrix message."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "%s not found, it may already be handled" % noun
        if exc.code == 403:
            return "permission denied, check the admin token scope"
        if exc.code == 401:
            return "authentication failed, check the admin token"
        return "HTTP %s %s" % (exc.code, exc.reason)
    return str(exc)

log = logging.getLogger("signup-report-monitor.worker")

def _strip_vs(key):
    """Drop emoji variation selectors so '❌' with U+FE0F matches plain '❌'."""
    return (key or "").replace("\ufe0f", "").replace("\ufe0e", "")


# Compared after _strip_vs, so list the base code points only.
APPROVE_KEYS = {_strip_vs(k) for k in ("✅", "☑", "\U0001F44D")}  # ✅ ☑️ 👍
REJECT_KEYS = {_strip_vs(k) for k in ("❌", "✖", "\U0001F44E", "\U0001F6AB")}  # ❌ ✖️ 👎 🚫


class ReactionWorker:
    def __init__(self, services):
        self.services = services
        self.cfg = services.cfg
        self.matrix = services.matrix
        self.store = services.store
        self.admin = MastodonAdmin(self.cfg.mastodon_base_url, self.cfg.mastodon_admin_token)
        self.user_id = None

    def _filter(self):
        import json

        return json.dumps(
            {
                "room": {
                    "rooms": [self.cfg.matrix_room_id],
                    "timeline": {"limit": 30, "types": ["m.reaction"]},
                    "state": {"types": []},
                },
                "presence": {"types": []},
                "account_data": {"types": []},
            }
        )

    def run(self):
        if not self.cfg.mastodon_admin_token:
            log.error("REACTIONS_ENABLED but MASTODON_ADMIN_TOKEN is empty; worker idle")
            return
        try:
            self.user_id = self.matrix.whoami()
        except MatrixError as exc:
            log.error("worker whoami failed: %s", exc)
        # Start from the stored position, or from "now" so we do not replay old
        # reactions on first launch.
        since = self.store.get_meta("sync_since")
        filt = self._filter()
        if not since:
            try:
                first = self.matrix.sync(since=None, timeout_ms=0, filter_json=filt)
                since = first.get("next_batch")
                self.store.set_meta("sync_since", since)
                log.info("worker initialised sync position")
            except MatrixError as exc:
                log.error("worker initial sync failed: %s", exc)

        backoff = 1
        while True:
            try:
                data = self.matrix.sync(since=since, timeout_ms=30000, filter_json=filt)
                backoff = 1
                since = data.get("next_batch", since)
                self.store.set_meta("sync_since", since)
                self._handle_sync(data)
            except MatrixError as exc:
                log.warning("worker sync error http=%s; backing off %ss", exc.status, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception:
                log.exception("worker sync loop error; backing off %ss", backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _handle_sync(self, data):
        rooms = (data.get("rooms") or {}).get("join") or {}
        room = rooms.get(self.cfg.matrix_room_id)
        if not room:
            return
        for event in (room.get("timeline") or {}).get("events") or []:
            if event.get("type") != "m.reaction":
                continue
            if event.get("sender") == self.user_id:
                continue
            relates = (event.get("content") or {}).get("m.relates_to") or {}
            if relates.get("rel_type") != "m.annotation":
                continue
            target = relates.get("event_id")
            key = relates.get("key")
            self._handle_reaction(target, key, event.get("sender"))

    def _handle_reaction(self, target_event_id, key, sender):
        key = _strip_vs(key)
        if key in APPROVE_KEYS:
            intent = "approve"
        elif key in REJECT_KEYS:
            intent = "reject"
        else:
            return
        record = self.store.lookup(target_event_id)
        if not record:
            return  # not one of our review messages
        if record.get("resolved"):
            log.info("reaction ignored: already %s", record["resolved"])
            return
        target = record["target_id"]
        label = record.get("label") or target
        if record["kind"] == "account":
            self._act_account(target_event_id, target, label, intent, sender)
        elif record["kind"] == "report":
            self._act_report(target_event_id, target, label, sender)

    def _act_account(self, event_id, account_id, username, intent, sender):
        try:
            if intent == "approve":
                status, _ = self.admin.approve(account_id)
            else:
                status, _ = self.admin.reject(account_id)
        except Exception as exc:
            self._confirm(event_id, "⚠️ Could not %s @%s: %s" % (intent, username, _describe(exc, "account")))
            return
        self.store.mark_resolved(event_id, intent)
        done = "approved" if intent == "approve" else "rejected"
        emoji = "✅" if intent == "approve" else "❌"
        self._confirm(event_id, "%s Signup @%s %s (by %s)" % (emoji, username, done, sender or "?"))

    def _act_report(self, event_id, report_id, label, sender):
        # Reports have a single closing action: resolve (both emoji mean "handled").
        try:
            status, _ = self.admin.resolve_report(report_id)
        except Exception as exc:
            self._confirm(event_id, "⚠️ Could not resolve report #%s: %s" % (report_id, _describe(exc, "report")))
            return
        self.store.mark_resolved(event_id, "resolve")
        who = ("against @%s " % label) if label else ""
        self._confirm(event_id, "✅ Report #%s %sresolved (by %s)" % (report_id, who, sender or "?"))

    def _confirm(self, thread_event_id, text):
        try:
            self.matrix.send_thread_reply(self.cfg.matrix_room_id, thread_event_id, text)
        except MatrixError as exc:
            log.warning("confirm reply failed http=%s", exc.status)
