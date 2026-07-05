"""Minimal Matrix client-server API client (stdlib only).

Covers what the daemon needs: send an m.room.message, edit one, add an
m.reaction, and long-poll /sync. No mautrix, no aiohttp: plain urllib.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

_TXN_COUNTER = [0]


def _next_txn():
    _TXN_COUNTER[0] += 1
    return "sm-%d-%d" % (int(time.time() * 1000), _TXN_COUNTER[0])


class MatrixError(Exception):
    def __init__(self, status, body):
        super().__init__("Matrix HTTP %s: %s" % (status, body))
        self.status = status
        self.body = body


class MatrixClient:
    def __init__(self, base_url, access_token, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout

    def _request(self, method, path, params=None, body=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {"Authorization": "Bearer " + self.access_token}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise MatrixError(exc.code, raw)

    def send_message(self, room_id, plain, html=None, mention_user_ids=None):
        """Send a message; returns the event_id.

        Uses m.text (not m.notice) so it can notify, and sets m.mentions so the
        pinged user is actually highlighted. m.notice would be dropped by the
        default suppress_notices push rule before the mention rule runs.
        """
        content = {"msgtype": "m.text", "body": plain}
        if html:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = html
        if mention_user_ids:
            content["m.mentions"] = {"user_ids": list(mention_user_ids)}
        txn = _next_txn()
        path = "/_matrix/client/v3/rooms/%s/send/m.room.message/%s" % (
            urllib.parse.quote(room_id),
            txn,
        )
        _, data = self._request("PUT", path, body=content)
        return data.get("event_id")

    def edit_message(self, room_id, target_event_id, plain, html=None):
        """Replace a previously sent message via m.replace."""
        new_content = {"msgtype": "m.notice", "body": plain}
        if html:
            new_content["format"] = "org.matrix.custom.html"
            new_content["formatted_body"] = html
        content = dict(new_content)
        content["body"] = "* " + plain
        content["m.new_content"] = new_content
        content["m.relates_to"] = {
            "rel_type": "m.replace",
            "event_id": target_event_id,
        }
        txn = _next_txn()
        path = "/_matrix/client/v3/rooms/%s/send/m.room.message/%s" % (
            urllib.parse.quote(room_id),
            txn,
        )
        _, data = self._request("PUT", path, body=content)
        return data.get("event_id")

    def send_thread_reply(self, room_id, thread_event_id, plain, html=None):
        content = {"msgtype": "m.notice", "body": plain}
        if html:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = html
        content["m.relates_to"] = {
            "rel_type": "m.thread",
            "event_id": thread_event_id,
            "is_falling_back": True,
            "m.in_reply_to": {"event_id": thread_event_id},
        }
        txn = _next_txn()
        path = "/_matrix/client/v3/rooms/%s/send/m.room.message/%s" % (
            urllib.parse.quote(room_id),
            txn,
        )
        _, data = self._request("PUT", path, body=content)
        return data.get("event_id")

    def react(self, room_id, target_event_id, emoji):
        content = {
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": target_event_id,
                "key": emoji,
            }
        }
        txn = _next_txn()
        path = "/_matrix/client/v3/rooms/%s/send/m.reaction/%s" % (
            urllib.parse.quote(room_id),
            txn,
        )
        _, data = self._request("PUT", path, body=content)
        return data.get("event_id")

    def whoami(self):
        _, data = self._request("GET", "/_matrix/client/v3/account/whoami")
        return data.get("user_id")

    def sync(self, since=None, timeout_ms=30000, filter_json=None):
        params = {"timeout": str(timeout_ms)}
        if since:
            params["since"] = since
        if filter_json:
            params["filter"] = filter_json
        _, data = self._request(
            "GET",
            "/_matrix/client/v3/sync",
            params=params,
        )
        return data
