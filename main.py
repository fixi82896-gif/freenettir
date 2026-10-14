import os
import sys
import time
import json
import re
import html
import random
import base64
import requests
import hashlib
import traceback
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from collections import Counter
from proxy_utils import (extract_proxy_links, normalize_proxy_link,
                         refresh_proxy_cache, plan_proxy_buttons)
from proxy_health import verify_mtproto_pool, verified_buttons_for_post

# ─── تنظیمات محیطی ───────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
RAW_CHANNELS = os.environ.get("TELEGRAM_CHANNEL", "")
CHANNELS = [c.strip() for c in RAW_CHANNELS.split(",") if c.strip()]
ADMIN_ID = os.environ.get("TELEGRAM_ADMIN_ID")

DEFAULT_CHANNEL_URL = "https://t.me/freenettir"
DEFAULT_SHARE_TEXT = quote("🚀 آخرین سرورها و پروکسی‌های پرسرعت رایگان را در کانال ما دنبال کنید:")
DEFAULT_SUPPORT_URL = f"https://t.me/share/url?url={DEFAULT_CHANNEL_URL}&text={DEFAULT_SHARE_TEXT}"
DEFAULT_AD_TEXT = "🏛️ اشتراک‌گذاری و حمایت از کانال"

GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

HISTORY_FILE = "sent_configs_history.json"
IP_CACHE = {}

HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})


def get_tehran_now():
    tehran_tz = timezone(timedelta(hours=3, minutes=30))
    return datetime.now(tehran_tz)


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if (gm > 2 or (gm == 2 and gd > 28)) else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def get_md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def normalize_source_url(raw_input):
    raw_input = raw_input.strip()
    if "t.me/" in raw_input or raw_input.startswith("@") or not raw_input.startswith("http"):
        clean_name = raw_input.replace("https://t.me/s/", "").replace("https://t.me/", "").replace("@", "").strip("/")
        return f"https://t.me/s/{clean_name}"
    return raw_input


def update_vmess_remark(vmess_cfg, new_remark):
    try:
        raw = vmess_cfg.replace("vmess://", "").strip().split("#")[0]
        raw = raw.replace("-", "+").replace("_", "/")
        raw += "=" * (-len(raw) % 4)

        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
        json_data = json.loads(decoded)

        if isinstance(json_data, dict):
            json_data["ps"] = new_remark
            new_json_str = json.dumps(json_data, ensure_ascii=False)
            new_b64 = base64.b64encode(new_json_str.encode("utf-8")).decode("utf-8")
            return f"vmess://{new_b64}"
    except Exception:
        pass

    clean_base = vmess_cfg.split("#")[0]
    return f"{clean_base}#{new_remark}"


def extract_configs_from_text(text):
    results = []
    raw_text = text

    if not re.search(r"(?:vless|vmess|trojan|ss)://", text):
        try:
            decoded_text = base64.b64decode(text.strip()).decode("utf-8", errors="ignore")
            raw_text = decoded_text
        except Exception:
            pass

    lines = raw_text.splitlines()
    for line in lines:
        match = re.search(r"((?:vless|vmess|trojan|ss)://[^\s\"\'>]+)", line)
        if match:
            full_cfg = match.group(1)
            clean_cfg = full_cfg.split("#")[0]

            ping_match = re.search(r"ping[:\s]*([\d\.]+\s*ms)", line, re.IGNORECASE)
            ping_val = ping_match.group(1).strip() if ping_match else None

            results.append((clean_cfg, ping_val))

    return results


def extract_host_port_from_config(config_str):
    try:
        if config_str.startswith("vmess://"):
            b64_data = config_str.replace("vmess://", "").strip().split("#")[0]
            b64_data = b64_data.replace("-", "+").replace("_", "/")
            b64_data += "=" * (-len(b64_data) % 4)
            decoded = base64.b64decode(b64_data).decode("utf-8", errors="ignore")
            json_data = json.loads(decoded)
            host = json_data.get("add") or json_data.get("host")
            port = json_data.get("port")
            if host and port:
                return f"{host}:{port}"
            return host
        elif "@" in config_str:
            parts = config_str.split("@")
            host_port = parts[1].split("#")[0].split("?")[0].split("/")[0]
            return host_port
    except Exception:
        pass
    return None


def get_country_info(config_str):
    try:
        host_port = extract_host_port_from_config(config_str)
        if not host_port:
            return "Unknown", "🌍"

        host = host_port.split(":")[0]

        if host in IP_CACHE:
            return IP_CACHE[host]

        time.sleep(1.4)

        res = HTTP_SESSION.get(
            f"http://ip-api.com/json/{host}?fields=status,country,countryCode",
            timeout=5,
        ).json()

        if res.get("status") == "success":
            country = res.get("country", "Unknown")
            cc = res.get("countryCode", "")
            flag = "".join(chr(127397 + ord(c)) for c in cc.upper()) if cc else "🌍"
            IP_CACHE[host] = (country, flag)
            return country, flag
    except Exception:
        pass
    return "Unknown", "🌍"


