"""Entry point: `python3 -m signup_report_monitor`.

Wires config, Matrix client, GeoIP, and state store into the webhook server.
When REACTIONS_ENABLED=true, also starts the Matrix sync worker (2C) in a
background thread.
"""

import argparse
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from .app import Services, serve
from .config import Config
from .geoip import GeoIP
from .matrix import MatrixClient
from .store import Store


def _setup_logging(cfg):
    root = logging.getLogger("signup-report-monitor")
    root.setLevel(logging.DEBUG if cfg.debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers = []
    if cfg.log_file:
        try:
            fh = RotatingFileHandler(
                cfg.log_file, maxBytes=5 * 1024 * 1024, backupCount=3
            )
            fh.setFormatter(fmt)
            handlers.append(fh)
        except OSError as exc:
            print("cannot open LOG_FILE %s: %s" % (cfg.log_file, exc), file=sys.stderr)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    handlers.append(sh)
    for handler in handlers:
        root.addHandler(handler)
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(prog="signup_report_monitor")
    parser.add_argument("--env", help="path to .env file")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate config and connectivity, then exit",
    )
    args = parser.parse_args(argv)

    cfg = Config(env_path=args.env)
    cfg.require_core()
    log = _setup_logging(cfg)

    matrix = MatrixClient(cfg.matrix_base_url, cfg.matrix_access_token)
    geoip = GeoIP(cfg.geoip_city_db, cfg.geoip_asn_db)
    store = Store(cfg.state_dir)
    services = Services(cfg, matrix, geoip, store)

    if args.check:
        try:
            user = matrix.whoami()
            log.info("check: matrix ok user=%s", user)
        except Exception as exc:
            log.error("check: matrix FAILED: %s", exc)
            return 1
        log.info(
            "check: geoip=%s claude=%s reactions=%s",
            "on" if geoip.available else "off",
            "on" if cfg.claude_enabled else "off",
            "on" if cfg.reactions_enabled else "off",
        )
        return 0

    if cfg.reactions_enabled:
        try:
            from .worker import ReactionWorker

            worker = ReactionWorker(services)
            thread = threading.Thread(target=worker.run, name="reaction-worker", daemon=True)
            thread.start()
            log.info("reaction worker started")
        except Exception:
            log.exception("failed to start reaction worker")

    serve(services)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
