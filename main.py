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

# ─── تنظیمات محیطی ───────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
RAW_CHANNELS = os.environ.get("TELEGRAM_CHANNEL", "")
CHANNELS = [c.strip() for c in RAW_CHANNELS.split(",") if c.strip()]
ADMIN_ID = os.environ.get("TELEGRAM_ADMIN_ID")

AD_BUTTON_TEXT = os.environ.get("AD_BUTTON_TEXT", "🚀 اتصال به پروکسی پرسرعت")
AD_BUTTON_URL = os.environ.get("AD_BUTTON_URL", "https://t.me/freenettir")

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

        time.sleep(0.3)

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


# ─── پنل ادمین و مدیریت دکمه‌های تلگرام ─────────────────────────────
def send_admin_panel(text="🛠 <b>پنل مدیریت منابع و کانفیگ‌ها</b>"):
    if not TOKEN or not ADMIN_ID:
        return

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "➕ افزودن منبع کانفیگ", "callback_data": "add_config_src"},
                {"text": "➕ افزودن منبع پروکسی", "callback_data": "add_proxy_src"}
            ],
            [
                {"text": "⚡️ افزودن مستقیم کانفیگ", "callback_data": "add_manual_config"},
                {"text": "🚀 افزودن مستقیم پروکسی", "callback_data": "add_manual_proxy"}
            ],
            [
                {"text": "📋 لیست منابع سفارشی", "callback_data": "list_sources"},
                {"text": "🗑 پاکسازی منابع", "callback_data": "clear_sources"}
            ]
        ]
    }

    try:
        HTTP_SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": ADMIN_ID,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
            timeout=5,
        )
    except Exception as e:
        print(f"⚠️ خطا در ارسال پنل مدیریت: {e}")


def answer_callback(cb_id, text=None):
    """تایید کلیک روی دکمه شیشه‌ای جهت رفع حالت لودینگ در تلگرام"""
    try:
        HTTP_SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
            data={"callback_query_id": cb_id, "text": text or ""},
            timeout=3,
        )
    except Exception:
        pass


def process_admin_updates(history):
    """پردازش سریع پیام‌ها و کلیک‌های ادمین در تلگرام"""
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

            # ۱. پردازش کلیک روی دکمه‌ها
            if "callback_query" in update:
                cb = update["callback_query"]
                if str(cb["from"]["id"]) == str(ADMIN_ID):
                    cb_id = cb["id"]
                    data = cb["data"]
                    answer_callback(cb_id)

                    if data == "add_config_src":
                        history["bot_state"] = "WAITING_FOR_CONFIG_SRC"
                        send_admin_panel("📥 لطفاً آیدی یا لینک کانال/منبع <b>کانفیگ</b> را ارسال کنید:\n(مثال: <code>@v2ray_configs_pool</code>)")
                    elif data == "add_proxy_src":
                        history["bot_state"] = "WAITING_FOR_PROXY_SRC"
                        send_admin_panel("📥 لطفاً آیدی یا لینک کانال/منبع <b>پروکسی</b> را ارسال کنید:\n(مثال: <code>@ProxyMTProto</code>)")
                    elif data == "add_manual_config":
                        history["bot_state"] = "WAITING_FOR_MANUAL_CONFIG"
                        send_admin_panel("⚡️ لطفاً کانفیگ یا متن حاوی کدهای V2Ray را ارسال کنید:\n(سیستم خودکار متن را پاکسازی کرده و پرچم/تگ می‌زند)")
                    elif data == "add_manual_proxy":
                        history["bot_state"] = "WAITING_FOR_MANUAL_PROXY"
                        send_admin_panel("🚀 لطفاً لینک مستقیم پروکسی تلگرام را ارسال کنید:")
                    elif data == "list_sources":
                        cfg_s = "\n".join(history.get("custom_config_sources", [])) or "هیچ"
                        prx_s = "\n".join(history.get("custom_proxy_sources", [])) or "هیچ"
                        msg = f"<b>📋 منابع کانفیگ افزوده‌شده:</b>\n<code>{cfg_s}</code>\n\n<b>📦 منابع پروکسی افزوده‌شده:</b>\n<code>{prx_s}</code>"
                        send_admin_panel(msg)
                    elif data == "clear_sources":
                        history["custom_config_sources"] = []
                        history["custom_proxy_sources"] = []
                        send_admin_panel("✅ تمامی منابع سفارشی حذف شدند.")

            # ۲. پردازش ورودی‌های متنی ادمین
            elif "message" in update:
                msg = update["message"]
                if str(msg["from"]["id"]) == str(ADMIN_ID) and "text" in msg:
                    text = msg["text"].strip()
                    state = history.get("bot_state")

                    if text in ["/start", "/panel"]:
                        history["bot_state"] = None
                        send_admin_panel()

                    elif state == "WAITING_FOR_CONFIG_SRC":
                        normalized = normalize_source_url(text)
                        if normalized not in history["custom_config_sources"]:
                            history["custom_config_sources"].append(normalized)
                            send_admin_panel(f"✅ منبع کانفیگ جدید اضافه شد:\n<code>{normalized}</code>")
                        else:
                            send_admin_panel("⚠️ این منبع قبلاً ثبت شده بود.")
                        history["bot_state"] = None

                    elif state == "WAITING_FOR_PROXY_SRC":
                        normalized = normalize_source_url(text)
                        if normalized not in history["custom_proxy_sources"]:
                            history["custom_proxy_sources"].append(normalized)
                            send_admin_panel(f"✅ منبع پروکسی جدید اضافه شد:\n<code>{normalized}</code>")
                        else:
                            send_admin_panel("⚠️ این منبع قبلاً ثبت شده بود.")
                        history["bot_state"] = None

                    elif state == "WAITING_FOR_MANUAL_CONFIG":
                        found_cfgs = extract_configs_from_text(text)
                        if found_cfgs:
                            history["leftover_configs"] = found_cfgs + history.get("leftover_configs", [])
                            send_admin_panel(f"✅ تعداد <b>{len(found_cfgs)}</b> کانفیگ دریافت شد و در اولویت ارسال پارت بعدی قرار گرفت.")
                        else:
                            send_admin_panel("❌ هیچ کد کانفیگ معتبری (vless, vmess, trojan, ss) در متن یافت نشد.")
                        history["bot_state"] = None

                    elif state == "WAITING_FOR_MANUAL_PROXY":
                        found_pxs = re.findall(r'(https://t\.me/proxy\?[^\s#"\'>]+)', text)
                        if found_pxs:
                            history["leftover_proxies"] = found_pxs + history.get("leftover_proxies", [])
                            send_admin_panel(f"✅ تعداد <b>{len(found_pxs)}</b> پروکسی دریافت شد و در اولویت ارسال پارت بعدی قرار گرفت.")
                        else:
                            send_admin_panel("❌ هیچ لینک پروکسی معتبری در متن یافت نشد.")
                        history["bot_state"] = None

    except Exception as e:
        print(f"⚠️ خطا در بررسی آپدیت‌های ادمین: {e}")


