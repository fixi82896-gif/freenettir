"""Actual MTProto reachability checks. Never assume a syntactically valid URL works.

This module does not contact Telegram Bot API and does not publish anything.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import socket
import time
from urllib.parse import parse_qs, urlsplit

from mtproxy_checker import CheckOptions, check_proxy

from proxy_utils import normalize_proxy_link

OPTIONS = CheckOptions(connect_timeout=2.5, response_timeout=2.5)
CHECK_CACHE_SECONDS = 300
CHECK_LIMIT = 120
MAX_WORKERS = 8


def is_public_mtproto(url):
    """Only test Telegram MTProto URLs aimed at public global IPs."""
    normalized = normalize_proxy_link(url)
    if not normalized or not normalized.startswith("https://t.me/proxy?"):
        return False
    parsed = urlsplit(normalized)
    host = parse_qs(parsed.query).get("server", [""])[0]
    try:
        resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return bool(resolved) and all(
            ipaddress.ip_address(item[4][0]).is_global
            for item in resolved
        )
    except (OSError, ValueError):
        return False


def is_live_mtproto(url):
    """True only after Telegram MTProto handshake and a validated resPQ response."""
    try:
        if not is_public_mtproto(url):
            return False
        return bool(check_proxy(url, OPTIONS).ok)
    except Exception:
        return False


def verify_mtproto_pool(candidates, max_checks=CHECK_LIMIT, workers=MAX_WORKERS,
                        verifier=None):
    """Check each unique MTProto URL; keep successes in original source order.

    No raw URLs or proxy secrets are logged.
    """
    validator = verifier or is_live_mtproto
    unique = []
    seen = set()
    for raw in candidates:
        url = normalize_proxy_link(raw)
        if url and url.startswith("https://t.me/proxy?") and url not in seen:
            seen.add(url)
            unique.append(url)
        if len(unique) >= max_checks:
            break

    if not unique:
        print("🔐 آزمون واقعی MTProto: هیچ لینک قابل آزمایشی موجود نیست.", flush=True)
        return []
    outcomes = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(unique))) as executor:
        futures = {executor.submit(validator, url): url for url in unique}
        for future in as_completed(futures):
            url = futures[future]
            try:
                outcomes[url] = bool(future.result())
            except Exception:
                outcomes[url] = False

    passed = [url for url in unique if outcomes.get(url)]
    print(f"🔐 آزمون واقعی MTProto: {len(passed)} از {len(unique)} اتصال تأیید شد. "
          "پروکسی SOCKS5 بدون تست عبور از تلگرام منتشر نمی‌شود.", flush=True)
    return passed


def verified_buttons_for_post(preferred, pool, checked_at, max_buttons=2,
                              max_checks=8, now=None, verifier=None):
    """Recheck older results before posting, replacing failed links when possible."""
    validator = verifier or is_live_mtproto
    if now is None:
        now = time.time()
    order, seen = [], set()
    for raw in list(preferred) + list(pool):
        url = normalize_proxy_link(raw)
        if url and url.startswith("https://t.me/proxy?") and url not in seen:
            order.append(url)
            seen.add(url)

    picked = []
    checks = 0
    for url in order:
        if len(picked) >= max_buttons:
            break
        stamp = checked_at.get(url, 0)
        if stamp and 0 <= now - stamp <= CHECK_CACHE_SECONDS:
            picked.append(url)
            continue
        if checks >= max_checks:
            break
        checks += 1
        try:
            good = bool(validator(url))
        except Exception:
            good = False
        if good:
            checked_at[url] = now
            picked.append(url)
        else:
            checked_at.pop(url, None)
    return picked
