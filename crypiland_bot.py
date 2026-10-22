#!/usr/bin/env python3
"""
ربات خبری کریپی‌لند — تک‌فایلی.

۱. اخبار: RSS + کانال‌های تلگرام + توییت‌ها (از طریق RSS bridge)
۲. بازنویسی فارسی با هوش مصنوعی (گپ‌جی‌پی‌تی، سازگار با OpenAI)
۳. عکس خبر فقط روی اخبار فوری
۴. پست قیمت هر ساعت، پین‌شده، حداکثر ۴ پین

اجرا: python3 crypiland_bot.py
وابستگی: هیچ. فقط کتابخانه استاندارد پایتون ۳٫۱۰+
"""
import html
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ============================ تنظیمات ============================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@crypiland")

# --- هوش مصنوعی (گپ‌جی‌پی‌تی — سازگار با OpenAI) ---
AI_BASE = os.environ.get("AI_BASE", "https://api.gapgpt.app/v1")
AI_KEY = os.environ.get("AI_KEY", "")
MODEL = os.environ.get("MODEL", "gpt-4o-mini")

# --- نوبیتکس ---
# توکن فقط برای اندپوینت‌های حساب لازم است؛ /market/stats عمومی است.
NOBITEX_TOKEN = os.environ.get("NOBITEX_TOKEN", "")
# اگر api.nobitex.ir از سرورت resolve نمی‌شود، یک واسط روی هاست ایرانی خودت بساز
# که همان پاسخ /market/stats را برگرداند و آدرسش را اینجا بده.
NOBITEX_BASE = os.environ.get("NOBITEX_BASE", "https://api.nobitex.ir")
PRICE_COINS = [                      # (نماد نوبیتکس، نام فارسی، ایموجی)
    ("btc", "بیت‌کوین", "🟠"),
    ("eth", "اتریوم", "⚪"),
    ("sol", "سولانا", "🟣"),
    ("xrp", "ریپل", "⚫"),
    ("doge", "دوج‌کوین", "🟡"),
]
PRICE_INTERVAL = 3600                # پست قیمت هر ۱ ساعت
MAX_PINS = 4                         # بیشتر از این تعداد پین نگه نمی‌دارد
DELETE_UNPINNED = True               # پیام قیمت قدیمی بعد از آنپین حذف هم بشود؟

STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json"))
POLL_INTERVAL = 300
MAX_PER_CYCLE = 1                    # در هر چرخه حداکثر یک خبر
GAP_SECONDS = 4 * 3600               # حداقل ۴ ساعت فاصله بین دو خبر
MAX_NEWS_PER_DAY = 5                 # سقف کل اخبار در ۲۴ ساعت
ONLY_BREAKING = False                # True یعنی فقط اخبار فوری منتشر شود

# --- پیام تبلیغاتی ---
PROMO_INTERVAL = int(os.environ.get("PROMO_INTERVAL", 4 * 3600))   # هر ۴ ساعت
SITE_URL = os.environ.get("SITE_URL", "https://dashboard.crypiland.ir")
PROMOS = [
    ("💱 <b>معامله سریع، بدون پیچیدگی</b>\n\n"
     "خرید و فروش تتر و ارزهای دیجیتال با نرخ لحظه‌ای و تسویه آنی.\n"
     "ثبت‌نام کمتر از دو دقیقه طول می‌کشد.", "شروع معامله"),

    ("📈 <b>بازار را حرفه‌ای دنبال کن</b>\n\n"
     "نمودار پیشرفته، دفتر سفارش لحظه‌ای و ثبت سفارش محدود،\n"
     "همه در یک پنل فارسی و ساده.", "مشاهده بازار"),

    ("🎁 <b>دعوت کن، پاداش بگیر</b>\n\n"
     "با سیستم دعوت کریپی‌لند از معاملات دوستانت سهم می‌گیری.\n"
     "لینک اختصاصی‌ات در پنل کاربری آماده است.", "دریافت لینک دعوت"),

    ("🔒 <b>دارایی‌ات، کنترل خودت</b>\n\n"
     "احراز هویت رسمی، ورود دومرحله‌ای و پشتیبانی فارسی.\n"
     "همین حالا حسابت را بساز.", "ساخت حساب"),
]

# --- منابع خبری ---
FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
]

# کانال‌های عمومی تلگرام (بدون @). از صفحه وب t.me/s/... خوانده می‌شود.
TG_CHANNELS = [c for c in os.environ.get("TG_CHANNELS", "").split(",") if c.strip()]

