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

# تنظیمات متغیرهای محیطی
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
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def extract_configs_from_text(text):
    results = []
    raw_text = text

    if not re.search(r'(?:vless|vmess|trojan|ss)://', text):
        try:
            decoded_text = base64.b64decode(text.strip()).decode('utf-8', errors='ignore')
            raw_text = decoded_text
        except Exception:
            pass

    lines = raw_text.splitlines()
    for line in lines:
        match = re.search(r'((?:vless|vmess|trojan|ss)://[^\s"\'>]+)', line)
        if match:
            full_cfg = match.group(1)
            clean_cfg = full_cfg.split('#')[0]

            ping_match = re.search(r'ping[:\s]*([\d\.]+\s*ms)', line, re.IGNORECASE)
            ping_val = ping_match.group(1).strip() if ping_match else None

            results.append((clean_cfg, ping_val))

    return results


def extract_host_from_config(config_str):
    try:
        if config_str.startswith("vmess://"):
            b64_data = config_str.replace("vmess://", "").strip()
            b64_data += '=' * (-len(b64_data) % 4)
            decoded = base64.b64decode(b64_data).decode('utf-8', errors='ignore')
            json_data = json.loads(decoded)
            return json_data.get("add") or json_data.get("host")
        elif "@" in config_str:
            parts = config_str.split('@')
            host_port = parts[1].split(':')[0]
            return host_port.split('?')[0].split('/')[0]
    except Exception:
        pass
    return None


def get_country_info(config_str):
    try:
        host = extract_host_from_config(config_str)
        if host:
            if host in IP_CACHE:
                return IP_CACHE[host]

            res = requests.get(f"http://ip-api.com/json/{host}?fields=status,country,countryCode", timeout=2).json()
            if res.get('status') == 'success':
                country = res.get('country', 'Unknown')
                cc = res.get('countryCode', '')
                flag = "".join(chr(127397 + ord(c)) for c in cc.upper()) if cc else "🌍"
                IP_CACHE[host] = (country, flag)
                return country, flag
    except Exception:
        pass
    return "Unknown", "🌍"


def send_telegram_with_retry(url, data=None, files=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            res = requests.post(url, data=data, files=files, timeout=15)
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
        "با عرض پوزش ربات ارسال کننده جهت بازبینی و اصلاح غیر فعال شده ، از تحمل و صبوری شما بسیار سپاسگزارم \n"
        "با تشکر ؛ مدیریت کانال"
    )

    for channel in CHANNELS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={"chat_id": channel, "text": notice_text},
                timeout=10
            )
            print(f"✅ پیام عذرخواهی به کانال {channel} ارسال شد.")
        except Exception as e:
            print(f"⚠️ خطا در ارسال پیام عذرخواهی به کانال {channel}: {e}")


def send_crash_telegram_admin(error_msg, full_traceback):
    if not TOKEN or not ADMIN_ID:
        print("⚠️ آیدی ادمین تنظیم نشده است؛ خطای فنی فقط در لاگ ثبت شد.")
        return

    now_tehran = get_tehran_now()
    jy, jm, jd = gregorian_to_jalali(now_tehran.year, now_tehran.month, now_tehran.day)
    time_str = now_tehran.strftime("%H:%M:%S")
    date_str = f"{jy}/{jm:02d}/{jd:02d}"

    tb_truncated = full_traceback[-2500:] if len(full_traceback) > 2500 else full_traceback

    safe_error_msg = html.escape(str(error_msg))
    safe_tb = html.escape(tb_truncated)

    alert_text = (
        f"🚨 <b>هشدار کرش ربات تلگرام (مخصوص ادمین)</b>\n\n"
        f"📅 <b>زمان وقوع:</b> {date_str} | {time_str} 🇮🇷\n\n"
        f"❌ <b>علت خطا:</b>\n<code>{safe_error_msg}</code>\n\n"
        f"🔍 <b>جزئیات فنی (Traceback):</b>\n<pre>{safe_tb}</pre>\n\n"
        f"⚠️ لطفاً وضعیت ریپازیتوری را بررسی کنید."
    )

    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": ADMIN_ID, "text": alert_text, "parse_mode": "HTML"},
            timeout=10
        )
        if res.status_code == 200:
            print("✅ گزارش خطای فنی با موفقیت به پیوی ادمین ارسال شد.")
        else:
            print(f"⚠️ خطای تلگرام در ارسال به ادمین (کد {res.status_code}): {res.text}")
    except Exception as e:
        print(f"⚠️ خطا در ارتباط برای ارسال به ادمین: {e}")


