"""Configuration loader.

Reads key=value pairs from a .env file (real environment variables win over
the file). No external dependencies: this is a deliberately tiny parser, not a
full dotenv implementation. Lines that are blank or start with # are ignored;
surrounding single or double quotes on a value are stripped.
"""

import os


def _parse_env_file(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key] = value
    except FileNotFoundError:
        pass
    return values


class Config:
    """Resolved configuration. Real env vars override the .env file."""

    def __init__(self, env_path=None):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.env_path = env_path or os.path.join(here, ".env")
        file_values = _parse_env_file(self.env_path)

        def get(key, default=None):
            if key in os.environ and os.environ[key] != "":
                return os.environ[key]
            return file_values.get(key, default)

        # Matrix
        self.matrix_base_url = (get("MATRIX_BASE_URL") or "").rstrip("/")
        self.matrix_access_token = get("MATRIX_ACCESS_TOKEN") or ""
        self.matrix_room_id = get("MATRIX_ROOM_ID") or ""

        # Mastodon
        self.mastodon_base_url = (get("MASTODON_BASE_URL") or "").rstrip("/")
        self.mastodon_signing_secret = get("MASTODON_SIGNING_SECRET") or ""
        self.mastodon_admin_token = get("MASTODON_ADMIN_TOKEN") or ""

        # Optional ping / mention
        self.ping_plain = get("PING_PLAIN") or ""
        self.ping_html = get("PING_HTML") or ""
        # User id to intentionally mention (m.mentions) so the ping actually
        # notifies/highlights. Explicit PING_USER_ID wins; otherwise derive it
        # from a matrix.to link in PING_HTML.
        self.ping_user_id = get("PING_USER_ID") or self._derive_ping_user_id()

        # HTTP listener (behind nginx)
        self.listen_addr = get("LISTEN_ADDR") or "127.0.0.1"
        self.listen_port = int(get("LISTEN_PORT") or "8099")
        self.webhook_path = get("WEBHOOK_PATH") or "/hooks/mastodon"

        # GeoIP (offline MaxMind mmdb). Empty = disabled.
        self.geoip_city_db = get("GEOIP_CITY_DB") or ""
        self.geoip_asn_db = get("GEOIP_ASN_DB") or ""

        # Claude analyser
        self.claude_enabled = (get("CLAUDE_ENABLED") or "false").lower() == "true"
        self.claude_bin = get("CLAUDE_BIN") or "claude"
        self.claude_timeout = int(get("CLAUDE_TIMEOUT") or "240")
        # Model alias for the latest, smartest model (e.g. "opus").
        self.claude_model = get("CLAUDE_MODEL") or "opus"
        # Allow read-only web lookups (email/IP/domain reputation) during analysis.
        self.claude_web = (get("CLAUDE_WEB") or "true").lower() == "true"

        # Reaction worker (emoji approve/reject). Empty = disabled.
        self.reactions_enabled = (get("REACTIONS_ENABLED") or "false").lower() == "true"
        self.state_dir = get("STATE_DIR") or os.path.join(here, "state")

        # Logging
        self.log_file = get("LOG_FILE") or ""
        self.debug = (get("DEBUG") or "false").lower() == "true"

    def _derive_ping_user_id(self):
        import re

        match = re.search(r"matrix\.to/#/(@[^\"'>?]+)", self.ping_html or "")
        return match.group(1) if match else ""

    def require_core(self):
        """Fail fast if the must-have values for posting are missing."""
        missing = [
            name
            for name, value in (
                ("MATRIX_BASE_URL", self.matrix_base_url),
                ("MATRIX_ACCESS_TOKEN", self.matrix_access_token),
                ("MATRIX_ROOM_ID", self.matrix_room_id),
                ("MASTODON_SIGNING_SECRET", self.mastodon_signing_secret),
            )
            if not value
        ]
        if missing:
            raise SystemExit("Missing required config: " + ", ".join(missing))