# توییت‌ها: X API رایگان نیست. یک RSS bridge (مثل RSSHub) لازم است.
# نمونه: X_RSS=https://rsshub.example.com/twitter/user/{user}
X_RSS = os.environ.get("X_RSS", "")
X_ACCOUNTS = [a for a in os.environ.get("X_ACCOUNTS", "").split(",") if a.strip()]

# --- الگوهای دسته‌بندی (فارسی + انگلیسی) ---
BREAKING = (r"hack|exploit|breach|halt|ban\b|lawsuit|\bsec\b|\betf\b|approv|crash|surge|"
            r"delist|bankrupt|\bfed\b|\bcpi\b|"
            r"هک|سرقت|توقف|ممنوع|شکایت|تصویب|تأیید|ریزش|جهش|ورشکست|توقیف")
ANALYSIS = (r"\bwhy\b|how to|guide|explained|analysis|opinion|outlook|forecast|deep dive|"
            r"تحلیل|چرا|آموزش|راهنما|چشم‌انداز|پیش‌بینی")
NOISE = (r"sponsored|press release|presale|price prediction|giveaway|best .* to buy|casino|"
         r"رپورتاژ|تبلیغ|پیش‌فروش|قرعه‌کشی|ثبت‌نام کنید|لینک عضویت")

STYLE = """تو سردبیر کانال فارسی‌زبان رمزارز «کریپی‌لند» هستی.

لحن: فارسی روان و حرفه‌ای، بدون هیجان کاذب، حداکثر ۲ ایموجی.
اصطلاح انگلیسی را با معادل فارسی + اصل داخل پرانتز بیاور. مثال: صندوق قابل معامله (ETF).
هرگز توصیه سرمایه‌گذاری نده و قیمت پیش‌بینی نکن.

مهم: فقط از اطلاعات متن ورودی استفاده کن. هیچ عدد، تاریخ یا نامی که در ورودی نیست ننویس.
خبر را بازنویسی کن، نه ترجمه واژه‌به‌واژه.

فقط یک شیء JSON برگردان، بدون بک‌تیک و بدون توضیح اضافه:
{"headline": "تیتر فارسی حداکثر ۹ کلمه",
 "body": "۲ تا ۳ پاراگراف کوتاه، مجموعاً ۶۰ تا ۱۲۰ کلمه",
 "tags": ["حداکثر ۳ هشتگ فارسی بدون #"],
 "ok": true}
اگر خبر بی‌ارزش، تبلیغاتی یا صرفاً یک اعلان قیمت بود، ok را false بگذار."""

TEHRAN = timezone(timedelta(hours=3, minutes=30))
FA_DIGITS = str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫")


# ============================ ابزار ============================

def http(url, payload=None, headers=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; CrypiLandBot/2.0)"}
    if data:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None


def clean(text):
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def fa(text):
    """تبدیل ارقام لاتین به فارسی."""
    return str(text).translate(FA_DIGITS)


def esc(text):
    return html.escape(text or "", quote=False)


# ============================ حافظه ============================

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("urls", [])
    s.setdefault("titles", [])
    s.setdefault("last_post", 0)
    s.setdefault("last_price", 0)
    s.setdefault("last_promo", 0)
    s.setdefault("promo_index", 0)
    s.setdefault("news_log", [])      # زمان انتشار اخبار، برای سقف روزانه
    s.setdefault("pins", [])          # [message_id, ...] از قدیم به جدید
    return s


def save_state(state):
    state["urls"] = state["urls"][-500:]
    state["titles"] = state["titles"][-300:]
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def check_writable():
    folder = os.path.dirname(STATE_FILE) or "."
    probe = STATE_FILE + ".probe"
    try:
        os.makedirs(folder, exist_ok=True)
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        raise SystemExit(
            f"نمی‌توان در «{folder}» نوشت ({e.strerror}).\n"
            f"یا مالکیت را درست کن:  sudo chown -R $USER {folder}\n"
            f"یا مسیر دیگری بده:     export STATE_FILE=~/crypiland/seen.json")


# ============================ منابع خبری ============================

MEDIA_NS = "{http://search.yahoo.com/mrss/}"


