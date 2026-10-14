"""Extract and canonicalize Telegram MTProto / SOCKS proxy links."""
import html
import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

_LINK_PATTERN = re.compile(
    r"(?:(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/|tg://)"
    r"(?:proxy|socks)\?[^\s<>\"'\]\)]+",
    re.IGNORECASE,
)
_SOCKS_ENDPOINT_PATTERN = re.compile(r"\s*(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})\s*")

class _TelegramLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.urls.append(href)

def normalize_proxy_link(value):
    """Validate proxy URI syntax and return normalized t.me URL (not liveness)."""
    if not isinstance(value, str):
        return None
    raw = html.unescape(html.unescape(value.strip())).strip(" \t\r\n<>\"'")
    raw = raw.rstrip(".,;)")
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.lower().startswith(("t.me/", "telegram.me/", "telegram.dog/")):
        raw = "https://" + raw
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() == "tg":
        if parsed.netloc.lower() not in ("proxy", "socks") or parsed.path:
            return None
        kind = parsed.netloc.lower()
    else:
        kind = parsed.path.strip("/").lower()
        if kind not in ("proxy", "socks"):
            return None
        if parsed.scheme.lower() not in ("http", "https") or parsed.netloc.lower() not in ("t.me", "telegram.me", "telegram.dog", "www.t.me"):
            return None
    params = parse_qs(parsed.query, keep_blank_values=True)
    server = params.get("server", [""])[0].strip().rstrip(".")
    port_text = params.get("port", [""])[0].strip()
    if not server or server.lower() == "unknown" or not port_text.isdecimal():
        return None
    port = int(port_text)
    if not 1 <= port <= 65535:
        return None
    if any(c in server for c in "/\\?#&=@ \r\n\t"):
        return None
    try:
        server = server.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if len(server) > 253 or not re.fullmatch(r"[a-z0-9_:\.\-]+", server):
        return None
    fields = [("server", server), ("port", str(port))]
    if kind == "proxy":
        secret = params.get("secret", [""])[0].strip().replace(" ", "+")
        if not re.fullmatch(r"[A-Za-z0-9_+\/\-=]{16,512}", secret):
            return None
        fields.append(("secret", secret))
    else:
        for param in ("user", "pass"):
            if param in params:
                fields.append((param, params[param][0]))
    return "https://t.me/{}?{}".format(kind, urlencode(fields))

def extract_proxy_links(content):
    """Read HTML button hrefs and plain-text links, keeping unique proxy URLs."""
    if not isinstance(content, str):
        return []
    parser = _TelegramLinkParser()
    try:
        parser.feed(content)
    except (ValueError, AssertionError):
        pass
    candidates = parser.urls + _LINK_PATTERN.findall(html.unescape(content))
    found, seen = [], set()
    for candidate in candidates:
        normalized = normalize_proxy_link(candidate)
        if normalized and normalized not in seen:
            found.append(normalized)
            seen.add(normalized)
    return found

def extract_socks5_endpoints(content):
    """Convert bare IPv4:port lines from the configured SOCKS source."""
    found, seen = [], set()
    for row in content.splitlines():
        match = _SOCKS_ENDPOINT_PATTERN.fullmatch(row)
        if not match:
            continue
        ip, port = match.groups()
        try:
            ipaddress.IPv4Address(ip)
        except ipaddress.AddressValueError:
            continue
        url = normalize_proxy_link("https://t.me/socks?" + urlencode({"server": ip, "port": port}))
        if url and url not in seen:
            found.append(url)
            seen.add(url)
    return found
