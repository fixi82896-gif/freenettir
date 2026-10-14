"""Read-only diagnostic. No bot token, Telegram posts, or repository writes."""
from collections import Counter
from urllib.parse import urlsplit, parse_qs
import socket
import ipaddress
import requests

from proxy_utils import extract_proxy_links
from mtproxy_checker import check_proxy, CheckOptions

SOURCES = [
    "https://t.me/s/ProxyMTProto",
    "https://t.me/s/TelMTProto",
    "https://t.me/s/V2All",
    "https://t.me/s/Myporoxy",
]
LIMIT_PER_SOURCE = 8
OPTIONS = CheckOptions(connect_timeout=2.0, response_timeout=2.0)


def is_public_hostname(url):
    parsed = urlsplit(url)
    host = parse_qs(parsed.query).get("server", [""])[0]
    if not host:
        return False
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(info[4][0]).is_global
            for info in addresses
        )
    except (socket.gaierror, ValueError):
        return False


def main():
    print("LIVE_PROXY_DIAGNOSTIC_START", flush=True)
    unique = set()
    grand = Counter()
    for url in SOURCES:
        label = url.rsplit("/", 1)[-1]
        print(f"SOURCE {label}", flush=True)
        try:
            response = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            candidates = extract_proxy_links(response.text)
        except Exception as exc:
            print(f"SOURCE_ERROR {label}: {type(exc).__name__}", flush=True)
            continue
        print(f"FOUND {label} {len(candidates)}", flush=True)
        sample = []
        for link in candidates:
            if "/proxy?" not in link or link in unique:
                continue
            if not is_public_hostname(link):
                grand["invalid_dns"] += 1
                continue
            unique.add(link)
            sample.append(link)
            if len(sample) == LIMIT_PER_SOURCE:
                break
        counts = Counter()
        for link in sample:
            try:
                result = check_proxy(link, OPTIONS)
                outcome = "verified" if result.ok else str(result.error_code)
                if outcome.startswith("ErrorCode."):
                    outcome = outcome.split(".", 1)[1]
                counts[outcome] += 1
                if result.ok:
                    print(f"VERIFIED {label} rtt_ms={result.rtt_ms:.1f}", flush=True)
            except Exception as exc:
                counts[f"exception_{type(exc).__name__}"] += 1
        grand.update(counts)
        print(f"RESULT {label} tested={len(sample)} {dict(counts)}", flush=True)
    print(f"TOTAL tested={sum(v for k,v in grand.items() if k != 'invalid_dns')} {dict(grand)}", flush=True)
    print("LIVE_PROXY_DIAGNOSTIC_FINISH", flush=True)


if __name__ == "__main__":
    main()
