"""Webhook HTTP server and event processing.

Runs a small threaded HTTP server (bound to localhost, behind nginx). Each
request is verified against the Mastodon signing secret, then dispatched. The
slow parts (GeoIP, Claude) run inline in the request thread but only for
account.created; Matrix delivery is what we log for the cutover check.

Logging is PII-safe by default: only the event type and Matrix HTTP status.
Set DEBUG=true transiently to log message bodies.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import analyser, geoip as geoip_mod, messages
from .mastodon import verify_signature
from .matrix import MatrixError

log = logging.getLogger("signup-report-monitor")

# The comprehensive web-enabled analysis takes 30-60s, far longer than
# Mastodon's webhook timeout. So we post immediately and run the analysis on
# this pool, editing the verdict into the message when it finishes.
_ANALYSIS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analyser")


class Services:
    """Everything the request handler needs, assembled once at startup."""

    def __init__(self, cfg, matrix, geoip, store):
        self.cfg = cfg
        self.matrix = matrix
        self.geoip = geoip
        self.store = store


def process_event(services, event, obj):
    """Enrich, format, and post one webhook event. Returns Matrix HTTP status."""
    cfg = services.cfg
    if event == "account.created":
        gp = None
        ip = geoip_mod.extract_ip(obj)
        if services.geoip is not None:
            gp = services.geoip.lookup(ip)
        if gp is None and ip:
            gp = {"ip": ip}  # no offline DB, but still give the analyser the ip
        signup = {
            "username": obj.get("username") or messages._acct_username(obj),
            "email": obj.get("email"),
            "language": messages.language_name(obj.get("locale")),
            "created_at": obj.get("created_at"),
            "invite_request": obj.get("invite_request"),
            "geoip": gp,
        }
        pending = {"pending": True} if cfg.claude_enabled else None
        plain, html = messages.format_account_created(obj, cfg, geoip=gp, verdict=pending)
        event_id, status = _post(services, plain, html)
        if event_id and services.store is not None:
            services.store.record_account(event_id, obj.get("id"), signup["username"])
        if cfg.claude_enabled and event_id:
            _ANALYSIS_POOL.submit(_run_analysis, services, obj, gp, signup, event_id)
        return status
    if event == "report.created":
        plain, html = messages.format_report_created(obj, cfg)
        event_id, status = _post(services, plain, html)
        if event_id and services.store is not None:
            label = messages._acct_username(obj.get("target_account") or {})
            services.store.record_report(event_id, obj.get("id"), label)
        return status
    log.info("event=%s ignored=1", event)
    return None


def _run_analysis(services, obj, geoip, signup, event_id):
    """Run the (slow) analysis off the request path, then edit the verdict in."""
    cfg = services.cfg
    try:
        verdict = analyser.analyse(cfg, signup)
    except Exception:
        log.exception("analysis error")
        verdict = None
    final = verdict or {"error": True}
    try:
        plain, html = messages.format_account_created(obj, cfg, geoip=geoip, verdict=final)
        services.matrix.edit_message(cfg.matrix_room_id, event_id, plain, html)
    except MatrixError as exc:
        log.error("analysis edit failed http=%s", exc.status)
        return
    if verdict:
        log.info("event=account.analysis verdict=%s risk=%s", verdict.get("verdict"), verdict.get("risk"))
    else:
        log.info("event=account.analysis verdict=unavailable")


def _post(services, plain, html):
    cfg = services.cfg
    if cfg.debug:
        log.debug("posting message:\n%s", plain)
    mentions = [cfg.ping_user_id] if cfg.ping_user_id else None
    try:
        event_id = services.matrix.send_message(cfg.matrix_room_id, plain, html, mention_user_ids=mentions)
        return event_id, 200
    except MatrixError as exc:
        log.error("matrix send failed http=%s", exc.status)
        return None, exc.status


class Handler(BaseHTTPRequestHandler):
    services = None  # injected on the server instance

    def log_message(self, *args):
        pass  # silence default stderr access logging; we log our own lines

    def _reply(self, code, text="", ):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        cfg = self.server.services.cfg
        if self.path == "/healthz":
            self._reply(200, "ok\n")
            return
        if self.path.split("?")[0] == cfg.webhook_path:
            self._reply(405, "method not allowed\n")
            return
        self._reply(404, "not found\n")

    def do_POST(self):
        services = self.server.services
        cfg = services.cfg
        if self.path.split("?")[0] != cfg.webhook_path:
            self._reply(404, "not found\n")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        sig = self.headers.get("X-Hub-Signature", "")
        if not verify_signature(cfg.mastodon_signing_secret, raw, sig):
            log.warning("event=? rejected=bad_signature")
            self._reply(401, "bad signature\n")
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._reply(400, "bad json\n")
            return
        event = payload.get("event", "?")
        obj = payload.get("object") or {}
        try:
            status = process_event(services, event, obj)
        except Exception:  # never leak a 500 stacktrace to the caller
            log.exception("event=%s processing_error=1", event)
            self._reply(500, "error\n")
            return
        if status is not None:
            log.info("event=%s matrix_http=%s", event, status)
        # Ack the webhook even if Matrix delivery failed, so Mastodon does not
        # retry-storm us; failures are visible in our own log.
        self._reply(200, "ok\n")


def serve(services):
    cfg = services.cfg
    server = ThreadingHTTPServer((cfg.listen_addr, cfg.listen_port), Handler)
    server.services = services
    log.info(
        "listening addr=%s port=%s path=%s",
        cfg.listen_addr,
        cfg.listen_port,
        cfg.webhook_path,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
