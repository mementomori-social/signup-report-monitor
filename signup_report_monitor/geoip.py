"""Offline GeoIP enrichment using MaxMind GeoLite2 mmdb files.

No signup IP ever leaves the host. Uses the `maxminddb` reader if installed;
if the library or the DB files are absent, every lookup returns None and the
message is simply posted without a location line (graceful degradation).
"""

try:
    import maxminddb
except Exception:  # pragma: no cover - optional dependency
    maxminddb = None


def extract_ip(obj):
    """Best-effort signup IP from an Admin::Account webhook object."""
    ip = obj.get("ip")
    if ip:
        return ip if isinstance(ip, str) else ip.get("ip")
    ips = obj.get("ips")
    if isinstance(ips, list) and ips:
        first = ips[0]
        return first.get("ip") if isinstance(first, dict) else first
    return None


class GeoIP:
    def __init__(self, city_db="", asn_db=""):
        self.city = self._open(city_db)
        self.asn = self._open(asn_db)

    @staticmethod
    def _open(path):
        if not path or maxminddb is None:
            return None
        try:
            return maxminddb.open_database(path)
        except Exception:
            return None

    @property
    def available(self):
        return self.city is not None or self.asn is not None

    def lookup(self, ip):
        """Return {'ip','country','city','asn','org'} or None."""
        if not ip or not self.available:
            return None
        result = {"ip": ip}
        try:
            if self.city:
                rec = self.city.get(ip) or {}
                country = (rec.get("country") or {}).get("names", {}).get("en")
                city = (rec.get("city") or {}).get("names", {}).get("en")
                if country:
                    result["country"] = country
                if city:
                    result["city"] = city
            if self.asn:
                rec = self.asn.get(ip) or {}
                asn = rec.get("autonomous_system_number")
                org = rec.get("autonomous_system_organization")
                if asn:
                    result["asn"] = asn
                if org:
                    result["org"] = org
        except Exception:
            return None
        # Only useful if we resolved at least one field beyond the ip.
        return result if len(result) > 1 else None
