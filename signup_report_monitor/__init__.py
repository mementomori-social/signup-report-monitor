"""signup-report-monitor: Mastodon admin webhooks -> Matrix admins room.

A small, dependency-light Python daemon that receives Mastodon admin webhook
events, enriches new signups (offline GeoIP + optional Claude risk verdict),
posts them into a Matrix room, and (optionally) lets moderators approve or
reject pending accounts by reacting to the message.
"""

__version__ = "2.0.0"
