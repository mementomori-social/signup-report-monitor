# signup-monitor

A tiny, zero-dependency **Mastodon → Matrix** forwarder. It receives Mastodon
admin webhook events and posts them into a Matrix room so your admins see new
signups and reports as they happen.

Handled events:

- **`account.created`** — 👤 new user signup (username, email, invite request,
  link to the pending-accounts queue)
- **`report.created`** — 🚨 new report (category, comment, reported account,
  link to the report)

```
Mastodon instance ──webhook POST──▶ signup-monitor (this) ──▶ Matrix admins room
```

## Requirements

- PHP 7.4+ with the `curl` extension (no Composer, no build step)
- A web server that can run PHP (nginx + PHP-FPM, Apache, or `php -S`)
- A Matrix bot account with an access token and rights to post in the room
- Admin access on your Mastodon instance to register a webhook

## Setup

1. **Clone & configure**

   ```bash
   git clone git@github.com:mementomori-social/signup-monitor.git
   cd signup-monitor
   cp .env.example .env
   $EDITOR .env   # fill in Matrix + Mastodon values
   ```

2. **Get a Matrix bot token & room ID**
   - Log in as the bot account and copy its access token (Element:
     *Settings → Help & About → Advanced → Access Token*), or provision one via
     the login API.
   - The room ID is the **internal** ID (starts with `!`, e.g.
     `!abc123:chat.example.social`) — not the `#alias`. Invite the bot and make
     sure it has joined.

3. **Serve `webhook.php`** behind HTTPS. Example nginx location (PHP-FPM):

   ```nginx
   # https://chat.example.social/hooks/mastodon
   location = /hooks/mastodon {
       fastcgi_pass unix:/run/php/php-fpm.sock;
       fastcgi_param SCRIPT_FILENAME /srv/signup-monitor/webhook.php;
       include fastcgi_params;
   }
   ```

   Or, for a quick test: `php -S 127.0.0.1:8099 webhook.php`.

4. **Register the webhook in Mastodon**
   *Admin → Settings → Webhooks → New webhook*
   - **URL:** the public URL from step 3 (e.g.
     `https://chat.example.social/hooks/mastodon`)
   - **Events:** `account.created`, `report.created`
   - Copy the generated **signing secret** into `MASTODON_SIGNING_SECRET` in
     `.env` (or leave blank to skip verification).

5. **Test.** Create a test signup (or use Mastodon's webhook "resend"). You
   should see a message land in the Matrix room, and `event=… matrix_http=200`
   in the log.

## Configuration

All configuration is via `.env` — see [`.env.example`](.env.example) for the
full list. `.env` is gitignored; never commit real secrets.

## Notes

- **Privacy:** by default the log records only the event type and the Matrix
  HTTP status — no emails or IPs. Set `DEBUG=true` only when troubleshooting
  (it logs raw payloads, which contain PII), and keep `LOG_FILE` outside any
  web-served directory.
- **Security:** when `MASTODON_SIGNING_SECRET` is set, requests must carry a
  matching `Signature` header or they're rejected with `403`.

## License

MIT
