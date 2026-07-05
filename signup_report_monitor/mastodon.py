"""Mastodon webhook signature verification and admin API calls.

Signature scheme (from mastodon app/workers/webhooks/delivery_worker.rb):
    header  X-Hub-Signature: sha256=<hex>
    digest  HMAC-SHA256(webhook.secret, raw_request_body)
We verify against the exact raw bytes received, with a constant-time compare.
"""

import hashlib
import hmac
import json
import urllib.error
import urllib.request


def verify_signature(secret, raw_body, header_value):
    """Return True iff X-Hub-Signature matches HMAC-SHA256 of raw_body."""
    if not header_value or not secret:
        return False
    prefix = "sha256="
    if not header_value.startswith(prefix):
        return False
    provided = header_value[len(prefix):].strip()
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(provided, expected)


class MastodonAdmin:
    """Admin API client for approve/reject (needs an admin:write token)."""

    def __init__(self, base_url, admin_token, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.timeout = timeout

    def _post(self, path):
        url = self.base_url + path
        req = urllib.request.Request(
            url,
            data=b"",
            headers={"Authorization": "Bearer " + self.admin_token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})

    def approve(self, account_id):
        return self._post("/api/v1/admin/accounts/%s/approve" % account_id)

    def reject(self, account_id):
        return self._post("/api/v1/admin/accounts/%s/reject" % account_id)

    def resolve_report(self, report_id):
        return self._post("/api/v1/admin/reports/%s/resolve" % report_id)