def smart_sleep(seconds, history):
    """خواب هوشمند که در طول آن پیام‌ها و دکمه‌های ادمین پردازش می‌شوند"""
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
    history.setdefault("sent_proxies_hashes", [])
    history.setdefault("custom_config_sources", [])
    history.setdefault("custom_proxy_sources", [])
    history.setdefault("last_update_id", 0)
    history.setdefault("bot_state", None)
    return history


def save_history(history):
    history["sent_hashes"] = history["sent_hashes"][-5000:]
    history["sent_ip_ports"] = history["sent_ip_ports"][-3000:]
    history["sent_proxies_hashes"] = history["sent_proxies_hashes"][-5000:]
    history["leftover_configs"] = history["leftover_configs"][-300:]
    history["leftover_proxies"] = history["leftover_proxies"][-300:]

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

    base_github_sources = [
        "https://manager.onetwothree123.ir/",
        "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/all_extracted_configs.txt",
        "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt",
        "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
        "https://raw.githubusercontent.com/sakha1370/OpenRay/main/output/all_valid_proxies.txt",
        "https://raw.githubusercontent.com/ts-indexer/sub-indexer/main/sub/mix",
        "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/normal/mix",
        "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
        "https://raw.githubusercontent.com/EbrahimAhar/V2ray-Config/main/All_Configs_Sub.txt",
    ]

    all_config_sources = base_github_sources + history.get("custom_config_sources", [])

    for src in all_config_sources:
        try:
            r = HTTP_SESSION.get(src, timeout=10)
            if r.status_code == 200:
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
        except Exception as e:
            print(f"⚠️ خطا در خواندن منبع {src}: {e}")
        if len(valid_configs) >= 200:
            break

    return valid_configs


