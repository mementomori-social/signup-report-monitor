# signup-report-monitor

A small Python daemon that forwards Mastodon admin webhook events into a Matrix
room, so moderators see new signups and reports as they happen. New signups can
be enriched with an offline GeoIP lookup and an AI bot/spam risk verdict, and
(optionally) approved or rejected straight from Matrix with an emoji reaction.

```
mementomori.social  --admin webhook-->  signup-report-monitor  --Matrix CS API-->  admins room
                                              |  ^
                                    approve/reject  emoji reaction
```

Stack: **Python 3, no Docker.** The core forwarder uses only the standard
library. GeoIP needs `maxminddb`; the AI verdict shells out to the `claude` CLI.
It runs as a normal systemd service under an ordinary user account (so the
`claude` login is available to it).

## Handled events

- `account.created` -> signup card (username, email, language, reason for
  joining, optional GeoIP + AI verdict, link to pending accounts)
- `report.created`  -> report card (reported account, category, reporter,
  comment, link to the report)

## Layout

- `signup_report_monitor/` - the package
  - `config.py` - .env loader (stdlib, real env vars win)
  - `matrix.py` - minimal Matrix client (send / edit / react / sync)
  - `mastodon.py` - X-Hub-Signature verification + admin approve/reject
  - `messages.py` - webhook payload -> Matrix message (plain + HTML)
  - `geoip.py` - offline City/ASN mmdb lookup (graceful no-op if unavailable)
  - `analyser.py` - AI bot/spam verdict via the claude CLI
  - `store.py` - sqlite map event_id -> account/report id (for reactions)
  - `app.py` - webhook HTTP server + event processing
  - `worker.py` - Matrix sync loop for emoji approve/reject
  - `__main__.py` - entry point
- `signup-report-monitor.service` - systemd unit (runs as user `rolle`)
- `.env.example` - documented config template

## Install

```bash
git clone <repo> /home/rolle/signup-report-monitor
cd /home/rolle/signup-report-monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # only needed for GeoIP
cp .env.example .env                            # then edit .env
sudo mkdir -p /var/log/signup-report-monitor && sudo chown rolle:rolle /var/log/signup-report-monitor

# validate config + Matrix connectivity without starting the server
.venv/bin/python -m signup_report_monitor --check
```

### nginx

Add an exact-match location to the `chat.mementomori.social` 443 server block:

```nginx
location = /hooks/mastodon {
    proxy_pass http://127.0.0.1:8099;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header Host $host;
}
```

`sudo nginx -t && sudo systemctl reload nginx`.

### systemd

```bash
sudo cp signup-report-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now signup-report-monitor
```

### Mastodon webhook

In Mastodon admin (Settings -> Webhooks) point the webhook URL at
`https://chat.mementomori.social/hooks/mastodon`, subscribe to `account.created`
and `report.created`, and use the signing secret from `.env`. Hit "resend" on a
past event and confirm `event=... matrix_http=200` appears in the log.

## Features

### GeoIP (2A)

Uses offline City + ASN mmdb databases; no signup IP leaves the host. The free
DB-IP Lite databases need no account or key (CC-BY, updated monthly):

```bash
cd geoip
curl -sSLO https://download.db-ip.com/free/dbip-city-lite-$(date +%Y-%m).mmdb.gz
curl -sSLO https://download.db-ip.com/free/dbip-asn-lite-$(date +%Y-%m).mmdb.gz
gunzip -f dbip-*.mmdb.gz && mv dbip-city-lite-*.mmdb dbip-city.mmdb && mv dbip-asn-lite-*.mmdb dbip-asn.mmdb
```

Point `GEOIP_CITY_DB` / `GEOIP_ASN_DB` at them (GeoLite2 files from MaxMind work
too, same format). If the files or `maxminddb` are missing, the location line is
simply omitted.

### AI assessment (2B)

Set `CLAUDE_ENABLED=true`. Runs **asynchronously**: the message posts instantly
with an "analysing" line, then the verdict is edited in, so the slow model call
never blocks or times out the webhook. For each signup the daemon runs
`claude -p ... --output-format json --model opus` **as the service user** (that
user must be logged into Claude Code), optionally with read-only web tools
(`CLAUDE_WEB=true`) to check email/IP/domain reputation. It renders a coloured
`risk / verdict` line plus a short plain-prose assessment (the message never
names the model). The signup application text is untrusted, so the model gets
only `WebSearch`/`WebFetch`, never Bash. Uses the Claude Code subscription, not
the paid API.

### Emoji approve/reject (2C)

Set `REACTIONS_ENABLED=true` and provide `MASTODON_ADMIN_TOKEN` (a token with
`admin:write`). The daemon runs a Matrix `/sync` loop; reacting to a signup
message with the checkmark emoji approves the account, the cross rejects it, and
the bot confirms in the room. The event_id -> account_id map is kept in a small
sqlite file under `STATE_DIR`.

## Logging

PII-safe by default: only the event type and Matrix HTTP status are logged
(`event=account.created matrix_http=200`). `DEBUG=true` additionally logs message
bodies; set it only transiently. `LOG_FILE` rotates at 5 MB (3 backups) and must
live outside any web-served directory.

## Operational notes

- Secrets live only in `.env` (gitignored). Never commit them.
- The webhook handler always returns 200 to Mastodon once the signature checks
  out, even if Matrix delivery failed, to avoid retry storms; delivery failures
  are visible in the log.