def _find_image(node, raw_desc):
    """پیدا کردن عکس خبر از enclosure / media:content / تگ img داخل توضیحات."""
    for tag in (f"{MEDIA_NS}content", f"{MEDIA_NS}thumbnail", "enclosure"):
        el = node.find(tag)
        if el is not None:
            url = el.get("url") or ""
            if url.startswith("http") and (el.get("type", "image").startswith("image")
                                           or re.search(r"\.(jpg|jpeg|png|webp)", url, re.I)):
                return url
    m = re.search(r'<img[^>]+src=["\']([^"\']+)', raw_desc or "")
    return m.group(1) if m and m.group(1).startswith("http") else ""


def canonical(url):
    p = urllib.parse.urlsplit(url.strip())
    return f"https://{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def fetch_rss(name, url):
    items = []
    root = ET.fromstring(http(url))

    for node in root.iterfind(".//item"):                       # RSS 2.0
        link, title = (node.findtext("link") or "").strip(), clean(node.findtext("title"))
        raw = node.findtext("description") or ""
        if link and title:
            items.append({"source": name, "title": title, "url": link,
                          "summary": clean(raw)[:1000], "image": _find_image(node, raw)})

    atom = "{http://www.w3.org/2005/Atom}"
    for node in root.iterfind(f"{atom}entry"):                  # Atom
        el = node.find(f"{atom}link")
        link = el.get("href") if el is not None else ""
        title = clean(node.findtext(f"{atom}title"))
        raw = node.findtext(f"{atom}summary") or node.findtext(f"{atom}content") or ""
        if link and title:
            items.append({"source": name, "title": title, "url": link,
                          "summary": clean(raw)[:1000], "image": _find_image(node, raw)})
    return items


def fetch_telegram(channel, limit=5):
    """خواندن آخرین پست‌های یک کانال عمومی از پیش‌نمایش وب t.me/s/<channel>.
    نیازی به اکانت، توکن یا Telethon ندارد — ولی فقط برای کانال‌های عمومی کار می‌کند."""
    page = http(f"https://t.me/s/{channel}").decode("utf-8", "replace")
    items = []
    for chunk in page.split('data-post="')[1:]:
        post_id = chunk.split('"', 1)[0]
        m = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        if not m:
            continue
        text = clean(m.group(1))
        if len(text) < 60:                    # پست‌های خیلی کوتاه معمولاً تبلیغ یا واکنش‌اند
            continue
        items.append({"source": f"@{channel}", "title": text[:140],
                      "url": f"https://t.me/{post_id}", "summary": text[:1000], "image": ""})
    return items[-limit:]                     # جدیدترین‌ها انتهای صفحه هستند


def collect():
    items = []
    for name, url in FEEDS:
        try:
            items += fetch_rss(name, url)
        except Exception as e:
            print(f"[!] {name}: {e}")

    for user in X_ACCOUNTS:
        if not X_RSS:
            break
        try:
            items += fetch_rss(f"X/@{user.strip()}", X_RSS.format(user=user.strip()))
        except Exception as e:
            print(f"[!] X/{user}: {e}")

    for ch in TG_CHANNELS:
        try:
            items += fetch_telegram(ch.strip())
        except Exception as e:
            print(f"[!] TG/{ch}: {e}")
    return items


# ============================ فیلتر و دسته‌بندی ============================

def words(text):
    return {w for w in re.findall(r"[a-zآ-ی0-9]+", text.lower()) if len(w) > 2}


def is_similar(title, old_titles):
    a = words(title)
    for old in old_titles:
        b = words(old)
        if a and b and len(a & b) / len(a | b) >= 0.6:
            return True
    return False


def category(item):
    """breaking | analysis | news | None (نویز)"""
    text = f"{item['title']} {item['summary']}".lower()
    if re.search(NOISE, text):
        return None
    if re.search(BREAKING, text):
        return "breaking"
    if re.search(ANALYSIS, text):
        return "analysis"
    return "news"


# ============================ هوش مصنوعی ============================

