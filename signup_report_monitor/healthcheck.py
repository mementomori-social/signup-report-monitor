"""Standalone check that the AI analyser can still authenticate.

Run on its own schedule (a systemd timer), independent of the webhook
service, so an auth break is caught within hours instead of waiting for the
next real signup to reveal it silently as "AI recommendation: unavailable".

Posts a Matrix message only on a state change (healthy -> broken or broken ->
healthy), tracked in the same sqlite store the reaction worker uses, so a
sustained outage does not spam the room on every run.
"""

import html
import logging

from .analyser import check_auth
from .config import Config
from .matrix import MatrixClient, MatrixError
from .store import Store

log = logging.getLogger("signup-report-monitor.healthcheck")

_META_KEY = "claude_auth_ok"


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    cfg = Config()
    if not cfg.claude_enabled:
        log.info("claude analyser disabled, nothing to check")
        return 0

    store = Store(cfg.state_dir)
    ok, reason = check_auth(cfg)
    was_ok = store.get_meta(_META_KEY, "true") == "true"

    if ok == was_ok:
        log.info("claude auth check: %s (no change)", "ok" if ok else "still broken")
        return 0

    store.set_meta(_META_KEY, "true" if ok else "false")
    _notify(cfg, ok, reason)
    log.info("claude auth check: transitioned to %s (%s)", "ok" if ok else "broken", reason or "")
    return 0


def _notify(cfg, ok, reason):
    matrix = MatrixClient(cfg.matrix_base_url, cfg.matrix_access_token)
    mentions = [cfg.ping_user_id] if cfg.ping_user_id else None
    if ok:
        plain = "✅ AI recommendation is working again."
        body = plain
    else:
        plain = (
            "⚠️ AI recommendation is broken: %s\n\n"
            "Run `claude setup-token` as rolle and update "
            "/home/rolle/.config/claude/token.env." % reason
        )
        body = (
            "⚠️ <strong>AI recommendation is broken:</strong> %s<br><br>"
            "Run <code>claude setup-token</code> as rolle and update "
            "<code>/home/rolle/.config/claude/token.env</code>."
            % html.escape(str(reason))
        )
    if cfg.ping_plain or cfg.ping_html:
        plain += "\n\n%s" % (cfg.ping_plain or "")
        body += "<br><br>%s" % (cfg.ping_html or "")
    try:
        matrix.send_message(cfg.matrix_room_id, plain, body, mention_user_ids=mentions)
    except MatrixError as exc:
        log.error("failed to post health check alert: http=%s", exc.status)


if __name__ == "__main__":
    raise SystemExit(main())