def send_telegram_with_retry(url, data=None, files=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            res = HTTP_SESSION.post(url, data=data, files=files, timeout=15)
            if res.status_code == 429:
                retry_after = res.json().get("parameters", {}).get("retry_after", 10)
                print(f"⚠️ محدودیت تلگرام! {retry_after} ثانیه صبر می‌کنیم...")
                time.sleep(retry_after)
                continue
            return res
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(3)
    return None


def send_channel_maintenance_notice():
    if not TOKEN or not CHANNELS:
        return

    notice_text = (
        "اعضای محترم کانال ،\n"
        "با عرض پوزش ربات ارسال کننده جهت بازبینی و اصلاح غیر فعال شده ، "
        "از تحمل و صبوری شما بسیار سپاسگزارم \n"
        "با تشکر ؛ مدیریت کانال"
    )

    for channel in CHANNELS:
        try:
            HTTP_SESSION.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={"chat_id": channel, "text": notice_text},
                timeout=10,
            )
        except Exception as e:
            print(f"⚠️ خطا در ارسال پیام اطلاع‌رسانی: {e}")


def send_crash_telegram_admin(error_msg, full_traceback):
    if not TOKEN or not ADMIN_ID:
        return

    now_tehran = get_tehran_now()
    jy, jm, jd = gregorian_to_jalali(now_tehran.year, now_tehran.month, now_tehran.day)
    time_str = now_tehran.strftime("%H:%M:%S")
    date_str = f"{jy}/{jm:02d}/{jd:02d}"

    tb_truncated = full_traceback[-2500:] if len(full_traceback) > 2500 else full_traceback

    alert_text = (
        f"🚨 <b>هشدار کرش ربات تلگرام (مخصوص ادمین)</b>\n\n"
        f"📅 <b>زمان وقوع:</b> {date_str} | {time_str} 🇮🇷\n\n"
        f"❌ <b>علت خطا:</b>\n<code>{html.escape(str(error_msg))}</code>\n\n"
        f"🔍 <b>جزئیات فنی (Traceback):</b>\n<pre>{html.escape(tb_truncated)}</pre>"
    )

    try:
        HTTP_SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": ADMIN_ID, "text": alert_text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"⚠️ خطا در گزارش به ادمین: {e}")


def record_source_status(src, is_success, history):
    failures = history.setdefault("source_failures", {})
    today_str = get_tehran_now().strftime("%Y-%m-%d")

    if is_success:
        if src in failures:
            del failures[src]
        return

    data = failures.get(src, {"count": 0, "last_date": ""})
    if data["last_date"] != today_str:
        data["count"] += 1
        data["last_date"] = today_str
        failures[src] = data

    if data["count"] >= 3:
        removed = False
        if src in history.get("custom_config_sources", []):
            history["custom_config_sources"].remove(src)
            removed = True
        if src in history.get("custom_proxy_sources", []):
            history["custom_proxy_sources"].remove(src)
            removed = True

        if removed:
            del failures[src]
            alert_msg = (
                f"🚨 <b>حذف خودکار منبع از دست‌رفته</b>\n\n"
                f"منبع زیر به دلیل <b>۳ روز متوالی خطا</b> به‌صورت خودکار از لیست منابع سفارشی حذف شد:\n\n"
                f"<code>{html.escape(src)}</code>"
            )
            try:
                HTTP_SESSION.post(
                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    data={"chat_id": ADMIN_ID, "text": alert_msg, "parse_mode": "HTML"},
                    timeout=5,
                )
            except Exception as e:
                print(f"⚠️ خطا در ارسال گزارش حذف منبع به ادمین: {e}")


# ─── پنل ادمین و مدیریت دکمه تبلیغات ───────────────────────────────
def send_admin_keyboard(text="🛠 <b>پنل مدیریت ربات</b>"):
    if not TOKEN or not ADMIN_ID:
        return

    reply_keyboard = {
        "keyboard": [
            [{"text": "➕ افزودن منبع کانفیگ"}, {"text": "➕ افزودن منبع پروکسی"}],
            [{"text": "⚡️ افزودن مستقیم کانفیگ"}, {"text": "🚀 افزودن مستقیم پروکسی"}],
            [{"text": "📋 لیست و حذف منابع"}, {"text": "⚙️ مدیریت دکمه تبلیغات"}],
            [{"text": "🔄 بروزرسانی پنل"}]
        ],
        "resize_keyboard": True
    }

    try:
        HTTP_SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": ADMIN_ID,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(reply_keyboard),
            },
            timeout=5,
        )
    except Exception as e:
        print(f"⚠️ خطا در ارسال کیبورد ادمین: {e}")


def send_ad_management_menu(history, text=None):
    if not TOKEN or not ADMIN_ID:
        return

    ad_text = history.get("ad_button_text", DEFAULT_AD_TEXT)
    ad_url = history.get("ad_button_url", DEFAULT_SUPPORT_URL)

    if not text:
        text = (
            f"⚙️ <b>تنظیمات فعلی دکمه تبلیغات / حمایت:</b>\n\n"
            f"🏷 <b>متن دکمه:</b> <code>{html.escape(ad_text)}</code>\n"
            f"🔗 <b>لینک/محتوا:</b> <code>{html.escape(ad_url)}</code>"
        )

    inline_keyboard = [
        [{"text": "✏️ تغییر متن و لینک تبلیغات", "callback_data": "change_ad_text_url"}],
        [{"text": "🔄 بازنشانی به حالت پیش‌فرض (حمایت از کانال)", "callback_data": "reset_ad_button"}]
    ]

    try:
        HTTP_SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": ADMIN_ID,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": json.dumps({"inline_keyboard": inline_keyboard})
            },
            timeout=5,
        )
    except Exception as e:
        print(f"⚠️ خطا در ارسال منوی تبلیغات: {e}")


