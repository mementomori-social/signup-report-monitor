"""Turn a webhook payload into a Matrix message (plain + HTML).

Layout (signup):
    👤 New signup request
    Username: @user      (labels bold in HTML, values plain, never italic)
    Email: ...
    Language: English     (locale code shown as a language name)
    Reasons for joining: ...
    <AI recommendation block>
    View pending accounts        (last line before the ping)

    Ping @user

    React to approve / reject    (only when the reaction worker is enabled)

The AI recommendation is filled in asynchronously: the message is posted with
an "analysing" line, then edited once the model returns.
"""

import html
import re

# House rule: never emit em-dashes or en-dashes. Model output can contain them,
# so we strip them from anything the AI writes before rendering.
_DASH_RE = re.compile("\\s*[\\u2014\\u2013]\\s*")  # unicode em/en dash, kept as escapes


def _no_dash(text):
    return _DASH_RE.sub(", ", text or "")


_LANG = {
    "en": "English", "fi": "Finnish", "sv": "Swedish", "de": "German",
    "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch", "ru": "Russian", "pl": "Polish", "ja": "Japanese",
    "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "tr": "Turkish",
    "uk": "Ukrainian", "cs": "Czech", "da": "Danish", "no": "Norwegian",
    "nb": "Norwegian", "nn": "Norwegian", "et": "Estonian", "hu": "Hungarian",
    "ro": "Romanian", "el": "Greek", "he": "Hebrew", "hi": "Hindi",
    "th": "Thai", "vi": "Vietnamese", "id": "Indonesian", "fa": "Persian",
    "ca": "Catalan", "eu": "Basque", "gl": "Galician", "lt": "Lithuanian",
    "lv": "Latvian", "sk": "Slovak", "sl": "Slovenian", "hr": "Croatian",
    "sr": "Serbian", "bg": "Bulgarian", "is": "Icelandic", "ga": "Irish",
    "cy": "Welsh", "eo": "Esperanto",
}

_VERDICT_EMOJI = {"ALLOW": "\U0001F7E2", "REVIEW": "\U0001F7E1", "DENY": "\U0001F534"}
_VERDICT_COLOR = {"ALLOW": "#2e7d32", "REVIEW": "#f9a825", "DENY": "#c62828"}


def _g(obj, *keys, default=""):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _acct_username(account_obj):
    return _g(account_obj, "username") or _g(account_obj, "account", "username")


def language_name(locale):
    if not locale:
        return ""
    code = str(locale).strip().lower()
    if code in _LANG:
        return _LANG[code]
    base = code.split("-")[0].split("_")[0]
    return _LANG.get(base, locale)


def _kv(plain_lines, html_lines, label, value):
    """Append a 'Label: value' line with a bold label in HTML."""
    plain_lines.append("%s: %s" % (label, value))
    html_lines.append("<strong>%s:</strong> %s" % (html.escape(label), html.escape(str(value))))


def _blank(plain_lines, html_lines):
    plain_lines.append("")
    html_lines.append("")


def _ai_block(plain_lines, html_lines, verdict):
    """Render the AI recommendation block. Handles pending/error/real states."""
    if not verdict:
        return
    _blank(plain_lines, html_lines)  # one empty line before the AI recommendation
    if verdict.get("pending"):
        plain_lines.append("\U0001F916 AI recommendation: analysing...")
        html_lines.append("\U0001F916 <strong>AI recommendation: analysing...</strong>")
        return
    if verdict.get("error"):
        plain_lines.append("⚪ AI recommendation: unavailable")
        html_lines.append("⚪ <strong>AI recommendation: unavailable</strong>")
        return
    label = str(verdict.get("verdict", "?")).upper()
    risk = verdict.get("risk", "?")
    emoji = _VERDICT_EMOJI.get(label, "⚪")
    color = _VERDICT_COLOR.get(label, "#666")
    plain_lines.append("%s AI recommendation: %s (risk %s/100)" % (emoji, label, risk))
    html_lines.append(
        '%s <font color="%s"><strong>AI recommendation: %s (risk %s/100)</strong></font>'
        % (emoji, color, html.escape(label), html.escape(str(risk)))
    )
    assessment = _no_dash(str(verdict.get("assessment") or "")).strip()
    if assessment:
        plain_lines.append(assessment)
        html_lines.append(html.escape(assessment))