def collect_proxies(history, sent_proxies_set):
    print("📦 در حال جمع‌آوری پروکسی‌ها...")
    valid_proxies = list(history.get("leftover_proxies", []))
    seen_proxies = set(valid_proxies)

    base_proxy_sources = [
        "https://office.onetwothree123.ir/",
        "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/mtproto/data.txt",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "https://t.me/s/ProxyMTProto",
        "https://t.me/s/mtpro_to",
        "https://t.me/s/TelMTProto",
    ]

    all_proxy_sources = base_proxy_sources + history.get("custom_proxy_sources", [])

    for p_src in all_proxy_sources:
        try:
            r = HTTP_SESSION.get(p_src, timeout=8)
            if r.status_code == 200:
                found_p = re.findall(r'(https://t\.me/proxy\?[^\s#"\'>]+)', r.text)
                for p in found_p:
                    p_hash = get_md5(p)
                    if p_hash not in sent_proxies_set and p not in seen_proxies:
                        valid_proxies.append(p)
                        seen_proxies.add(p)
                    if len(valid_proxies) >= 150:
                        break
        except Exception as e:
            print(f"⚠️ خطا در خواندن منبع پروکسی {p_src}: {e}")
        if len(valid_proxies) >= 150:
            break

    fallback_proxies = [
        "https://t.me/proxy?server=⚡️🔥⚡️.freenet.cfd&port=443&secret=dd00000000000000000000000000000000",
        "https://t.me/proxy?server=cloud.freenet.icu&port=8443&secret=ee00000000000000000000000000000000",
        "https://t.me/proxy?server=germany.freenet.monster&port=443&secret=7gAAAAAAAAAAAAAAAAAAAAV3d3cuZ29vZ2xlLmNvbQ",
    ]
    for fp in fallback_proxies:
        if len(valid_proxies) >= 3:
            break
        if fp not in seen_proxies:
            valid_proxies.append(fp)
            seen_proxies.add(fp)

    return valid_proxies


def get_random_logo():
    logos = [f for f in os.listdir(".") if f.startswith("logo") and f.endswith(".jpg")]
    return random.choice(logos) if logos else None


# ─── نقطه ورود اصلی ────────────────────────────────────────────────
def main():
    if not TOKEN or not CHANNELS:
        raise ValueError("سکرت‌های TELEGRAM_BOT_TOKEN یا TELEGRAM_CHANNEL یافت نشدند!")

    history = load_history()

    # ارسال خودکار پنل به ادمین در ابتدای اجرای اسکریپت
    send_admin_panel("🚀 <b>ربات فعال شد!</b>\nاز پنل زیر برای مدیریت منابع استفاده کنید:")

    # بررسی پیام‌های قبلی ادمین
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

    cycle_configs = valid_configs[:100]
    history["leftover_configs"] = valid_configs[100:]

    cycle_proxies = valid_proxies[:100]
    history["leftover_proxies"] = valid_proxies[100:]

    config_batches = [cycle_configs[i : i + 3] for i in range(0, len(cycle_configs), 3)]
    proxy_batches = [cycle_proxies[i : i + 3] for i in range(0, len(cycle_proxies), 3)]

    sent_all_configs = []
    country_flags = {}
    country_counter = Counter()

    delay_between_posts = int(3600 / len(config_batches)) if len(config_batches) > 1 else 105

    print(f"\n🚀 شروع ارسال تدریجی {len(config_batches)} پارت (فاصله: {delay_between_posts} ثانیه)...")

    for b_idx, batch_c in enumerate(config_batches):
        loop_start_time = time.time()

        batch_p = list(proxy_batches[b_idx]) if b_idx < len(proxy_batches) else []
        if len(batch_p) < 3:
            for p in cycle_proxies:
                if p not in batch_p:
                    batch_p.append(p)
                if len(batch_p) == 3:
                    break

        for p in batch_p:
            sent_proxies_set.add(get_md5(p))

        default_proxy = "https://t.me/freenettir"
        p1 = batch_p[0] if len(batch_p) > 0 else default_proxy
        p2 = batch_p[1] if len(batch_p) > 1 else p1

        keyboard_buttons = [
            [{"text": "🚀 اتصال به پروکسی", "url": p1}, {"text": "🚀 اتصال به پروکسی", "url": p2}],
            [{"text": AD_BUTTON_TEXT, "url": AD_BUTTON_URL}],
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

        for channel in CHANNELS:
            try:
                if logo and os.path.exists(logo):
                    with open(logo, "rb") as photo_file:
                        send_telegram_with_retry(
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
                    send_telegram_with_retry(
                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                        data={
                            "chat_id": channel,
                            "text": post_text,
                            "parse_mode": "HTML",
                            "reply_markup": json.dumps(reply_markup),
                        },
                    )
            except Exception as e:
                print(f"❌ خطا در ارسال پارت {b_idx + 1} به کانال {channel}: {e}")

        print(f"✅ پارت {b_idx + 1} از {len(config_batches)} ارسال شد. (سریال: {history['last_serial']})")

        elapsed = time.time() - loop_start_time
        actual_sleep = max(0, delay_between_posts - elapsed)

        if b_idx < len(config_batches) - 1:
            # استفاده از خواب هوشمند جهت پردازش کلیک‌ها حین ارسال پارت‌ها
            smart_sleep(actual_sleep, history)

    # 📝 پایان ارسال پست‌ها و ایجاد فایل متنی نهایی
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

    share_text = quote("🚀 آخرین سرورها و پروکسی‌های پرسرعت رایگان را در کانال ما دنبال کنید:")
    share_url = f"https://t.me/share/url?url=https://t.me/freenettir&text={share_text}"
    support_markup = {
        "inline_keyboard": [[{"text": "🏛️ اشتراک‌گذاری و حمایت از کانال", "url": share_url}]]
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