def source_menu_token(source):
    """Stable identifier: stale keyboards cannot delete a different list item."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def build_sources_deletion_menu(history, expanded=0, notice=None):
    """Build independent, initially collapsed configuration/proxy panels."""
    expanded = int(expanded) & 3
    cfg_sources = history.get("custom_config_sources", [])
    prx_sources = history.get("custom_proxy_sources", [])
    text = (
        "📋 <b>لیست و حذف منابع</b>\\n"
        "برای نمایش منابع، بخش موردنظر را باز کنید.\\n"
        "برای بستن همان بخش دوباره روی عنوان آن بزنید."
    )
    if notice:
        text += "\\n\\n" + html.escape(notice)

    keyboard = []
    for key, bit, title, sources, kind in (
        ("cfg", 1, "📋 منابع کانفیگ", cfg_sources, "cfg"),
        ("prx", 2, "📦 منابع پروکسی", prx_sources, "prx"),
    ):
        opened = bool(expanded & bit)
        arrow = "🔽" if opened else "▶️"
        keyboard.append([{
            "text": f"{arrow} {title} ({len(sources)})",
            "callback_data": f"src_menu_{expanded ^ bit}",
        }])
        if opened:
            if not sources:
                keyboard.append([{
                    "text": "— هنوز منبعی ثبت نشده است —",
                    "callback_data": "ignore",
                }])
            else:
                for source in sources:
                    label = source.replace("https://t.me/s/", "@")
                    if len(label) > 55:
                        label = label[:52] + "…"
                    keyboard.append([{
                        "text": f"❌ حذف {label}",
                        "callback_data": f"src_del_{kind}_{expanded}_{source_menu_token(source)}",
                    }])
    return text, {"inline_keyboard": keyboard}


def delete_source_by_token(history, kind, token):
    """Delete only when exactly one current source matches the callback token."""
    field = {"cfg": "custom_config_sources", "prx": "custom_proxy_sources"}.get(kind)
    if not field or len(token) != 20 or not re.fullmatch(r"[a-f0-9]{20}", token):
        return None
    sources = history.get(field, [])
    matches = [i for i, source in enumerate(sources) if source_menu_token(source) == token]
    if len(matches) != 1:
        return None
    return sources.pop(matches[0])


def send_sources_deletion_menu(history, expanded=0, message_id=None, notice=None):
    """Open or edit the SAME Telegram menu message; never duplicate on toggle."""
    if not TOKEN or not ADMIN_ID:
        return False

    text, markup = build_sources_deletion_menu(history, expanded=expanded, notice=notice)
    editing = message_id is not None
    endpoint = "editMessageText" if editing else "sendMessage"
    payload = {
        "chat_id": ADMIN_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(markup, ensure_ascii=False),
    }
    if editing:
        payload["message_id"] = message_id

    try:
        response = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/{endpoint}",
            data=payload,
            timeout=5,
        )
        if response.status_code != 200 or not response.json().get("ok"):
            description = response.json().get("description", "")
            print(f"⚠️ خطا در نمایش منوی منابع ({endpoint}): {description}")
            return False
        return True
    except Exception as exc:
        print(f"⚠️ خطا در نمایش منوی منابع: {exc}")
        return False


def answer_callback(cb_id, text=None):
    try:
        HTTP_SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
            data={"callback_query_id": cb_id, "text": text or ""},
            timeout=3,
        )
    except Exception:
        pass


def process_admin_updates(history):
    if not TOKEN or not ADMIN_ID:
        return

    try:
        offset = history.get("last_update_id", 0) + 1
        res = HTTP_SESSION.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 1, "limit": 20},
            timeout=3,
        ).json()

        if not res.get("ok"):
            return

        for update in res.get("result", []):
            history["last_update_id"] = update["update_id"]

            if "callback_query" in update:
                cb = update["callback_query"]
                if str(cb["from"]["id"]) == str(ADMIN_ID):
                    cb_id = cb["id"]
                    data = cb["data"]

                    if data == "ignore":
                        answer_callback(cb_id)
                        continue

                    elif data.startswith("src_menu_"):
                        mask_text = data.removeprefix("src_menu_")
                        if mask_text in ("0", "1", "2", "3"):
                            answer_callback(cb_id)
                            send_sources_deletion_menu(
                                history, expanded=int(mask_text),
                                message_id=cb.get("message", {}).get("message_id"),
                            )
                        else:
                            answer_callback(cb_id, "دکمه نامعتبر است؛ منو را دوباره باز کنید.")

                    elif data.startswith("src_del_"):
                        parts = data.split("_", 4)
                        if len(parts) == 5 and parts[2] in ("cfg", "prx") and parts[3] in ("0", "1", "2", "3"):
                            kind, expanded, token = parts[2], int(parts[3]), parts[4]
                            removed = delete_source_by_token(history, kind, token)
                            if removed is None:
                                answer_callback(cb_id, "منبع پیدا نشد؛ شاید فهرست قبلاً تغییر کرده است.")
                                notice = "⚠️ این منبع قبلاً حذف شده یا فهرست تغییر کرده است."
                            else:
                                answer_callback(cb_id, "منبع حذف شد.")
                                notice = f"✅ منبع {removed} حذف شد."
                            send_sources_deletion_menu(
                                history, expanded=expanded,
                                message_id=cb.get("message", {}).get("message_id"),
                                notice=notice,
                            )
                        else:
                            answer_callback(cb_id, "درخواست حذف معتبر نیست.")

                    elif data.startswith(("del_cfg_", "del_prx_")):
                        # Legacy index-based buttons may refer to a different source now.
                        # Fail closed instead of accidentally deleting an unrelated source.
                        answer_callback(cb_id, "این منو قدیمی است؛ فهرست تازه را باز کنید.")
                        send_sources_deletion_menu(
                            history, message_id=cb.get("message", {}).get("message_id"),
                        )

                    elif data == "change_ad_text_url":
                        history["bot_state"] = "WAITING_FOR_AD_TEXT"
                        answer_callback(cb_id)
                        send_admin_keyboard("🏷 لطفاً **متن جدید دکمه تبلیغات** را ارسال کنید:")

                    elif data == "reset_ad_button":
                        history["ad_button_text"] = DEFAULT_AD_TEXT
                        history["ad_button_url"] = DEFAULT_SUPPORT_URL
                        answer_callback(cb_id, "دکمه تبلیغات با موفقیت به حالت پیش‌فرض بازنشانی شد.")
                        send_ad_management_menu(history, "✅ <b>دکمه تبلیغات با موفقیت به حالت حمایت از کانال بازنشانی شد.</b>")

            elif "message" in update:
                msg = update["message"]
                if str(msg["from"]["id"]) == str(ADMIN_ID) and "text" in msg:
                    text = msg["text"].strip()
                    state = history.get("bot_state")

                    if text in ["/start", "/panel", "🔄 بروزرسانی پنل"]:
                        history["bot_state"] = None
                        send_admin_keyboard("🔄 پنل مدیریت بروزرسانی شد.")

                    elif text == "➕ افزودن منبع کانفیگ":
                        history["bot_state"] = "WAITING_FOR_CONFIG_SRC"
                        send_admin_keyboard("📥 لطفاً آیدی یا لینک کانال/منبع <b>کانفیگ</b> را ارسال کنید:\n(مثال: <code>@v2ray_configs_pool</code>)")

                    elif text == "➕ افزودن منبع پروکسی":
                        history["bot_state"] = "WAITING_FOR_PROXY_SRC"
                        send_admin_keyboard("📥 لطفاً آیدی یا لینک کانال/منبع <b>پروکسی</b> را ارسال کنید:\n(مثال: <code>@ProxyMTProto</code>)")

                    elif text == "⚡️ افزودن مستقیم کانفیگ":
                        history["bot_state"] = "WAITING_FOR_MANUAL_CONFIG"
                        send_admin_keyboard("⚡️ لطفاً کانفیگ یا متن حاوی کدهای V2Ray را ارسال کنید:")

                    elif text == "🚀 افزودن مستقیم پروکسی":
                        history["bot_state"] = "WAITING_FOR_MANUAL_PROXY"
                        send_admin_keyboard("🚀 لطفاً لینک مستقیم پروکسی تلگرام را ارسال کنید:")

                    elif text == "📋 لیست و حذف منابع":
                        history["bot_state"] = None
                        send_sources_deletion_menu(history)

                    elif text == "⚙️ مدیریت دکمه تبلیغات":
                        history["bot_state"] = None
                        send_ad_management_menu(history)

                    elif state == "WAITING_FOR_CONFIG_SRC":
                        normalized = normalize_source_url(text)
                        if normalized not in history["custom_config_sources"]:
                            history["custom_config_sources"].append(normalized)
                            send_admin_keyboard(f"✅ منبع کانفیگ جدید اضافه شد:\n<code>{normalized}</code>")
                        else:
                            send_admin_keyboard("⚠️ این منبع قبلاً ثبت شده بود.")
                        history["bot_state"] = None

                    elif state == "WAITING_FOR_PROXY_SRC":
                        normalized = normalize_source_url(text)
                        if normalized not in history["custom_proxy_sources"]:
                            history["custom_proxy_sources"].append(normalized)
                            send_admin_keyboard(f"✅ منبع پروکسی جدید اضافه شد:\n<code>{normalized}</code>")
                        else:
                            send_admin_keyboard("⚠️ این منبع قبلاً ثبت شده بود.")
                        history["bot_state"] = None

                    elif state == "WAITING_FOR_MANUAL_CONFIG":
                        found_cfgs = extract_configs_from_text(text)
                        if found_cfgs:
                            history["leftover_configs"] = found_cfgs + history.get("leftover_configs", [])
                            send_admin_keyboard(f"✅ تعداد <b>{len(found_cfgs)}</b> کانفیگ دریافت شد و در اولویت ارسال قرار گرفت.")
                        else:
                            send_admin_keyboard("❌ هیچ کد کانفیگ معتبری در متن یافت نشد.")
                        history["bot_state"] = None

                    elif state == "WAITING_FOR_MANUAL_PROXY":
                        found_pxs = re.findall(r'(https://t\.me/proxy\?[^\s#"\'>]+)', text)
                        if found_pxs:
                            history["leftover_proxies"] = found_pxs + history.get("leftover_proxies", [])
                            send_admin_keyboard(f"✅ تعداد <b>{len(found_pxs)}</b> پروکسی دریافت شد و در اولویت ارسال قرار گرفت.")
                        else:
                            send_admin_keyboard("❌ هیچ لینک پروکسی معتبری در متن یافت نشد.")
                        history["bot_state"] = None

                    elif state == "WAITING_FOR_AD_TEXT":
                        history["temp_ad_text"] = text
                        history["bot_state"] = "WAITING_FOR_AD_URL"
                        send_admin_keyboard("🔗 لطفاً **لینک یا آیدی اختصاصی** دکمه تبلیغات را ارسال کنید:\n(مثال: <code>https://t.me/my_channel</code> یا <code>@my_channel</code>)")

                    elif state == "WAITING_FOR_AD_URL":
                        target_url = text
                        if target_url.startswith("@"):
                            target_url = f"https://t.me/{target_url.replace('@', '')}"
                        elif not target_url.startswith("http"):
                            target_url = f"https://t.me/{target_url}"

                        history["ad_button_text"] = history.get("temp_ad_text", DEFAULT_AD_TEXT)
                        history["ad_button_url"] = target_url
                        history["bot_state"] = None

                        send_admin_keyboard("✅ دکمه تبلیغات جدید با موفقیت تنظیم و فعال شد.")
                        send_ad_management_menu(history)

    except Exception as e:
        print(f"⚠️ خطا در بررسی آپدیت‌های ادمین: {e}")


def smart_sleep(seconds, history):
    start_t = time.time()
    while time.time() - start_t < seconds:
        process_admin_updates(history)
        time.sleep(2)


# ─── لایه ذخیره‌سازی داده‌ها ─────────────────────────────────────────
def load_history():
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
                print("✅ تاریخچه با موفقیت بارگیری شد.")
        except Exception as e:
            print(f"⚠️ خطا در خواندن تاریخچه: {e}")

    history.setdefault("last_serial", 0)
    history.setdefault("sent_hashes", [])
    history.setdefault("sent_ip_ports", [])
    history.setdefault("leftover_configs", [])
    history.setdefault("leftover_proxies", [])
    history.setdefault("recent_proxy_pool", [])
    history.setdefault("proxy_rotation_offset", 0)
    history.setdefault("sent_proxies_hashes", [])
    history.setdefault("custom_config_sources", [])
    history.setdefault("custom_proxy_sources", [])
    history.setdefault("source_failures", {})
    history.setdefault("ad_button_text", DEFAULT_AD_TEXT)
    history.setdefault("ad_button_url", DEFAULT_SUPPORT_URL)
    history.setdefault("last_update_id", 0)
    history.setdefault("bot_state", None)
    return history


def save_history(history):
    history["sent_hashes"] = history["sent_hashes"][-5000:]
    history["sent_ip_ports"] = history["sent_ip_ports"][-3000:]
    history["sent_proxies_hashes"] = history["sent_proxies_hashes"][-5000:]
    history["leftover_configs"] = history["leftover_configs"][-300:]
    history["leftover_proxies"] = history["leftover_proxies"][-300:]
    history["recent_proxy_pool"] = history.get("recent_proxy_pool", [])[:180]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ خطا در ذخیره محلی تاریخچه: {e}")

    if GITHUB_REPO and GITHUB_TOKEN:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{HISTORY_FILE}"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            }

            res = HTTP_SESSION.get(url, headers=headers, timeout=5)
            sha = res.json().get("sha") if res.status_code == 200 else None

            json_str = json.dumps(history, ensure_ascii=False, indent=2)
            content_b64 = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

            payload = {
                "message": "🤖 بروزرسانی خودکار تاریخچه و منابع [Bot]",
                "content": content_b64,
            }
            if sha:
                payload["sha"] = sha

            put_res = HTTP_SESSION.put(url, headers=headers, json=payload, timeout=10)
            if put_res.status_code in [200, 201]:
                print("✅ فایل تاریخچه در ریپازیتوری گیت‌هاب بروزرسانی شد.")
            else:
                print(f"⚠️ خطای API گیت‌هاب: کد {put_res.status_code}")
        except Exception as e:
            print(f"⚠️ خطا در ارتباط با API گیت‌هاب: {e}")


# ─── جمع‌آوری داده‌ها ───────────────────────────────────────────────
def collect_configs(history, sent_hashes_set, sent_ip_ports_set):
    print("\n🔍 در حال جمع‌آوری کانفیگ‌ها...")
    valid_configs = []

    for item in history.get("leftover_configs", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            valid_configs.append((item[0], item[1]))
        elif isinstance(item, str):
            valid_configs.append((item, None))

    seen_cfgs = set(c[0] for c in valid_configs)

    # Source addresses are managed exclusively by the Telegram admin panel.
    # Keep the original ordering; do not inject fallback or built-in feeds.
    all_config_sources = list(dict.fromkeys(history.get("custom_config_sources", [])))
    print(f"📋 منابع کانفیگ ثبت‌شده در پنل: {len(all_config_sources)}")

    for src in all_config_sources:
        try:
            r = HTTP_SESSION.get(src, timeout=10)
            if r.status_code == 200:
                record_source_status(src, True, history)
                found = extract_configs_from_text(r.text)
                for cfg, ping in found:
                    cfg_hash = get_md5(cfg)
                    ip_port = extract_host_port_from_config(cfg)

                    if cfg_hash not in sent_hashes_set and cfg not in seen_cfgs:
                        if not ip_port or ip_port not in sent_ip_ports_set:
                            valid_configs.append((cfg, ping))
                            seen_cfgs.add(cfg)
                            if ip_port:
                                sent_ip_ports_set.add(ip_port)

                    if len(valid_configs) >= 200:
                        break
            else:
                record_source_status(src, False, history)
        except Exception as e:
            record_source_status(src, False, history)
            print(f"⚠️ خطا در خواندن منبع {src}: {e}")

        if len(valid_configs) >= 200:
            break

    return valid_configs


def collect_proxies(history, sent_proxies_set):
    print("📦 در حال جمع‌آوری پروکسی‌ها...")
    # Every proxy source is selected in the Telegram admin panel; no built-ins.
    all_proxy_sources = list(dict.fromkeys(history.get("custom_proxy_sources", [])))
    print(f"📋 منابع پروکسی ثبت‌شده در پنل: {len(all_proxy_sources)}")

    observed_proxies = []
    observed = set()
    max_collected = 180
    per_source_limit = max(10, min(35, max_collected // max(1, len(all_proxy_sources))))

    for src in all_proxy_sources:
        try:
            response = HTTP_SESSION.get(src, timeout=8)
            if response.status_code != 200:
                record_source_status(src, False, history)
                print(f"⚠️ منبع پروکسی {src}: HTTP {response.status_code}")
                continue
            record_source_status(src, True, history)
            candidates = extract_proxy_links(response.text)
            accepted = 0
            for proxy in candidates:
                if proxy in observed:
                    continue
                observed_proxies.append(proxy)
                observed.add(proxy)
                accepted += 1
                if accepted >= per_source_limit or len(observed_proxies) >= max_collected:
                    break
            print(f"🔗 منبع پروکسی {src}: {accepted} لینک معتبر ساختاری (نه لزوماً فعال)")
        except Exception as exc:
            record_source_status(src, False, history)
            print(f"⚠️ خطا در خواندن منبع پروکسی {src}: {exc}")
        if len(observed_proxies) >= max_collected:
            break

    # Recently observed links are kept for a bounded time to survive brief outages.
    # A previous send is NOT proof a link is dead; historical hashes are only for priority.
    archive = refresh_proxy_cache(
        history.get("recent_proxy_pool", []), observed_proxies, int(time.time())
    )
    candidates = [entry["url"] for entry in archive]

    # Historical links must be revalidated. Never trust previous sends or cache age.
    for raw_proxy in history.get("leftover_proxies", []):
        proxy = normalize_proxy_link(raw_proxy)
        if proxy and proxy not in candidates and len(candidates) < 180:
            candidates.append(proxy)

    # Only a real MTProto handshake and Telegram resPQ confirmation can enter the
    # publishing pool. Public SOCKS5 endpoints remain sources but are excluded
    # until a SOCKS-to-Telegram connectivity verifier is implemented.
    verified_proxies = verify_mtproto_pool(candidates)
    now_epoch = int(time.time())
    history["recent_proxy_pool"] = [
        {"url": link, "seen_at": now_epoch} for link in verified_proxies
    ]
    never_sent = [p for p in verified_proxies if get_md5(p) not in sent_proxies_set]
    previously_sent = [p for p in verified_proxies if get_md5(p) in sent_proxies_set]
    valid_proxies = never_sent + previously_sent
    print(
        f"📊 پروکسی‌های تأییدشده واقعی: {len(valid_proxies)}"
        f" | استفاده‌نشده: {len(never_sent)}"
        f" | قابل تکرار پس از تأیید مجدد: {len(previously_sent)}"
    )
    return valid_proxies


def get_random_logo():
    logos = [f for f in os.listdir(".") if f.startswith("logo") and f.endswith(".jpg")]
    return random.choice(logos) if logos else None


# ─── نقطه ورود اصلی ────────────────────────────────────────────────
def main():
    if not TOKEN or not CHANNELS:
        raise ValueError("سکرت‌های TELEGRAM_BOT_TOKEN یا TELEGRAM_CHANNEL یافت نشدند!")

    history = load_history()

    send_admin_keyboard("🚀 <b>ربات فعال شد!</b>\nاز صفحه کلید زیر جهت مدیریت منابع استفاده کنید:")

    process_admin_updates(history)

    sent_hashes_set = set(history.get("sent_hashes", []))
    sent_ip_ports_set = set(history.get("sent_ip_ports", []))
    sent_proxies_set = set(history.get("sent_proxies_hashes", []))

    print(f"\n==========================================")
    print(f"=== 🛠️ شروع چرخه ۶۰ دقیقه‌ای ارسال ===")
    print(f"📌 آخرین شماره سریال ثبت‌شده: {history.get('last_serial', 0)}")
    print(f"==========================================")

    valid_configs = collect_configs(history, sent_hashes_set, sent_ip_ports_set)
    valid_proxies = collect_proxies(history, sent_proxies_set)

    print(f"📊 کانفیگ‌های جدید آماده: {len(valid_configs)} | پروکسی‌های جدید: {len(valid_proxies)}")

    if len(valid_configs) < 30:
        print(f"⚠️ کانفیگ کافی ({len(valid_configs)} عدد) برای شروع چرخه وجود ندارد. خروج بدون ارسال.")
        history["leftover_configs"] = valid_configs
        history["leftover_proxies"] = valid_proxies
        save_history(history)
        return

    if not valid_proxies:
        # Do not publish posts without the promised proxy buttons.
        # Keep unsent configs for the next cycle; do not change serials or sent hashes.
        print("🚨 هیچ لینک پروکسی معتبری از منابع یا حافظه موقت موجود نیست؛ ارسال پست‌های بدون پروکسی متوقف شد.")
        history["leftover_configs"] = valid_configs[:300]
        history["leftover_proxies"] = []
        save_history(history)
        return

    cycle_configs = valid_configs[:100]
    history["leftover_configs"] = valid_configs[100:]

    config_batches = [cycle_configs[i : i + 3] for i in range(0, len(cycle_configs), 3)]
    proxy_batches, next_offset = plan_proxy_buttons(
        valid_proxies, len(config_batches), history.get("proxy_rotation_offset", 0)
    )
    verified_at = {url: time.time() for url in valid_proxies}
    history["proxy_rotation_offset"] = next_offset
    history["leftover_proxies"] = valid_proxies[min(len(valid_proxies), len(config_batches) * 2):]
    reused_button_count = sum(len(batch) for batch in proxy_batches) - min(
        len(valid_proxies), len(config_batches) * 2
    )
    print(
        f"🔘 دکمه‌های اتصال: {sum(len(batch) for batch in proxy_batches)} برای"
        f" {len(config_batches)} پست؛ تخصیص تکراری بین پست‌ها: {max(0, reused_button_count)}"
    )

    sent_all_configs = []
    country_flags = {}
    country_counter = Counter()

    delay_between_posts = int(3600 / len(config_batches)) if len(config_batches) > 1 else 105

    print(f"\n🚀 شروع ارسال تدریجی {len(config_batches)} پارت (فاصله: {delay_between_posts} ثانیه)...")

    for b_idx, batch_c in enumerate(config_batches):
        loop_start_time = time.time()

        planned_proxies = list(proxy_batches[b_idx]) if b_idx < len(proxy_batches) else []
        # A proxy can go down during this one-hour cycle. Refresh aged validation.
        batch_p = verified_buttons_for_post(
            planned_proxies, valid_proxies, verified_at,
        )
        if not batch_p:
            print("🚨 توقف امن: هیچ پروکسی با اتصال واقعی تلگرام برای این پست تأیید نشد.")
            # Save the unposted configurations, preserving serials and sent history.
            history["leftover_configs"] = (
                cycle_configs[b_idx * 3:] + history.get("leftover_configs", [])
            )[:300]
            history["sent_hashes"] = list(sent_hashes_set)
            history["sent_ip_ports"] = list(sent_ip_ports_set)
            history["sent_proxies_hashes"] = list(sent_proxies_set)
            save_history(history)
            return

        ad_text = history.get("ad_button_text", DEFAULT_AD_TEXT)
        ad_url = history.get("ad_button_url", DEFAULT_SUPPORT_URL)

        # Only real, distinct proxy URLs become proxy buttons; retain the ad button.
        proxy_buttons = [{"text": "🚀 اتصال به پروکسی", "url": p} for p in batch_p]
        keyboard_buttons = ([proxy_buttons] if proxy_buttons else []) + [
            [{"text": ad_text, "url": ad_url}],
        ]
        reply_markup = {"inline_keyboard": keyboard_buttons}

        post_text = ""
        labels = ["اول", "دوم", "سوم"]

        for idx, item in enumerate(batch_c):
            cfg, ping = item if isinstance(item, (tuple, list)) else (item, None)

            history["last_serial"] += 1
            serial_str = f"[{history['last_serial']:06d}]"
            country, flag = get_country_info(cfg)
            country_flags[country] = flag
            country_counter[country] += 1

            ping_str = f" | ⚡️ {ping}" if ping else ""
            remark = f"{serial_str} - {flag} {country}{ping_str} | @freenettir"

            if cfg.startswith("vmess://"):
                final_cfg = update_vmess_remark(cfg, remark)
            else:
                final_cfg = f"{cfg}#{remark}"

            sent_all_configs.append(final_cfg)

            ping_display = f" (⚡️ پینگ: <code>{ping}</code>)" if ping else ""
            post_text += f"<b>📌 سرور {labels[idx]} :</b>{ping_display}\n\n<code>{final_cfg}</code>\n\n"
            sent_hashes_set.add(get_md5(cfg))

        post_text += "<b>🌐 @freenettir  مخزن اصلی سرورها</b>\n\n🔹 #v2ray #vpn #proxy"
        logo = get_random_logo()

        delivered_to_any_channel = False
        for channel in CHANNELS:
            try:
                if logo and os.path.exists(logo):
                    with open(logo, "rb") as photo_file:
                        response = send_telegram_with_retry(
                            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                            data={
                                "chat_id": channel,
                                "caption": post_text,
                                "parse_mode": "HTML",
                                "reply_markup": json.dumps(reply_markup),
                            },
                            files={"photo": photo_file},
                        )
                else:
                    response = send_telegram_with_retry(
                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                        data={
                            "chat_id": channel,
                            "text": post_text,
                            "parse_mode": "HTML",
                            "reply_markup": json.dumps(reply_markup),
                        },
                    )
                if response is None or response.status_code != 200 or not response.json().get("ok"):
                    status = response.status_code if response is not None else "no response"
                    description = response.json().get("description", "") if response is not None else ""
                    print(f"❌ ارسال پارت {b_idx + 1} به کانال {channel} تأیید نشد (HTTP {status}: {description[:160]})")
                else:
                    delivered_to_any_channel = True
            except Exception as e:
                print(f"❌ خطا در ارسال پارت {b_idx + 1} به کانال {channel}: {e}")

        if delivered_to_any_channel:
            for proxy in batch_p:
                sent_proxies_set.add(get_md5(proxy))
            print(f"✅ پارت {b_idx + 1} از {len(config_batches)} ارسال شد. (سریال: {history['last_serial']})")
        else:
            # Preserve unsuccessful proxy buttons for another cycle.
            for proxy in batch_p:
                if proxy not in history["leftover_proxies"]:
                    history["leftover_proxies"].append(proxy)
            print(f"❌ پارت {b_idx + 1} از {len(config_batches)} به هیچ کانالی ارسال نشد.")

        elapsed = time.time() - loop_start_time
        actual_sleep = max(0, delay_between_posts - elapsed)

        if b_idx < len(config_batches) - 1:
            smart_sleep(actual_sleep, history)

    print("\n📝 پایان ارسال پست‌ها. ارسال فایل متنی سرورها...")
    for channel in CHANNELS:
        try:
            send_telegram_with_retry(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={"chat_id": channel, "text": "📝"},
            )
        except Exception:
            pass

    smart_sleep(2, history)

    support_markup = {
        "inline_keyboard": [[{"text": "🏛️ اشتراک‌گذاری و حمایت از کانال", "url": DEFAULT_SUPPORT_URL}]]
    }

    now_tehran = get_tehran_now()
    jy, jm, jd = gregorian_to_jalali(now_tehran.year, now_tehran.month, now_tehran.day)
    time_str = now_tehran.strftime("%H:%M")
    date_str = f"{jy}/{jm:02d}/{jd:02d}"

    config_file_name = f"@freenettir-{jy}-{jm:02d}-{jd:02d}-{now_tehran.hour:02d}-{now_tehran.minute:02d}.txt"

    with open(config_file_name, "w", encoding="utf-8") as f:
        f.write("\n\n".join(sent_all_configs))

    top_countries = country_counter.most_common(8)
    compact_items = [f"{country_flags.get(c, '🌍')} {c} ({cnt})" for c, cnt in top_countries]
    stats_lines = []
    for i in range(0, len(compact_items), 2):
        if i + 1 < len(compact_items):
            stats_lines.append(f"{compact_items[i]}  |  {compact_items[i+1]}")
        else:
            stats_lines.append(f"{compact_items[i]}")
    stats_text = "\n".join(stats_lines)

    total_sent_count = len(sent_all_configs)
    config_caption = (
        f"📦 <b>مجموعه {total_sent_count} سرور پرسرعت نهایی</b>\n"
        "──────────────────\n"
        f"📅 <b>تاریخ:</b> {date_str}  |  ⏰ <b>ساعت:</b> {time_str} 🇮🇷\n"
        "──────────────────\n\n"
        f"🌍 <b>لوکیشن‌های برتر:</b>\n"
        f"{stats_text}\n\n"
        "💡 <b>راهنما:</b> فایل را دانلود کرده و در برنامه (v2rayNG / NekoBox) از بخش Import File وارد کنید.\n\n"
        "🌐 <b>@freenettir | مرجع سرورهای رایگان</b>\n\n"
        "🔹 #v2ray #vpn #proxy"
    )

    try:
        if os.path.exists(config_file_name):
            for channel in CHANNELS:
                try:
                    with open(config_file_name, "rb") as doc_file:
                        res = send_telegram_with_retry(
                            f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                            data={
                                "chat_id": channel,
                                "caption": config_caption,
                                "parse_mode": "HTML",
                                "reply_markup": json.dumps(support_markup),
                            },
                            files={"document": (config_file_name, doc_file)},
                        )
                    if res and res.status_code == 200:
                        print(f"✅ فایل متنی به کانال {channel} ارسال شد.")
                except Exception as e:
                    print(f"⚠️ خطا در ارسال فایل به {channel}: {e}")
    finally:
        if os.path.exists(config_file_name):
            os.remove(config_file_name)

    history["sent_hashes"] = list(sent_hashes_set)
    history["sent_ip_ports"] = list(sent_ip_ports_set)
    history["sent_proxies_hashes"] = list(sent_proxies_set)
    save_history(history)

    print("\n✅ اجرای چرخه با موفقیت کامل شد.")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        tb = traceback.format_exc()
        print(f"💥 کرش کلی ربات: {err}")
        send_crash_telegram_admin(str(err), tb)
        send_channel_maintenance_notice()
        sys.exit(1)