def _geoip_line(plain_lines, html_lines, geoip):
    if not geoip:
        return
    parts = []
    loc = ", ".join(p for p in (geoip.get("city"), geoip.get("country")) if p)
    if loc:
        parts.append(loc)
    if geoip.get("org"):
        asn = ("AS%s " % geoip["asn"]) if geoip.get("asn") else ""
        parts.append(asn + geoip["org"])
    if parts:
        _kv(plain_lines, html_lines, "Location", " | ".join(parts))


def _tail(plain_lines, html_lines, cfg, links, hint):
    """One or more view links, then blank + ping, then blank + reaction hint."""
    for label, url in links:
        plain_lines.append("%s: %s" % (label, url))
        html_lines.append(
            '<strong><a href="%s">%s</a></strong>' % (html.escape(url), html.escape(label))
        )
    if cfg.ping_plain or cfg.ping_html:
        _blank(plain_lines, html_lines)
        plain_lines.append("Ping %s" % (cfg.ping_plain or ""))
        html_lines.append("Ping %s" % (cfg.ping_html or ""))
    if getattr(cfg, "reactions_enabled", False) and hint:
        _blank(plain_lines, html_lines)
        plain_lines.append(hint)
        html_lines.append(html.escape(hint))


def format_account_created(obj, cfg, geoip=None, verdict=None, pending_count=None):
    username = _acct_username(obj) or "(unknown)"
    account_id = _g(obj, "id")
    pending_url = "%s/admin/accounts?origin=local&status=pending" % cfg.mastodon_base_url

    plain_lines = ["👤 New signup request"]
    html_lines = ["👤 <strong>New signup request</strong>"]
    _kv(plain_lines, html_lines, "Username", "@%s" % username)

    if _g(obj, "email"):
        _kv(plain_lines, html_lines, "Email", _g(obj, "email"))
    lang = language_name(_g(obj, "locale"))
    if lang:
        _kv(plain_lines, html_lines, "Language", lang)
    _geoip_line(plain_lines, html_lines, geoip)
    if _g(obj, "invite_request"):
        _kv(plain_lines, html_lines, "Reasons for joining", _g(obj, "invite_request"))

    _ai_block(plain_lines, html_lines, verdict)

    links = []
    if account_id:
        links.append(("View this application",
                      "%s/admin/accounts/%s" % (cfg.mastodon_base_url, account_id)))
    pending_label = "View all pending accounts"
    if pending_count is not None:
        pending_label += " (%s)" % pending_count
    links.append((pending_label, pending_url))
    _tail(plain_lines, html_lines, cfg, links, "React ✅ to approve, ❌ to reject")
    return "\n".join(plain_lines), "<br>".join(html_lines)


def format_report_created(obj, cfg):
    report_id = _g(obj, "id")
    reported = _acct_username(_g(obj, "target_account")) or "(unknown)"
    reporter = _acct_username(_g(obj, "account"))
    link = "%s/admin/reports/%s" % (cfg.mastodon_base_url, report_id) if report_id else \
        "%s/admin/reports" % cfg.mastodon_base_url

    plain_lines = ["🚩 New report"]
    html_lines = ["🚩 <strong>New report</strong>"]
    _kv(plain_lines, html_lines, "Reported account", "@%s" % reported)
    if _g(obj, "category"):
        _kv(plain_lines, html_lines, "Category", _g(obj, "category"))
    if reporter:
        _kv(plain_lines, html_lines, "Reported by", "@%s" % reporter)
    if _g(obj, "comment"):
        _kv(plain_lines, html_lines, "Comment", _g(obj, "comment"))

    _tail(plain_lines, html_lines, cfg, [("View report", link)], "React ✅ to resolve")
    return "\n".join(plain_lines), "<br>".join(html_lines)