def load_history():
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
                print("✅ تاریخچه با موفقیت از فایل ریپازیتوری بارگیری شد.")
        except Exception as e:
            print(f"⚠️ خطا در خواندن فایل تاریخچه: {e}")
            history = {}

    history.setdefault("last_serial", 0)
    history.setdefault("sent_hashes", [])
    history.setdefault("leftover_configs", [])
    history.setdefault("leftover_proxies", [])
    history.setdefault("sent_proxies_hashes", [])
    return history


def save_history(history):
    history["sent_hashes"] = history["sent_hashes"][-5000:]
    history["sent_proxies_hashes"] = history["sent_proxies_hashes"][-5000:]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ خطا در ذخیره محلی: {e}")

    if GITHUB_REPO and GITHUB_TOKEN:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{HISTORY_FILE}"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json"
            }

            res = requests.get(url, headers=headers, timeout=5)
            sha = res.json().get("sha") if res.status_code == 200 else None

            json_str = json.dumps(history, ensure_ascii=False, indent=2)
            content_b64 = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')

            payload = {
                "message": "🤖 بروزرسانی خودکار تاریخچه [Bot]",
                "content": content_b64
            }
            if sha:
                payload["sha"] = sha

            put_res = requests.put(url, headers=headers, json=payload, timeout=10)
            if put_res.status_code in [200, 201]:
                print("✅ فایل sent_configs_history.json مستقیماً در ریپازیتوری بروزرسانی شد.")
            else:
                print(f"⚠️ خطای API گیت‌هاب در ثبت تغییرات: کد {put_res.status_code}")
        except Exception as e:
            print(f"⚠️ خطا در بروزرسانی آنلاین فایل ریپازیتوری: {e}")