def ask_ai(system, user, json_mode=True):
    payload = {"model": MODEL, "temperature": 0.3, "max_tokens": 800,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        body = http(f"{AI_BASE}/chat/completions", payload=payload,
                    headers={"Authorization": f"Bearer {AI_KEY}"}, timeout=90)
    except RuntimeError as e:
        if json_mode and ("response_format" in str(e) or "400" in str(e)):
            return ask_ai(system, user, json_mode=False)
        raise
    return json.loads(body)["choices"][0]["message"]["content"]


def rewrite(item, cat):
    hint = {"breaking": "خبر فوری است؛ تیتر کوتاه و مستقیم.",
            "analysis": "تحلیل است؛ مشخص کن نظر نویسنده است نه واقعیت قطعی.",
            "news": "خبر عادی؛ خلاصه دقیق و بی‌طرف."}[cat]
    text = ask_ai(STYLE, f"{hint}\n\nمنبع: {item['source']}\nتیتر: {item['title']}\n"
                         f"متن: {item['summary'] or '(فقط تیتر موجود است)'}")
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    s, e = text.find("{"), text.rfind("}")
    if s < 0:
        return None
    data = json.loads(text[s:e + 1])
    return data if data.get("ok") and data.get("headline") and data.get("body") else None


# ============================ تلگرام ============================

def tg(method, payload):
    return json.loads(http(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", payload=payload))


def render(post, item, cat):
    icon = {"breaking": "🚨", "analysis": "🧠", "news": "📰"}[cat]
    tags = " ".join("#" + t.strip().replace(" ", "_") for t in post.get("tags", [])[:3])
    return (f"{icon} <b>{esc(post['headline'])}</b>\n\n"
            f"{esc(post['body'])}\n\n"
            f"{esc(tags)} #کریپی_لند\n\n"
            f"<i>منبع: {esc(item['source'])}</i>\n🔷 @crypiland")


def publish_news(text, url, image=""):
    """عکس فقط اگر داده شده باشد و متن در محدودیت ۱۰۲۴ کاراکتری کپشن جا شود."""
    buttons = {"inline_keyboard": [[
        {"text": "🔗 مشاهده منبع", "url": url},
        {"text": "💱 کریپی‌لند", "url": "https://dashboard.crypiland.ir"}]]}

    if image and len(text) <= 1024:
        try:
            return tg("sendPhoto", {"chat_id": CHANNEL_ID, "photo": image, "caption": text,
                                    "parse_mode": "HTML", "reply_markup": buttons})
        except RuntimeError as e:
            print(f"[!] ارسال عکس نشد، متنی می‌فرستم: {e}")

    return tg("sendMessage", {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML",
                              "disable_web_page_preview": True, "reply_markup": buttons})


# ============================ قیمت نوبیتکس ============================

def nobitex_stats():
    """یک درخواست، هم قیمت ارزها به تتر و هم تتر به ریال."""
    headers = {"Authorization": f"Token {NOBITEX_TOKEN}"} if NOBITEX_TOKEN else {}
    src = ",".join([c for c, _, _ in PRICE_COINS] + ["usdt"])
    try:
        data = json.loads(http(f"{NOBITEX_BASE}/market/stats",
                               payload={"srcCurrency": src, "dstCurrency": "usdt,rls"},
                               headers=headers))
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.gaierror):
            raise RuntimeError(
                f"دامنه {urllib.parse.urlsplit(NOBITEX_BASE).netloc} از این سرور resolve نمی‌شود. "
                f"DNS سرور را چک کن یا NOBITEX_BASE را روی واسط خودت بگذار.") from None
        raise RuntimeError(f"اتصال به نوبیتکس ناموفق: {e.reason}") from None
    return data.get("stats", {})


def _num(value, digits=0):
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _change(stat):
    """درصد تغییر ۲۴ ساعته با ایموجی سبز/قرمز (تلگرام رنگ متن ندارد)."""
    try:
        pct = float(stat.get("dayChange", 0))
    except (TypeError, ValueError):
        return ""
    icon = "🟢" if pct >= 0 else "🔴"
    sign = "+" if pct >= 0 else "−"
    return f"{icon} {sign}{fa(f'{abs(pct):.1f}')}٪"


def build_price_post():
    stats = nobitex_stats()
    now = datetime.now(TEHRAN).strftime("%H:%M")
    lines = [f"📊 <b>نبض بازار</b> — ساعت {fa(now)}", ""]

    usdt = stats.get("usdt-rls")
    if usdt:
        toman = float(usdt.get("latest", 0)) / 10        # نوبیتکس ریال می‌دهد
        lines.append(f"💵 <b>تتر:</b> {fa(_num(toman))} تومان  {_change(usdt)}")
        lines.append("")

    for code, name, dot in PRICE_COINS:
        stat = stats.get(f"{code}-usdt")
        if not stat:
            continue
        price = float(stat.get("latest", 0))
        lines.append(f"{dot} <b>{name}:</b> ${fa(_num(price, 2 if price < 10 else 0))}"
                     f"  {_change(stat)}")

    lines += ["", "<i>تغییرات ۲۴ ساعته</i>", "🔷 @crypiland"]
    return "\n".join(lines)


def post_prices(state):
    text = build_price_post()
    msg = tg("sendMessage", {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML",
                             "disable_web_page_preview": True})
    mid = msg["result"]["message_id"]

    tg("pinChatMessage", {"chat_id": CHANNEL_ID, "message_id": mid,
                          "disable_notification": True})
    state["pins"].append(mid)

    while len(state["pins"]) > MAX_PINS:                  # قدیمی‌ترین پین کنار می‌رود
        old = state["pins"].pop(0)
        for method in (["unpinChatMessage", "deleteMessage"] if DELETE_UNPINNED
                       else ["unpinChatMessage"]):
            try:
                tg(method, {"chat_id": CHANNEL_ID, "message_id": old})
            except RuntimeError as e:
                print(f"[!] {method} برای {old}: {e}")

    state["last_price"] = time.time()
    print(f"[✓] قیمت‌ها منتشر و پین شد (پین‌های فعال: {len(state['pins'])})")


# ============================ پیام تبلیغاتی ============================

def post_promo(state):
    """هر چند ساعت یک پیام دعوت به سایت، به ترتیب چرخشی تا تکراری نشود."""
    text, button = PROMOS[state["promo_index"] % len(PROMOS)]
    tg("sendMessage", {
        "chat_id": CHANNEL_ID,
        "text": f"{text}\n\n🔷 @crypiland",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": True,          # تبلیغ نباید نوتیفیکیشن بدهد
        "reply_markup": {"inline_keyboard": [[{"text": f"🚀 {button}", "url": SITE_URL}]]},
    })
    state["promo_index"] = (state["promo_index"] + 1) % len(PROMOS)
    state["last_promo"] = time.time()
    print(f"[✓] پیام تبلیغاتی {state['promo_index']} منتشر شد")


def news_today(state):
    """تعداد اخبار منتشرشده در ۲۴ ساعت گذشته."""
    cutoff = time.time() - 86400
    state["news_log"] = [t for t in state["news_log"] if t > cutoff]
    return len(state["news_log"])


# ============================ حلقه اصلی ============================

def cycle(state):
    if time.time() - state["last_price"] >= PRICE_INTERVAL:
        try:
            post_prices(state)
            save_state(state)
        except Exception as e:
            print(f"[!] خطای قیمت: {e}")

    if time.time() - state["last_promo"] >= PROMO_INTERVAL:
        try:
            post_promo(state)
            save_state(state)
        except Exception as e:
            print(f"[!] خطای تبلیغ: {e}")

    # سقف‌های خبری: فاصله زمانی و تعداد روزانه
    if time.time() - state["last_post"] < GAP_SECONDS or news_today(state) >= MAX_NEWS_PER_DAY:
        save_state(state)
        return

    posted = 0
    for item in collect():
        if posted >= MAX_PER_CYCLE:
            break

        url = canonical(item["url"])
        if url in state["urls"] or is_similar(item["title"], state["titles"]):
            continue

        cat = category(item)
        state["urls"].append(url)
        state["titles"].append(item["title"])
        if not cat or (ONLY_BREAKING and cat != "breaking"):
            continue

        try:
            post = rewrite(item, cat)
            if not post:
                continue
            # عکس فقط روی اخبار فوری
            image = item.get("image", "") if cat == "breaking" else ""
            publish_news(render(post, item, cat), url, image)
            state["last_post"] = time.time()
            state["news_log"].append(time.time())
            posted += 1
            print(f"[✓] {cat}{' +عکس' if image else ''} "
                  f"({news_today(state)}/{MAX_NEWS_PER_DAY} امروز): {post['headline']}")
            time.sleep(3)
        except Exception as e:
            print(f"[!] خطا در «{item['title'][:50]}»: {e}")

    save_state(state)


def main():
    if not BOT_TOKEN or not AI_KEY:
        raise SystemExit("BOT_TOKEN و AI_KEY را تنظیم کن")
    check_writable()

    print(f"🤖 ربات کریپی‌لند شروع شد (حافظه: {STATE_FILE})")
    state = load_state()
    while True:
        try:
            cycle(state)
        except Exception as e:
            print(f"[!] خطای چرخه: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