def collect_configs(history):
    print("\n🔍 در حال جمع‌آوری کانفیگ‌ها...")
    valid_configs = []

    for item in history.get("leftover_configs", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            valid_configs.append((item[0], item[1]))
        elif isinstance(item, str):
            valid_configs.append((item, None))

    primary_configs = []
    try:
        res = requests.get("https://manager.onetwothree123.ir/", timeout=10)
        if res.status_code == 200:
            primary_configs = extract_configs_from_text(res.text)
    except Exception as e:
        print(f"⚠️ منبع اصلی کانفیگ پاسخ نداد: {e}")

    for cfg, ping in primary_configs:
        cfg_hash = get_md5(cfg)
        already_exists = any(c[0] == cfg for c in valid_configs)
        if cfg_hash not in history["sent_hashes"] and not already_exists:
            valid_configs.append((cfg, ping))

    if len(valid_configs) < 100:
        print("🛡️ دریافت کانفیگ از اگرگیتورهای برتر گیت‌هاب...")
        github_sources = [
            "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/normal/mix",
            "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
            "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/All_Configs_Sub.txt",
            "https://raw.githubusercontent.com/morteza-f/v2ray-configs/main/All_Configs_Sub.txt"
        ]
        for src in github_sources:
            try:
                r = requests.get(src, timeout=8)
                if r.status_code == 200:
                    found = extract_configs_from_text(r.text)
                    for cfg, ping in found:
                        cfg_hash = get_md5(cfg)
                        already_exists = any(c[0] == cfg for c in valid_configs)
                        if cfg_hash not in history["sent_hashes"] and not already_exists:
                            valid_configs.append((cfg, ping))
                        if len(valid_configs) >= 150:
                            break
            except Exception as e:
                print(f"⚠️ خطا در خواندن اگرگیتور {src}: {e}")
            if len(valid_configs) >= 150:
                break

    if len(valid_configs) < 3 and primary_configs:
        print("⚠️ فعال‌سازی حالت بازیافت کانفیگ‌ها...")
        for cfg, ping in primary_configs:
            already_exists = any(c[0] == cfg for c in valid_configs)
            if not already_exists:
                valid_configs.append((cfg, ping))

    return valid_configs


def collect_proxies(history):
    print("📦 در حال جمع‌آوری پروکسی‌ها...")
    valid_proxies = history["leftover_proxies"]
    primary_proxies = []

    try:
        res = requests.get("https://office.onetwothree123.ir/", timeout=10)
        if res.status_code == 200:
            primary_proxies = re.findall(r'(https://t\.me/proxy\?[^\s#"\'>]+)', res.text)
    except Exception as e:
        print(f"⚠️ منبع اصلی پروکسی پاسخ نداد: {e}")

    for p in primary_proxies:
        p_hash = get_md5(p)
        if p_hash not in history["sent_proxies_hashes"] and p not in valid_proxies:
            valid_proxies.append(p)

    if len(valid_proxies) < 100:
        print("🛡️ دریافت پروکسی از منابع پشتیبان...")
        proxy_sources = [
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/mtproto/data.txt",
            "https://t.me/s/ProxyMTProto",
            "https://t.me/s/mtpro_to",
            "https://t.me/s/TelMTProto"
        ]
        for p_src in proxy_sources:
            try:
                r = requests.get(p_src, timeout=8)
                if r.status_code == 200:
                    found_p = re.findall(r'(https://t\.me/proxy\?[^\s#"\'>]+)', r.text)
                    for p in found_p:
                        if p not in valid_proxies:
                            valid_proxies.append(p)
                        if len(valid_proxies) >= 100:
                            break
            except Exception as e:
                print(f"⚠️ خطا در خواندن منبع پروکسی {p_src}: {e}")
            if len(valid_proxies) >= 100:
                break

    fallback_proxies = [
        "https://t.me/proxy?server=⚡️🔥⚡️.freenet.cfd&port=443&secret=dd00000000000000000000000000000000",
        "https://t.me/proxy?server=cloud.freenet.icu&port=8443&secret=ee00000000000000000000000000000000",
        "https://t.me/proxy?server=germany.freenet.monster&port=443&secret=7gAAAAAAAAAAAAAAAAAAAAV3d3cuZ29vZ2xlLmNvbQ"
    ]
    while len(valid_proxies) < 3:
        for fp in fallback_proxies:
            if fp not in valid_proxies:
                valid_proxies.append(fp)

    return valid_proxies


def get_random_logo():
    logos = [f for f in os.listdir('.') if f.startswith('logo') and f.endswith('.jpg')]
    return random.choice(logos) if logos else None


def main():
    if not TOKEN or not CHANNELS:
        raise ValueError("سکرت‌های TELEGRAM_BOT_TOKEN یا TELEGRAM_CHANNEL یافت نشدند!")

    history = load_history()
    cycle_counter = 0

    while True:
        cycle_counter += 1
        print(f"\n==========================================")
        print(f"=== 🛠️ شروع چرخه شماره {cycle_counter} (۶۰ دقیقه ارسال + ۳۰ دقیقه استراحت) ===")
        print(f"📌 آخرین شماره سریال ثبت‌شده: {history.get('last_serial', 0)}")
        print(f"==========================================")

        valid_configs = collect_configs(history)
        valid_proxies = collect_proxies(history)

        print(f"📊 کانفیگ‌های آماده: {len(valid_configs)} | پروکسی‌های آماده: {len(valid_proxies)}")

        if len(valid_configs) < 3:
            print("⚠️ تعداد کانفیگ‌های موجود کمتر از ۳ عدد است. ۵ دقیقه صبر می‌کنیم...")
            time.sleep(300)
            continue

        cycle_configs = valid_configs[:100]
        history["leftover_configs"] = valid_configs[100:]

        cycle_proxies = valid_proxies[:100]
        history["leftover_proxies"] = valid_proxies[100:]

        config_batches = [cycle_configs[i:i + 3] for i in range(0, len(cycle_configs), 3)]
        proxy_batches = [cycle_proxies[i:i + 3] for i in range(0, len(cycle_proxies), 3)]

        sent_all_configs = []
        country_flags = {}
        country_counter = Counter()

        delay_between_posts = int(3600 / len(config_batches)) if config_batches else 105

        print(f"\n🚀 شروع ارسال تدریجی {len(config_batches)} پست به کانال‌ها (پایه هر {delay_between_posts} ثانیه)...")

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
                history["sent_proxies_hashes"].append(get_md5(p))

            default_proxy = "https://t.me/freenettir"
            p1 = batch_p[0] if len(batch_p) > 0 else default_proxy
            p2 = batch_p[1] if len(batch_p) > 1 else p1

            keyboard_buttons = [
                [{"text": "🚀 اتصال به پروکسی", "url": p1}, {"text": "🚀 اتصال به پروکسی", "url": p2}],
                [{"text": AD_BUTTON_TEXT, "url": AD_BUTTON_URL}]
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
                final_cfg = f"{cfg}#{serial_str} - {flag} {country}{ping_str} | @freenettir"
                sent_all_configs.append(final_cfg)

                ping_display = f" (⚡️ پینگ: <code>{ping}</code>)" if ping else ""
                post_text += f"<b>📌 سرور {labels[idx]} :</b>{ping_display}\n\n<code>{final_cfg}</code>\n\n"
                history["sent_hashes"].append(get_md5(cfg))

            post_text += "<b>🌐 @freenettir  مخزن اصلی سرورها</b>\n\n🔹 #v2ray #vpn #proxy"
            logo = get_random_logo()

            for channel in CHANNELS:
                try:
                    if logo and os.path.exists(logo):
                        with open(logo, 'rb') as photo_file:
                            send_telegram_with_retry(
                                f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                data={"chat_id": channel, "caption": post_text, "parse_mode": "HTML", "reply_markup": json.dumps(reply_markup)},
                                files={"photo": photo_file}
                            )
                    else:
                        send_telegram_with_retry(
                            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                            data={"chat_id": channel, "text": post_text, "parse_mode": "HTML", "reply_markup": json.dumps(reply_markup)}
                        )
                except Exception as e:
                    print(f"❌ خطا در ارسال پارت {b_idx + 1} به کانال {channel}: {e}")

            print(f"✅ پارت {b_idx + 1} از {len(config_batches)} ارسال شد. (سریال: {history['last_serial']})")

            elapsed = time.time() - loop_start_time
            actual_sleep = max(0, delay_between_posts - elapsed)

            if b_idx < len(config_batches) - 1:
                time.sleep(actual_sleep)

        print("\n📝 ۶۰ دقیقه ارسال تکمیل شد. ارسال استیکر و فایل متنی سرورها...")
        for channel in CHANNELS:
            try:
                send_telegram_with_retry(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": channel, "text": "📝"})
            except Exception:
                pass

        time.sleep(2)

        share_text = quote("🚀 آخرین سرورها و پروکسی‌های پرسرعت رایگان را در کانال ما دنبال کنید:")
        share_url = f"https://t.me/share/url?url=https://t.me/freenettir&text={share_text}"
        support_markup = {"inline_keyboard": [[{"text": "🏛️ اشتراک‌گذاری و حمایت از کانال", "url": share_url}]]}

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

        config_caption = (
            "📦 <b>مجموعه ۱۰۰ سرور پرسرعت نهایی</b>\n"
            "──────────────────\n"
            f"📅 <b>تاریخ:</b> {date_str}  |  ⏰ <b>ساعت:</b> {time_str} 🇮🇷\n"
            "──────────────────\n\n"
            f"🌍 <b>لوکیشن‌های برتر:</b>\n"
            f"{stats_text}\n\n"
            "💡 <b>راهنما:</b> فایل را دانلود کرده و در برنامه (v2rayNG / NekoBox) از بخش Import File وارد کنید.\n\n"
            "🌐 <b>@freenettir | مرجع سرورهای رایگان</b>\n\n"
            "🔹 #v2ray #vpn #proxy"
        )

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
                                "reply_markup": json.dumps(support_markup)
                            },
                            files={"document": (config_file_name, doc_file)}
                        )
                    if res and res.status_code == 200:
                        print(f"✅ فایل متنی با موفقیت به کانال {channel} ارسال شد.")
                    else:
                        print(f"⚠️ خطای ارسال فایل به {channel}: کد {res.status_code if res else 'Unknown'}")
                except Exception as e:
                    print(f"⚠️ خطا در ارسال فایل متنی به {channel}: {e}")

        # 💾 ذخیره آنلاین تاریخچه تنها یک‌بار در انتهای هر چرخه
        save_history(history)

        print("\n😴 چرخه تمام شد؛ شروع ۳۰ دقیقه استراحت...")
        time.sleep(1800)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        tb = traceback.format_exc()
        print(f"💥 کرش کلی ربات: {err}")
        send_crash_telegram_admin(str(err), tb)
        send_channel_maintenance_notice()
        sys.exit(1)
