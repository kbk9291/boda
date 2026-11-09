from __future__ import annotations
import os, re, json, time, hashlib, logging, inspect, asyncio, random
from collections import deque
from html import escape
from typing import Any
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity, ChatPermissions, User
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError, RetryAfter
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, ConversationHandler, ContextTypes, filters

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pubg-scam-detector")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
OWNER_IDS = {8121013255} | {int(v) for v in os.getenv("OWNER_IDS", "").split(",") if v.strip().isdigit()}
SOURCE_CHANNEL = os.getenv("SOURCE_CHANNEL", "@Nsabin3").strip()
GROUP_WARNING_COOLDOWN = max(15, int(os.getenv("GROUP_WARNING_COOLDOWN", "60")))
SEARCH_RESULTS_LIMIT = max(1, int(os.getenv("SEARCH_RESULTS_LIMIT", "5")))
if not BOT_TOKEN: raise RuntimeError("Missing BOT_TOKEN")
if not REDIS_URL or not REDIS_TOKEN: raise RuntimeError("Missing Upstash REST URL/token")

SEARCH, REPORT_TEXT, REPORT_REASON, ADMIN_ID, REPORT_URL = range(5)
DELETE_REPORTS = 5
EDIT_MESSAGE = 6
REPORT_USERNAME = 7
REPORT_PUBG = 8

DEFAULT_WELCOME = (
    "🛡 كاشف بلاغات نصب PUBG\n━━━━━━━━━━━━━━\n"
    "🔎 ابحث عن البلاغات المسجّلة بثلاث طرق:\n"
    "🔴 رقم المحفظة / الكاش\n🎮 معرّف PUBG ID\n👤 اسم مستخدم تيليجرام\n\n"
    "📌  قاعدة البيانات تشمل البلاغات الجديدة التي يرصدها البوت بعد تشغيله.\n"
    "‼️ عدم العثور على بلاغ لا يثبت أن الشخص مضمون.\n━━━━━━━━━━━━━━"
)
DEFAULT_HELP = (
    "🧭 طريقة الاستخدام\n\nاضغط «كشف نصاب»، ثم اختر نوع البحث:\n"
    "🔴 رقم المحفظة / الكاش\n🎮 PUBG ID\n👤 يوزر تيليجرام\n\n"
    "‼️ عدم وجود نتيجة لا يثبت أن الشخص مضمون."
)
DEFAULT_SEARCH_GUIDE = (
    "اختر طريقة البحث المناسبة:\n\n"
    "💳 البحث برقم المحفظة / الكاش: اضغط زر رقم المحفظة ثم أرسل الرقم.\n"
    "🆔 البحث بـ Telegram ID: اضغط زر ID تيليجرام ثم أرسل الرقم الرقمي للحساب.\n"
    "👤 البحث باليوزر: اضغط زر يوزر تيليجرام ثم أرسل اسم المستخدم مع @ أو بدونها.\n"
    "🎮 البحث بـ PUBG ID: اضغط زر PUBG ID ثم أرسل المعرّف.\n"
    "📌 إذا عُثر على بلاغ، ستظهر رسالة التحذير وزر رابط منشور البلاغ إن كان الرابط متوفرًا.\n"
    "⚠️ عدم العثور على بلاغ لا يثبت أن الشخص مضمون."
)
DEFAULT_GROUP_WARNING = (
    "⚠️ تحذير: توجد بلاغات مسجلة تطابق بيانات في هذه الرسالة.\n"
    "تحقّق من التفاصيل؛ البلاغ وحده ليس حكمًا نهائيًا."
)
WELCOME_ENTITIES = [
    {"type":"custom_emoji","offset":0,"length":2,"custom_emoji_id":"5891225499677496831"},
    {"type":"bold","offset":3,"length":20},
    {"type":"custom_emoji","offset":39,"length":2,"custom_emoji_id":"5258396243666681152"},
    {"type":"custom_emoji","offset":79,"length":2,"custom_emoji_id":"5890939368956237177"},
    {"type":"custom_emoji","offset":102,"length":2,"custom_emoji_id":"5967378280607652101"},
    {"type":"custom_emoji","offset":119,"length":2,"custom_emoji_id":"6032994772321309200"},
    {"type":"custom_emoji","offset":143,"length":2,"custom_emoji_id":"5965359207891867239"},
    {"type":"custom_emoji","offset":214,"length":2,"custom_emoji_id":"5888630540566796058"},
]
HELP_ENTITIES = [
    {"type":"custom_emoji","offset":0,"length":2,"custom_emoji_id":"5352858062157783478"},
    {"type":"bold","offset":3,"length":15},
    {"type":"custom_emoji","offset":56,"length":2,"custom_emoji_id":"5890939368956237177"},
    {"type":"custom_emoji","offset":79,"length":2,"custom_emoji_id":"5967378280607652101"},
    {"type":"custom_emoji","offset":90,"length":2,"custom_emoji_id":"6032994772321309200"},
    {"type":"custom_emoji","offset":108,"length":2,"custom_emoji_id":"5888630540566796058"},
]


# ---- دليل الأوامر: رسالة واحدة بالإيموجي المميز (قابلة للتعديل من إدارة الشات) ----
_GUIDE_P1 = ("👑أولاً | أوامر مالك المجموعة\n\n• رفع / تنزيل مشرف .\n• رفع / تنزيل تاجر . \n• إضافة كارت مالك.\n\n"
             "━━━━━━━━━━━━━━━━━━\n🛡ثانياً | أوامر الإدارة والمشرفين\n\n• حظر و تقييد وكتم الاعضاء .\n"
             "• إلغاء التقييد و الغاء الكتم .\n• رفع القيود\n• إضافة كارت مشرف.\n━━━━━━━━━━━━━━━━━━\n"
             "⭐ثالثاً | العضو المميز\n\n• رفع / تنزيل  مميز.\n\n• كتم / إلغاء الكتم.\n• تقييد / إلغاء التقييد.\n\n"
             "━━━━━━━━━━━━━━━━━━")
_GUIDE_P2 = ("📣 رابعاً | الاشتراك الإجباري\n\n• تفعيل الاشتراك .\n• تعطيل الاشتراك . \n\n━━━━━━━━━━━━━━━━━━\n"
             "🧠خامساً | نظام الذكاء الاصطناعي AI\n\nتفاعل مع البوت باستخدام الأوامر الذكية:\n• عرب نام \n• عرب اصحى \n\n"
             "━━━━━━━━━━━━━━━━━━\n🔓سادساً | فك القيود الجماعي\n\n• براءه يا رجاله\n\n"
             "يُستخدم الأمر لرفع القيود عن جميع أعضاء المجموعة دفعة واحدة.\n\n━━━━━━━━━━━━━━━━━━\n"
             "🚨سابعاً | نظام الحماية الأمنية\n\nبمجرد إضافة البوت إلى مجموعتك، يبدأ نظام الحماية في مراقبة بيانات الأعضاء "
             "ومطابقتها مع القائمة السوداء وارسال تنبيه فورا فحاله وجد بيانات مذكورة\n━━━━━━━━━━━━━━━━━━\n"
             "𓆩 👑 𓆪 عــــرب | إدارة وحماية باحترافية")
_GUIDE_E1 = [(0,2,"c","5229011542011299168"),(2,27,"b"),(31,20,"b"),(52,21,"b"),(74,18,"b"),(94,18,"b"),
             (113,2,"c","6032679573261392503"),(115,32,"b"),(149,28,"b"),(178,31,"b"),(210,12,"b"),(223,18,"b"),
             (242,18,"b"),(261,1,"c","6033034380509714973"),(262,21,"b"),(285,20,"b"),(307,20,"b"),(328,24,"b"),(354,18,"b")]
_GUIDE_E2 = [(0,2,"c","6035273840882358819"),(2,27,"b"),(31,18,"b"),(50,19,"b"),(71,18,"b"),
             (90,2,"c","5226639745106330551"),(92,33,"b"),(127,39,"b"),(167,10,"b"),(178,11,"b"),(191,18,"b"),
             (210,2,"c","5291873529464122510"),(212,26,"b"),(240,16,"b"),(258,60,"b"),(320,18,"b"),
             (339,2,"c","5395695537687123235"),(341,29,"b"),(372,144,"b"),(517,18,"b"),(536,3,"b"),(539,2,"b"),
             (539,2,"c","6035136547957774577"),(541,36,"b")]
DEFAULT_CMD_GUIDE = _GUIDE_P1 + "\n" + _GUIDE_P2
_GUIDE_SHIFT = len(_GUIDE_P1.encode("utf-16-le")) // 2 + 1
CMD_GUIDE_ENTITIES = (
    [{"type": "custom_emoji" if e[2] == "c" else "bold", "offset": e[0], "length": e[1],
      **({"custom_emoji_id": e[3]} if e[2] == "c" else {})} for e in _GUIDE_E1]
    + [{"type": "custom_emoji" if e[2] == "c" else "bold", "offset": e[0] + _GUIDE_SHIFT, "length": e[1],
        **({"custom_emoji_id": e[3]} if e[2] == "c" else {})} for e in _GUIDE_E2])

def entity_objects(items):
    out = []
    for item in items or []:
        allowed = {k:item[k] for k in ("type","offset","length","url","custom_emoji_id","language") if k in item and item[k] is not None}
        try: out.append(MessageEntity(**allowed))
        except (TypeError, ValueError): continue
    return out

MSG_CFG_CACHE = {}
MSG_CFG_TTL = 30

async def get_message_config(kind):
    # Short in-memory cache: avoids a Redis round trip on every /start, search and group warning.
    cached = MSG_CFG_CACHE.get(kind)
    if cached and time.time() - cached[0] < MSG_CFG_TTL:
        return cached[1]
    saved = await db.getj("message_config:" + kind)
    if saved and isinstance(saved.get("text"), str):
        result = saved
    else:
        defaults = {"welcome":{"text":DEFAULT_WELCOME,"entities":WELCOME_ENTITIES},
                    "help":{"text":DEFAULT_HELP,"entities":HELP_ENTITIES},
                    "group_warning":{"text":DEFAULT_GROUP_WARNING,"entities":[]},
                    "search_guide":{"text":DEFAULT_SEARCH_GUIDE,"entities":[]},
                    "cmd_guide":{"text":DEFAULT_CMD_GUIDE,"entities":CMD_GUIDE_ENTITIES}}
        result = defaults[kind]
    MSG_CFG_CACHE[kind] = (time.time(), result)
    return result

def replace_reason_placeholder(text, entities, reason):
    marker = "{reason}"
    if marker not in text:
        return text, entities
    replacement = reason or "بلاغ منشور في قناة البلاغات"
    start_char = text.index(marker)
    start_u16 = len(text[:start_char].encode("utf-16-le")) // 2
    end_u16 = start_u16 + len(marker.encode("utf-16-le")) // 2
    delta = (len(replacement.encode("utf-16-le")) - len(marker.encode("utf-16-le"))) // 2
    adjusted = []
    for original in entities or []:
        item = dict(original)
        if item.get("offset", 0) >= end_u16:
            item["offset"] = item["offset"] + delta
        adjusted.append(item)
    return text.replace(marker, replacement, 1), adjusted

async def send_configured_message(bot, chat_id, kind, *, reply_markup=None, reply_to_message_id=None, reason=None):
    cfg = await get_message_config(kind)
    body = cfg["text"]
    entities = cfg.get("entities", [])
    return await bot.send_message(chat_id=chat_id, text=body, entities=entity_objects(entities),
                                  reply_markup=reply_markup, reply_to_message_id=reply_to_message_id,
                                  disable_web_page_preview=True)


# Custom emoji IDs supplied by the bot owner. Telegram inline keyboard button labels
# currently accept plain text only; these IDs are used in message text entities where supported.
CUSTOM_EMOJI = {
    "search": "5258274739041883702",
    "add_report": "5890864005165096780",
    "wallet": "5890939368956237177",
    "telegram": "5904630315946611415",
    "pubg": "5935966809655088705",
    "reason": "5879814368572478751",
    "source_url": "6028346797368283073",
    "skip": "5891251587308853180",
    "confirm": "5888604607554262373",
    "owner": "5891000366081775168",
    "admin": "5404739128199766189",
    "addgroup": "6206375377925839184",
    "help": "5776121926627888870",
}


def two_column_rows(buttons):
    """Arrange buttons two per row."""
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

def back_button(callback_data="back_home"):
    # Telegram custom emoji IDs are not supported in inline button text; retain the requested symbol as text.
    return make_button("🔙 العودة", callback_data=callback_data, style="primary")

def nav_back(callback_data="admin_open"):
    """Back button used inside admin sections: blue, no emoji."""
    return make_button("العودة", callback_data=callback_data, style="primary")

async def edit_or_send(message, text, *, reply_markup=None, entities=None, parse_mode=None, disable_web_page_preview=True):
    """Edit the current bot UI message; only send a new one if editing is impossible."""
    kwargs = {"text": text, "reply_markup": reply_markup, "disable_web_page_preview": disable_web_page_preview}
    if entities is not None: kwargs["entities"] = entities
    if parse_mode is not None: kwargs["parse_mode"] = parse_mode
    try:
        return await message.edit_text(**kwargs)
    except TelegramError:
        return await message.reply_text(**kwargs)

def make_button(text, *, callback_data=None, url=None, style=None, emoji_key=None):
    """Create an inline button while only passing fields supported by installed PTB.

    Keep style/emoji metadata at call sites so the original button design remains
    represented. Older python-telegram-bot versions do not accept these optional
    fields, so never send unknown fields through api_kwargs (which can break Bot API
    requests). Where the installed library explicitly supports them, pass them.
    """
    kwargs = {"text": text}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    try:
        supported = inspect.signature(InlineKeyboardButton).parameters
    except (TypeError, ValueError):
        supported = {}
    if style in {"primary", "success", "danger"} and "style" in supported:
        kwargs["style"] = style
    emoji_id = CUSTOM_EMOJI.get(emoji_key) if emoji_key else None
    if emoji_id and "icon_custom_emoji_id" in supported:
        kwargs["icon_custom_emoji_id"] = str(emoji_id)
    return InlineKeyboardButton(**kwargs)


class RedisREST:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15, headers={"Authorization": f"Bearer {REDIS_TOKEN}"})
    async def cmd(self, *args):
        last_exc = None
        for attempt in range(3):
            try:
                r = await self.client.post(REDIS_URL, json=list(args))
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Connection never reached Redis, so retrying is safe even for writes.
                last_exc = exc
                await asyncio.sleep(0.5 * (attempt + 1))
        else:
            raise last_exc
        r.raise_for_status()
        d = r.json()
        if d.get("error"): raise RuntimeError(d["error"])
        return d.get("result")
    async def getj(self, key):
        raw = await self.cmd("GET", key)
        return json.loads(raw) if raw else None
    async def setj(self, key, value):
        await self.cmd("SET", key, json.dumps(value, ensure_ascii=False))
    async def close(self): await self.client.aclose()

db = None

def norm(s):
    s = (s or "").casefold().replace("ـ", "")
    s = re.sub(r"[\u064b-\u065f\u0670]", "", s)
    return re.sub(r"\s+", " ", s).strip()

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'«»]+|(?<![\w@./-])(?:t\.me|telegram\.me|telegram\.dog)/[^\s<>\"'«»]+", re.I)
_PHONE_RE = re.compile(r"(?<!\d)(?:(?:\+|00)?20[\s-]*|0)1[0125](?:[\s-]*\d){8}(?!\d)")
_USER_RE = re.compile(r"(?<![\w@/.])@([A-Za-z][A-Za-z0-9_]{3,31})(?!\w)")
_ID_RE = re.compile(r"(?<![\d.])\d{6,20}(?!\d)")
_LABELED_PATTERNS = [
    r"(?:pubg\s*id|id\s*ببجي|ايدي\s*ببجي|ايدى\s*ببجي|معرف\s*ببجي)\s*[:：=\-]?\s*([a-z0-9_-]{4,24})",
    r"(?:username|user\s*name|اسم\s*اللاعب|اليوزر|يوزر)\s*[:：=\-]?\s*@?([a-z0-9_.-]{3,32})",
]

def normalize_url(u):
    """Canonical form of a full link (scheme/www/trailing slash/case ignored, nothing else)."""
    u = u.strip().rstrip(".,;:!?)]}»،؛'\"")
    u = re.sub(r"^(?:https?://)?(?:www\.)?", "", u, flags=re.I).split("#")[0].rstrip("/")
    return u.lower()

def extract_keys(text, strict=False):
    """Identifiers only: full links, @usernames, numeric IDs (6-20 digits) and Egyptian 01x phone numbers.

    Every key must match a stored key EXACTLY. Ordinary words are never keys.
    strict=False (used when indexing reports) additionally reads labelled fields such as
    "PUBG ID: abc123" or "يوزر: name"; strict=True (used for user messages/searches) does not.
    """
    raw = (text or "").translate(_AR_DIGITS)
    keys = set()
    for m in _URL_RE.finditer(raw):
        nu = normalize_url(m.group(0))
        if len(nu) >= 5:
            keys.add("url:" + nu)
        pm = re.fullmatch(r"(?:t\.me|telegram\.me|telegram\.dog)/@?([a-z][a-z0-9_]{3,31})(?:\?.*)?", nu)
        if pm:
            keys.add(pm.group(1))
    rest = _URL_RE.sub(" ", raw)
    for m in _PHONE_RE.finditer(rest):
        keys.add("0" + re.sub(r"\D", "", m.group(0))[-10:])
    keys.update(m.group(1).lower() for m in _USER_RE.finditer(rest))
    keys.update(_ID_RE.findall(rest))
    if not strict:
        n = norm(rest)
        for p in _LABELED_PATTERNS:
            keys.update(x.strip("@.,:;()[]{}") for x in re.findall(p, n, re.I))
    return {x for x in keys if len(x) >= 3}

async def is_admin(uid):
    return uid in OWNER_IDS or bool(await db.cmd("SISMEMBER", "admins", str(uid)))

def normalize_reference(value):
    return re.sub(r"[^A-Z0-9-]", "", (value or "").strip().upper())

async def save_report(report):
    rid = report["id"]
    existing = await db.getj("report:" + rid)
    if existing and existing.get("reference_id"):
        report["reference_id"] = existing["reference_id"]
    elif not report.get("reference_id"):
        seq = await db.cmd("INCR", "reports:reference_counter")
        report["reference_id"] = f"XR-{int(seq):06d}"
    ref = normalize_reference(report["reference_id"])
    await db.setj("report:" + rid, report)
    await db.cmd("SADD", "reports:all", rid)
    await db.cmd("SET", "reference:" + ref, rid)
    for key in report.get("keys", []):
        await db.cmd("SADD", "index:" + key, rid)

def report_key_set(report):
    return extract_keys(report.get("text", ""))

async def find_reports_by_keys(keys, limit=SEARCH_RESULTS_LIMIT):
    """Reports that contain at least one of the given identifiers, matched exactly."""
    keys = {k for k in keys if k}
    if not keys: return []
    # Independent Redis lookups run in parallel instead of one after another.
    key_list = list(keys)[:20]
    ids = set()
    for members in await asyncio.gather(*(db.cmd("SMEMBERS", "index:" + key) for key in key_list)):
        ids.update(members or [])
    found = []
    candidates = await asyncio.gather(*(db.getj("report:" + rid) for rid in list(ids)[:200]))
    for r in candidates:
        if r and keys & report_key_set(r):
            found.append(r)
    found.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return found[:limit]

async def find_reports(query, limit=SEARCH_RESULTS_LIMIT, kind=None):
    q = norm(query)
    if not q: return []
    ref = normalize_reference(q)
    if re.fullmatch(r"[A-Z]{2}-\d{1,12}", ref):
        rid = await db.cmd("GET", "reference:" + ref)
        if rid:
            report = await db.getj("report:" + rid)
            return [report] if report else []
        # Also match a reference in legacy data if the reverse index is absent.
        for rid in await db.cmd("SMEMBERS", "reports:all") or []:
            report = await db.getj("report:" + rid)
            if report and normalize_reference(report.get("reference_id")) == ref:
                await db.cmd("SET", "reference:" + ref, rid)
                return [report]
        return []
    if kind == "telegram_id":
        d = q.translate(_AR_DIGITS).strip()
        keys = {d} if d.isdigit() else set()
    elif kind == "pubg":
        t = q.translate(_AR_DIGITS).strip()
        keys = {t} if re.fullmatch(r"[a-z0-9_-]{4,24}", t) else extract_keys(q, strict=True)
    elif kind == "telegram":
        keys = extract_keys(q if ("@" in q or "/" in q) else "@" + q, strict=True)
    else:
        keys = extract_keys(q, strict=True)
    return await find_reports_by_keys(keys, limit)

def source_url(report):
    return report.get("source_url")

def keyboard_for(report):
    url = source_url(report)
    return InlineKeyboardMarkup([[make_button("اذهب للرسالة الأصلية", url=url, style="success", emoji_key="source_url")]]) if url else None

def format_report(r, i=1):
    # Public-facing search responses intentionally never expose report reasons or source text.
    return "⚠️ تحذير: توجد بلاغات مسجلة تطابق البيانات التي تبحث عنها.\nتحقّق من التفاصيل؛ البلاغ وحده ليس حكمًا نهائيًا."

def source_channel_url():
    """Return a clickable public Telegram channel URL from SOURCE_CHANNEL."""
    channel = (SOURCE_CHANNEL or "@Nsabin3").strip()
    if channel.startswith(("https://t.me/", "http://t.me/")):
        return channel
    if channel.startswith("@"):
        channel = channel[1:]
    # A numeric channel ID is not a public username and cannot form a t.me link.
    if channel and not channel.lstrip("-").isdigit():
        return f"https://t.me/{channel}"
    return "https://t.me/Nsabin3"


_BOT_USERNAME = ""

def add_to_group_url():
    return f"https://t.me/{_BOT_USERNAME}?startgroup=true" if _BOT_USERNAME else "https://t.me/"

async def home_keyboard(uid):
    rows = [
        [make_button("أضفني إلى مجموعتك", url=add_to_group_url(), style="success", emoji_key="addgroup")],
        [make_button("كشف نصاب", callback_data="search", style="primary", emoji_key="search"),
         make_button("دليل الأوامر", callback_data="cmd_guide", style="primary")],
        [make_button("قناة البلاغات", url=source_channel_url(), style="primary", emoji_key="source_url"),
         make_button("تواصل مع المالك", url=f"tg://user?id={8121013255}", style="primary", emoji_key="owner")],
    ]
    if uid in OWNER_IDS:
        rows.append([make_button("لوحة الإدارة", callback_data="admin_open", style="primary", emoji_key="admin")])
    return InlineKeyboardMarkup(rows)

async def forced_sub_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«الاشتراك الإجباري»: واجهة فقط حالياً، مفيش وظيفة بعد."""
    await update.callback_query.answer()

def replace_name_placeholder(text, entities, name):
    """Replace {name} (also {الاسم}/{اسم}) with the user's name and keep every entity offset correct (UTF-16)."""
    import re as _re
    pat = _re.compile(r"\{(?:name|الاسم|اسم)\}", _re.I)
    matches = list(pat.finditer(text))
    if not matches:
        return text, entities
    def u16(x): return len(x.encode("utf-16-le")) // 2
    occ = []   # (start_u16, end_u16, delta)
    for m in matches:
        a = u16(text[:m.start()])
        occ.append((a, a + u16(m.group(0)), u16(name) - u16(m.group(0))))
    adjusted = []
    for original in entities or []:
        item = dict(original)
        off = item.get("offset", 0)
        end = off + item.get("length", 0)
        new_off = off + sum(d for (_a, b, d) in occ if b <= off)
        new_end = end + sum(d for (_a, b, d) in occ if b <= end)
        item["offset"], item["length"] = new_off, max(0, new_end - new_off)
        adjusted.append(item)
    return pat.sub(lambda _m: name, text), adjusted

def render_welcome(cfg, user):
    name = (getattr(user, "first_name", None) or getattr(user, "full_name", None) or "عزيزي").strip()
    text, ents = replace_name_placeholder(cfg["text"], cfg.get("entities", []), name)
    return text, entity_objects(ents)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _BOT_USERNAME
    _BOT_USERNAME = context.bot.username or _BOT_USERNAME
    uid = update.effective_user.id if update.effective_user else 0
    cfg = await get_message_config("welcome")
    w_text, w_ents = render_welcome(cfg, update.effective_user)
    msg = await update.effective_message.reply_text(w_text, entities=w_ents, reply_markup=await home_keyboard(uid))
    context.user_data["ui_chat_id"] = msg.chat_id
    context.user_data["ui_message_id"] = msg.message_id

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = await get_message_config("help")
    await update.effective_message.reply_text(cfg["text"], entities=entity_objects(cfg.get("entities", [])), reply_markup=InlineKeyboardMarkup([[back_button()]]))

async def button_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["ui_chat_id"] = q.message.chat_id
    context.user_data["ui_message_id"] = q.message.message_id
    if q.data == "back_home":
        global _BOT_USERNAME
        _BOT_USERNAME = context.bot.username or _BOT_USERNAME
        cfg = await get_message_config("welcome")
        w_text, w_ents = render_welcome(cfg, q.from_user)
        await edit_or_send(q.message, w_text, entities=w_ents, reply_markup=await home_keyboard(q.from_user.id))
        return ConversationHandler.END
    if q.data == "help":
        cfg = await get_message_config("help")
        await edit_or_send(q.message, cfg["text"], entities=entity_objects(cfg.get("entities", [])), reply_markup=InlineKeyboardMarkup([[back_button()]]))
        return ConversationHandler.END
    if q.data == "admin_open":
        await admin_panel(update, context)
        return ConversationHandler.END
    if q.data == "scam_open":
        await scam_open(update, context)
        return ConversationHandler.END
    kb_buttons = [
        make_button("رقم المحفظة / الكاش", callback_data="search_cash", style="success", emoji_key="wallet"),
        make_button("البحث بـ PUBG ID", callback_data="search_pubg", style="primary", emoji_key="pubg"),
        make_button("يوزر تيليجرام", callback_data="search_tg", style="primary", emoji_key="telegram"),
        make_button("البحث بـ Telegram ID", callback_data="search_tgid", style="primary", emoji_key="telegram"),
        make_button("البحث بالرقم المرجعي", callback_data="search_ref", style="primary", emoji_key="search"),
        back_button(),
    ]
    guide = await get_message_config("search_guide")
    await edit_or_send(q.message, guide["text"] + "\n\n🔍 اختر طريقة الكشف:", entities=entity_objects(guide.get("entities", [])), reply_markup=InlineKeyboardMarkup(two_column_rows(kb_buttons)))
    return ConversationHandler.END

async def choose_search_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mapping = {
        "search_cash": ("cash", "💳 أرسل رقم المحفظة أو الكاش المراد البحث عنه."),
        "search_pubg": ("pubg", "🎮 أرسل PUBG ID المراد البحث عنه."),
        "search_tg": ("telegram", "👤 أرسل اسم مستخدم تيليجرام، مع @ أو من غيرها."),
        "search_tgid": ("telegram_id", "🆔 أرسل Telegram ID الرقمي المراد البحث عنه."),
        "search_ref": ("reference", "🆔 أرسل الرقم المرجعي للبلاغ، مثال: XR-000001"),
    }
    kind, prompt = mapping[q.data]
    context.user_data["search_type"] = kind
    context.user_data["ui_chat_id"] = q.message.chat_id
    context.user_data["ui_message_id"] = q.message.message_id
    await edit_or_send(q.message, prompt, reply_markup=InlineKeyboardMarkup([[back_button("search")]]))
    return SEARCH

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # The user's query is a real chat message. Search results must be a NEW bot
    # message replying to that query; only navigation/menu screens are edited.
    user_message = update.effective_message
    query = (user_message.text or "").strip()
    kind = context.user_data.pop("search_type", "general")
    if kind == "telegram":
        query = query.lstrip("@")
    if kind == "telegram_id":
        query = query.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).strip()
        if not query.isdigit():
            await user_message.reply_text("أرسل Telegram ID رقميًا فقط.", reply_to_message_id=user_message.message_id)
            return ConversationHandler.END
    if kind == "reference":
        query = normalize_reference(query)

    results = await find_reports(query, kind=kind)
    if not results:
        text = "🔎 لم أجد بلاغًا مطابقًا في قاعدة البيانات الحالية. هذا لا يعني أن الشخص مضمون أو آمن."
        await user_message.reply_text(text, reply_to_message_id=user_message.message_id)
    else:
        cfg = await get_message_config("group_warning")
        r = results[0]
        await user_message.reply_text(
            cfg["text"],
            entities=entity_objects(cfg.get("entities", [])),
            reply_markup=keyboard_for(r),
            reply_to_message_id=user_message.message_id,
            disable_web_page_preview=True,
        )

    # Restore the search-method menu by editing the existing bot UI message,
    # so the user can run another search without accumulating menu messages.
    ui_chat_id = context.user_data.get("ui_chat_id")
    ui_message_id = context.user_data.get("ui_message_id")
    if ui_chat_id and ui_message_id:
        guide = await get_message_config("search_guide")
        kb_buttons = [
            make_button("رقم المحفظة / الكاش", callback_data="search_cash", style="success", emoji_key="wallet"),
            make_button("البحث بـ PUBG ID", callback_data="search_pubg", style="primary", emoji_key="pubg"),
            make_button("يوزر تيليجرام", callback_data="search_tg", style="primary", emoji_key="telegram"),
            make_button("البحث بـ Telegram ID", callback_data="search_tgid", style="primary", emoji_key="telegram"),
            make_button("البحث بالرقم المرجعي", callback_data="search_ref", style="primary", emoji_key="search"),
            back_button(),
        ]
        try:
            await context.bot.edit_message_text(
                chat_id=ui_chat_id,
                message_id=ui_message_id,
                text=guide["text"] + "\n\n🔍 اختر طريقة الكشف:",
                entities=entity_objects(guide.get("entities", [])),
                reply_markup=InlineKeyboardMarkup(two_column_rows(kb_buttons)),
                disable_web_page_preview=True,
            )
        except TelegramError:
            log.debug("Could not refresh search menu after results", exc_info=True)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("تم الإلغاء.")
    return ConversationHandler.END

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.effective_message.reply_text("الأمر متاح للمشرفين المصرح لهم فقط."); return
    buttons = [
        make_button("قسم النصابين", callback_data="scam_open", style="primary"),
        make_button("كروت التجار والمشرفين", callback_data="chatmgmt_open", style="primary"),
        make_button("إدارة الشات", callback_data="botcmds_open", style="primary"),
        make_button("الاشتراك الإجباري", callback_data="fsubsec_open", style="primary"),
    ]
    if update.effective_user.id in OWNER_IDS:
        buttons += [
            make_button("إدارة البوت", callback_data="botadmin_open", style="primary"),
            make_button("حماية الحظر العشوائي", callback_data="antiraid_open", style="primary"),
            make_button("ذكاء البوت (AI)", callback_data="ai:open", style="primary"),
        ]
    buttons.append(nav_back("back_home"))
    rows = two_column_rows(buttons)
    if update.callback_query:
        await edit_or_send(update.callback_query.message, "لوحة الإدارة:", reply_markup=InlineKeyboardMarkup(rows))
    else:
        await update.effective_message.reply_text("لوحة الإدارة:", reply_markup=InlineKeyboardMarkup(rows))

async def scam_open(update, context):
    """Admin section: everything related to scam reports."""
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("الأمر متاح للمشرفين المصرح لهم فقط."); return
    buttons = [
        make_button("إضافة بلاغ", callback_data="add_report", style="primary"),
        make_button("حذف بلاغ", callback_data="delete_report_menu", style="primary"),
        make_button("عدد البلاغات", callback_data="count", style="primary"),
    ]
    if q.from_user.id in OWNER_IDS:
        buttons += [
            make_button("تعديل شرح الاستخدام", callback_data="editmsg:help", style="primary"),
            make_button("تعديل شرح البحث", callback_data="editmsg:search_guide", style="primary"),
            make_button("تعديل تحذير الجروب", callback_data="editmsg:group_warning", style="primary"),
        ]
    buttons.append(nav_back("admin_open"))
    await edit_or_send(q.message, "قسم النصابين:", reply_markup=InlineKeyboardMarkup(two_column_rows(buttons)))

async def botadmin_open(update, context):
    """Owner section: bot administration (welcome message + admins)."""
    q = update.callback_query
    await q.answer()
    if q.from_user.id not in OWNER_IDS:
        await q.message.reply_text("القسم ده للمالك فقط."); return
    buttons = [
        make_button("تعديل رسالة الترحيب", callback_data="editmsg:welcome", style="primary"),
        make_button("إضافة مشرف", callback_data="add_admin", style="primary"),
        make_button("حذف مشرف", callback_data="del_admin", style="primary"),
        make_button("عرض المشرفين", callback_data="list_admins", style="primary"),
        make_button("إذاعة", callback_data="bc:open", style="primary"),
        nav_back("admin_open"),
    ]
    await edit_or_send(q.message, "إدارة البوت:", reply_markup=InlineKeyboardMarkup(two_column_rows(buttons)))

def reference_label(report):
    return report.get("reference_id") or report["id"][:8]

async def delete_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the newest reports labelled by reference number. Returns True when the menu was shown."""
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("غير مصرح لك بحذف البلاغات.")
        return False
    ids = await db.cmd("SMEMBERS", "reports:all") or []
    reports = []
    for rid in ids:
        report = await db.getj("report:" + rid)
        if report:
            reports.append(report)
    reports.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    if not reports:
        await q.message.reply_text("لا توجد بلاغات محفوظة لحذفها.")
        return False
    buttons = []
    for r in reports[:20]:
        buttons.append(make_button(reference_label(r), callback_data="delete_report:" + r["id"], style="primary"))
    buttons.append(nav_back("scam_open"))
    await q.message.reply_text("🗑 أرسل الرقم المرجعي للبلاغ المراد حذفه (مثال: XR-000001)، أو اختر من القائمة (أحدث 20 بلاغ):\n"
                               "اكتب /cancel للإلغاء.", reply_markup=InlineKeyboardMarkup(two_column_rows(buttons)))
    return True

async def perform_report_delete(bot, rid):
    """Delete a report, its indexes and (best effort) its original channel post. Returns (report, channel_deleted)."""
    report = await db.getj("report:" + rid)
    if not report:
        return None, False
    # Remove all search indexes before deleting the record.
    for key in set(report.get("keys", [])) | report_key_set(report):
        await db.cmd("SREM", "index:" + key, rid)
    await db.cmd("SREM", "reports:all", rid)
    if report.get("reference_id"):
        await db.cmd("DEL", "reference:" + normalize_reference(report["reference_id"]))
    await db.cmd("DEL", "report:" + rid)
    channel_deleted = False
    if report.get("source_chat") and report.get("source_message_id"):
        try:
            await bot.delete_message(chat_id=report["source_chat"], message_id=int(report["source_message_id"]))
            channel_deleted = True
        except TelegramError as exc:
            log.info("Could not delete source message for report %s: %s", rid, exc)
    return report, channel_deleted

def deleted_text(report, channel_deleted):
    ref = reference_label(report)
    return (f"تم حذف البلاغ {ref} من قاعدة بيانات البوت وفهارس البحث." +
            (" وتم حذف الرسالة الأصلية من القناة." if channel_deleted else " لم يتم حذف الرسالة الأصلية (قد تكون محذوفة بالفعل أو لا يملك البوت صلاحية حذفها)."))

async def delete_report_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("غير مصرح لك بحذف البلاغات.")
        return
    rid = q.data.split(":", 1)[1]
    report, channel_deleted = await perform_report_delete(context.bot, rid)
    if not report:
        await q.message.reply_text("البلاغ غير موجود أو حُذف بالفعل.")
        return
    await q.message.reply_text(deleted_text(report, channel_deleted))

async def delete_report_by_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sent a reference number (XR-000001, or just 1) while the delete menu was open."""
    msg = update.effective_message
    if not await is_admin(update.effective_user.id):
        await msg.reply_text("غير مصرح لك بحذف البلاغات.")
        return ConversationHandler.END
    text = (msg.text or "").strip().translate(_AR_DIGITS)
    ref = normalize_reference(text)
    if ref.isdigit():
        ref = f"XR-{int(ref):06d}"
    rid = await db.cmd("GET", "reference:" + ref) if ref else None
    if not rid and ref:
        for cand in await db.cmd("SMEMBERS", "reports:all") or []:
            report = await db.getj("report:" + cand)
            if report and normalize_reference(report.get("reference_id")) == ref:
                rid = cand
                break
    if not rid:
        await msg.reply_text("ما لقيتش بلاغ بالرقم المرجعي ده. أرسل رقمًا صحيحًا مثل XR-000001 أو اختر من القائمة، أو اكتب /cancel.")
        return DELETE_REPORTS
    report, channel_deleted = await perform_report_delete(context.bot, rid)
    if not report:
        await msg.reply_text("البلاغ غير موجود أو حُذف بالفعل.")
        return ConversationHandler.END
    await msg.reply_text(deleted_text(report, channel_deleted))
    return ConversationHandler.END

async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; data = q.data
    if not await is_admin(uid):
        await q.message.reply_text("غير مصرح لك باستخدام لوحة الإدارة."); return ConversationHandler.END
    if data == "delete_report_menu":
        shown = await delete_report_menu(update, context)
        return DELETE_REPORTS if shown else ConversationHandler.END
    if data.startswith("delete_report:"):
        await delete_report_action(update, context); return ConversationHandler.END
    if data == "count":
        count = await db.cmd("SCARD", "reports:all")
        await q.message.reply_text(f"عدد البلاغات: {count or 0}"); return ConversationHandler.END
    if data == "list_admins":
        admins = await db.cmd("SMEMBERS", "admins") or []
        owner_txt = "، ".join(str(i) for i in sorted(OWNER_IDS))
        await q.message.reply_text("المشرفون الإضافيون:\n" + ("\n".join(sorted(admins)) if admins else "لا يوجد") +
                                   f"\n\nمالك البوت (الوحيد): {owner_txt}\n(محدد في متغير OWNER_IDS)."); return ConversationHandler.END
    if data.startswith("editmsg:"):
        if uid not in OWNER_IDS:
            await q.message.reply_text("تعديل الرسائل متاح للمالك فقط."); return ConversationHandler.END
        kind = data.split(":", 1)[1]
        labels = {"welcome":"رسالة الترحيب","help":"رسالة طريقة الاستخدام","group_warning":"رسالة التحذير في الجروب والبوت","search_guide":"شرح طرق البحث","cmd_guide":"دليل الأوامر"}
        if kind not in labels:
            await q.message.reply_text("نوع الرسالة غير معروف."); return ConversationHandler.END
        context.user_data["editing_message_kind"] = kind
        if kind == "welcome":
            await q.message.reply_text("تلميح: اكتب {name} في أي مكان في الرسالة وهيتبدل باسم الشخص اللي دوس ستارت "
                                       "(مثال: مرحباً بك يا {name}).")
        await q.message.reply_text(f"أرسل الآن {labels[kind]} الجديدة في رسالة واحدة.\n\nيمكنك إرسال نص عادي أو نسخ رسالة تحتوي على Custom Emoji مميز؛ سأحفظ النص والـ entities كما وصلت.\nاكتب /cancel للإلغاء.")
        return EDIT_MESSAGE
    if data in ("add_admin","del_admin") and uid not in OWNER_IDS:
        await q.message.reply_text("المالكان فقط يقدران يضيفوا أو يحذفوا مشرفين."); return ConversationHandler.END
    context.user_data["admin_action"] = data
    if data == "add_report":
        for key in ("new_report_cash", "new_report_username", "new_report_pubg",
                    "new_report_reason", "new_report_source_url"):
            context.user_data.pop(key, None)
        await q.message.reply_text(
            "😢 <b>إضافة بلاغ يدوي</b>\nأرسل رقم المحفظة / الكاش، أو اكتب «تخطي» لو مش متوفر.",
            parse_mode="HTML")
        return REPORT_TEXT
    await q.message.reply_text("أرسلي Telegram ID الرقمي للمستخدم.")
    return ADMIN_ID

def report_step_skipped(value):
    return (value or "").strip().casefold() in {"تخطي", "تخطى", "skip", "-", "none", "لا يوجد", "غير متوفر", "غير محدد", "غير محدده"}


async def add_report_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    value = (msg.text or "").strip()
    if not report_step_skipped(value):
        context.user_data["new_report_cash"] = value
    await msg.reply_text("👤 أرسل يوزر تيليجرام، أو اكتب «تخطي» لو مش متوفر.")
    return REPORT_USERNAME


async def add_report_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    value = (msg.text or "").strip()
    if not report_step_skipped(value):
        match = re.fullmatch(r"@?([A-Za-z][A-Za-z0-9_]{3,31})", value)
        if not match:
            await msg.reply_text("اليوزر غير صحيح. أرسله بالشكل @username أو اكتب «تخطي».")
            return REPORT_USERNAME
        context.user_data["new_report_username"] = "@" + match.group(1)
    await msg.reply_text("🎮 أرسل PUBG ID، أو اكتب «تخطي» لو مش متوفر.")
    return REPORT_PUBG


async def add_report_pubg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    value = (msg.text or "").strip()
    if not report_step_skipped(value):
        value = value.translate(_AR_DIGITS)
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,24}", value):
            await msg.reply_text("PUBG ID غير صحيح. أرسل المعرّف أو اكتب «تخطي».")
            return REPORT_PUBG
        context.user_data["new_report_pubg"] = value
    await msg.reply_text("📝 أرسل سبب البلاغ، أو اكتب «تخطي» ليُسجَّل السبب: موجود في قناة البلاغات.")
    return REPORT_REASON


async def add_report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.effective_message.reply_text("غير مصرح.")
        return ConversationHandler.END
    value = (update.effective_message.text or "").strip()
    context.user_data["new_report_reason"] = (
        "موجود في قناة البلاغات" if report_step_skipped(value) else value
    )
    kb = InlineKeyboardMarkup([[make_button("تخطي الرابط", callback_data="report_url_skip", style="primary")]])
    await update.effective_message.reply_text(
        "✈️ ابعت رابط رسالة البلاغ الأصلية في القناة أو الجروب، أو اضغط تخطي.",
        reply_markup=kb)
    return REPORT_URL


def build_manual_report_body(context):
    parts = []
    cash = context.user_data.pop("new_report_cash", None)
    username = context.user_data.pop("new_report_username", None)
    pubg = context.user_data.pop("new_report_pubg", None)
    if cash:
        parts.append("رقم المحفظة / الكاش: " + cash)
    if username:
        parts.append("يوزر تيليجرام: " + username)
    if pubg:
        parts.append("PUBG ID: " + pubg)
    return "\n".join(parts)


def parse_source_message_link(url):
    value = (url or "").strip().split("?", 1)[0].rstrip("/")
    private = re.fullmatch(r"https?://t\.me/c/(\d+)/(\d+)", value, re.I)
    if private:
        return -int("100" + private.group(1)), int(private.group(2))
    public = re.fullmatch(r"https?://t\.me/([A-Za-z0-9_]{4,32})/(\d+)", value, re.I)
    if public:
        return "@" + public.group(1), int(public.group(2))
    return None, None


async def save_manual_report(uid, context, reply_message):
    body = build_manual_report_body(context)
    reason = context.user_data.pop("new_report_reason", "موجود في قناة البلاغات")
    url = context.user_data.pop("new_report_source_url", None)
    keys = sorted(extract_keys(body))
    if not keys:
        await reply_message.reply_text("لازم تضيف معرف واحد على الأقل: رقم كاش أو يوزر تيليجرام أو PUBG ID. لم يتم حفظ البلاغ.")
        return ConversationHandler.END
    source_chat, source_message_id = parse_source_message_link(url)
    rid = hashlib.sha256(f"manual:{uid}:{body}:{reason}:{url}:{time.time()}".encode()).hexdigest()[:20]
    await save_report({
        "id": rid, "text": body, "reason": reason, "keys": keys, "source_url": url,
        "source_chat": source_chat, "source_message_id": source_message_id,
        "custom_emoji_entities": [], "created_at": int(time.time()), "added_by": uid,
    })
    await reply_message.reply_text(
        "✅ تم حفظ البلاغ." + (" زر فتح الرسالة الأصلية جاهز." if url else " لم يُضف زر الرسالة الأصلية لعدم وجود رابط."),
        reply_markup=keyboard_for({"source_url": url}))
    return ConversationHandler.END


async def add_report_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    url = (msg.text or "").strip()
    if not re.match(r"^https?://t\.me/", url):
        await msg.reply_text("الرابط غير واضح. أرسل رابطًا يبدأ بـ https://t.me/ أو اضغط تخطي.")
        return REPORT_URL
    context.user_data["new_report_source_url"] = url
    return await save_manual_report(update.effective_user.id, context, msg)


async def skip_report_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["new_report_source_url"] = None
    return await save_manual_report(q.from_user.id, context, q.message)


async def edit_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.effective_message
    if uid not in OWNER_IDS:
        await msg.reply_text("تعديل الرسائل متاح للمالك فقط.")
        return ConversationHandler.END
    kind = context.user_data.pop("editing_message_kind", None)
    if kind not in {"welcome", "help", "group_warning", "search_guide", "cmd_guide"}:
        await msg.reply_text("انتهت جلسة التعديل. افتح لوحة الإدارة وابدأ من جديد.")
        return ConversationHandler.END
    body = (msg.text or msg.caption or "").strip()
    if not body:
        await msg.reply_text("الرسالة فارغة. افتح لوحة الإدارة وحاول مرة أخرى.")
        return ConversationHandler.END
    source_entities = msg.entities or msg.caption_entities or []
    entities = []
    for e in source_entities:
        item = {"type": e.type, "offset": e.offset, "length": e.length}
        for attr in ("custom_emoji_id", "url", "language"):
            value = getattr(e, attr, None)
            if value is not None: item[attr] = value
        entities.append(item)
    await db.setj("message_config:" + kind, {"text": body, "entities": entities, "updated_by": uid, "updated_at": int(time.time())})
    MSG_CFG_CACHE.pop(kind, None)
    labels = {"welcome":"رسالة الترحيب","help":"رسالة طريقة الاستخدام","group_warning":"رسالة التحذير في الجروب والبوت","search_guide":"شرح طرق البحث","cmd_guide":"دليل الأوامر"}
    await msg.reply_text(f"✅ تم حفظ {labels[kind]} الجديدة، بما فيها الإيموجي المميز إن وُجد. ستُستخدم في الرسائل القادمة.")
    return ConversationHandler.END


async def admin_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in OWNER_IDS:
        await update.effective_message.reply_text("المالكان فقط يقدران يغيروا المشرفين."); return ConversationHandler.END
    value = (update.effective_message.text or "").strip()
    if not value.isdigit():
        await update.effective_message.reply_text("أرسلي Telegram ID رقميًا صحيحًا."); return ConversationHandler.END
    if int(value) in OWNER_IDS:
        await update.effective_message.reply_text("هذا الحساب مالك بالفعل."); return ConversationHandler.END
    action = context.user_data.pop("admin_action", "")
    if action == "add_admin":
        await db.cmd("SADD", "admins", value); msg = f"تمت إضافة المشرف {value}."
    else:
        await db.cmd("SREM", "admins", value); msg = f"تم حذف المشرف {value}."
    await update.effective_message.reply_text(msg)
    return ConversationHandler.END

async def channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle both new and edited channel posts.
    msg = update.channel_post or update.edited_channel_post
    if not msg: return
    username = msg.chat.username
    if SOURCE_CHANNEL and SOURCE_CHANNEL.lstrip("@") != (username or "") and SOURCE_CHANNEL != str(msg.chat.id):
        return
    body = (msg.text or msg.caption or "").strip()
    if not body: return
    rid = hashlib.sha256(f"{msg.chat.id}:{msg.message_id}".encode()).hexdigest()[:20]
    existing_report = await db.getj("report:" + rid)
    new_keys = sorted(extract_keys(body))
    if not new_keys:
        log.info("Channel post %s has no searchable identifiers (saved anyway)", msg.message_id)

    # On edit: drop index entries for identifiers that no longer appear in the post.
    ref_id = None
    if existing_report:
        old_keys = set(existing_report.get("keys", [])) | report_key_set(existing_report)
        for old_k in old_keys:
            if old_k not in new_keys:
                await db.cmd("SREM", "index:" + old_k, rid)
        ref_id = existing_report.get("reference_id")

    if username:
        url = f"https://t.me/{username}/{msg.message_id}"
    else:
        internal_id = str(msg.chat.id)
        internal_id = internal_id[4:] if internal_id.startswith("-100") else internal_id.lstrip("-")
        url = f"https://t.me/c/{internal_id}/{msg.message_id}" if internal_id else None
    report = {"id":rid,"text":body,"reason":"بلاغ منشور في قناة البلاغات","keys":new_keys,
              "source_url":url,"source_chat":msg.chat.id,"source_message_id":msg.message_id,
              "created_at":existing_report.get("created_at") if existing_report else int(time.time()),
              "updated_at":int(time.time())}
    if ref_id:
        report["reference_id"] = ref_id
    await save_report(report)

    if not existing_report:
        # Publish the assigned reference as a reply, only for brand-new posts.
        try:
            await context.bot.send_message(chat_id=msg.chat.id,
                text=f"🆔 الرقم المرجعي للبلاغ: {report['reference_id']}",
                reply_to_message_id=msg.message_id)
        except TelegramError as exc:
            log.info("Could not post reference reply for source message %s: %s", msg.message_id, exc)
        log.info("Indexed new source post %s as %s", msg.message_id, report['reference_id'])
    else:
        log.info("Updated edited source post %s (%s) with keys: %s", msg.message_id, report.get('reference_id'), new_keys)

async def group_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    body = msg.text or msg.caption or ""
    if not body or body.startswith("/"): return
    keys = sorted(extract_keys(body, strict=True))
    seen = set()
    for key in keys[:8]:
        for r in await find_reports_by_keys([key], limit=2):
            if r["id"] in seen: continue
            seen.add(r["id"])
            try:
                cfg = await get_message_config("group_warning")
                warning_text, warning_entities = cfg["text"], cfg.get("entities", [])
                await context.bot.send_message(chat_id=msg.chat_id, text=warning_text,
                    entities=entity_objects(warning_entities), reply_to_message_id=msg.message_id,
                    reply_markup=keyboard_for(r), disable_web_page_preview=True)
            except TelegramError as e: log.warning("Could not warn in group: %s", e)
            if len(seen) >= 2: return

# ====================================================================
# Group auto-replies: an admin writes "اضف زر" in a group to add a keyword reply
# (with or without a link button). Fully isolated: registered in handler group 1,
# so it never blocks or changes the existing handlers in group 0.
# ====================================================================
GR_TRIGGERS = {"اضف زر", "اضافه زر", "اضف رد", "اضافه رد"}
GR_ADMIN_TRIGGERS = {"اضف رد مشرف", "اضافه رد مشرف"}
GR_DELETE_TRIGGERS = {"مسح زر", "مسح رد"}
GR_ADMIN_DELETE_TRIGGERS = {"مسح رد مشرف"}
GR_LIST_TRIGGERS = {"الردود"}
GR_ANON_ADMIN_ID = 1087968824          # Telegram's "GroupAnonymousBot"
GR_FLOW_TTL = 900                      # seconds before an unfinished flow expires
GR_CACHE_TTL = 30
GR_COOLDOWN = 3                        # seconds between the same reply in the same chat
GR_MAX_KEYWORDS = 50
GR_CACHE = {}
GR_LAST_SENT = {}
GR_MEDIA_METHODS = {
    "photo": ("send_photo", "photo"), "video": ("send_video", "video"),
    "animation": ("send_animation", "animation"), "document": ("send_document", "document"),
    "audio": ("send_audio", "audio"), "voice": ("send_voice", "voice"),
    "video_note": ("send_video_note", "video_note"), "sticker": ("send_sticker", "sticker"),
}
GR_NO_CAPTION = {"video_note", "sticker"}


def gr_n(s):
    s = norm(s)
    return s.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))

def gr_serialize_entities(entities):
    out = []
    for e in entities or []:
        if e.type == "text_mention":
            continue
        item = {"type": e.type, "offset": e.offset, "length": e.length}
        for attr in ("custom_emoji_id", "url", "language"):
            value = getattr(e, attr, None)
            if value is not None:
                item[attr] = value
        out.append(item)
    return out

def gr_extract(msg):
    """Return the reply content (text/caption + entities + media) from any message type."""
    media_type = file_id = None
    if msg.animation: media_type, file_id = "animation", msg.animation.file_id
    elif msg.photo: media_type, file_id = "photo", msg.photo[-1].file_id
    elif msg.video: media_type, file_id = "video", msg.video.file_id
    elif msg.voice: media_type, file_id = "voice", msg.voice.file_id
    elif msg.audio: media_type, file_id = "audio", msg.audio.file_id
    elif msg.video_note: media_type, file_id = "video_note", msg.video_note.file_id
    elif msg.sticker: media_type, file_id = "sticker", msg.sticker.file_id
    elif msg.document: media_type, file_id = "document", msg.document.file_id
    text = (msg.text or msg.caption or "").strip()
    entities = msg.entities if msg.text else msg.caption_entities
    if not text and not media_type:
        return None
    return {"text": text, "entities": gr_serialize_entities(entities), "media_type": media_type, "file_id": file_id}

def gr_parse_url(value):
    value = (value or "").strip()
    if re.fullmatch(r"(?:https?|tg)://\S+", value, re.I):
        return value
    if re.fullmatch(r"@[A-Za-z0-9_]{4,32}", value):
        return "https://t.me/" + value[1:]
    if re.fullmatch(r"(?:t\.me|www\.)\S+", value, re.I):
        return "https://" + value
    return None

def gr_parse_keywords(text):
    seen, out = set(), []
    for line in (text or "").splitlines():
        k = gr_n(line)
        if k and len(k) <= 100 and k not in seen:
            seen.add(k); out.append(k)
    return out[:GR_MAX_KEYWORDS]

async def gr_load(chat_id):
    now = time.time()
    cached = GR_CACHE.get(chat_id)
    if cached and now - cached[0] < GR_CACHE_TTL:
        return cached[1]
    items = await db.getj(f"group_replies:{chat_id}") or []
    GR_CACHE[chat_id] = (now, items)
    return items

async def gr_add(chat_id, item):
    items = await db.getj(f"group_replies:{chat_id}") or []
    items.append(item)
    await db.setj(f"group_replies:{chat_id}", items)
    GR_CACHE.pop(chat_id, None)

async def gr_is_group_admin(bot, chat_id, user_id):
    if user_id in OWNER_IDS:
        return True
    member = await gr_member(bot, chat_id, user_id)
    return bool(member and member.status in ("administrator", "creator"))

async def gr_bot_is_admin(bot, chat_id):
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False

def gr_markup(item, with_icon=True):
    if item.get("kind") != "button" or not item.get("button_url"):
        return None
    style = item.get("button_style") or "primary"
    icon = item.get("button_icon") if with_icon else None
    if icon:
        # Same mechanism as the rest of the bot: make_button + CUSTOM_EMOJI lookup -> icon_custom_emoji_id.
        key = "gr_icon_" + str(icon)
        CUSTOM_EMOJI[key] = str(icon)
        btn = make_button(item.get("button_text") or "\u200b", url=item["button_url"], style=style, emoji_key=key)
    else:
        btn = make_button(item.get("button_text_full") or item.get("button_text") or "فتح", url=item["button_url"], style=style)
    return InlineKeyboardMarkup([[btn]])

async def gr_send(bot, chat_id, reply_to, item):
    attempts = (True, False) if item.get("button_icon") else (True,)
    for with_icon in attempts:
        try:
            markup = gr_markup(item, with_icon)
            common = {"chat_id": chat_id, "reply_markup": markup}
            if reply_to:
                common["reply_to_message_id"] = reply_to
            text = item.get("text", "")
            ents = entity_objects(item.get("entities"))
            media_type = item.get("media_type")
            if not media_type:
                return await bot.send_message(text=text, entities=ents, disable_web_page_preview=True, **common)
            method, field = GR_MEDIA_METHODS[media_type]
            extra = {field: item["file_id"]}
            if media_type not in GR_NO_CAPTION and text:
                extra["caption"] = text
                extra["caption_entities"] = ents
            return await getattr(bot, method)(**extra, **common)
        except TelegramError as exc:
            log.warning("Group reply send failed (icon=%s): %s", with_icon, exc)
    return None

def gr_flows(context):
    return context.chat_data.setdefault("gr_flows", {})

KEYWORDS_PROMPT = ("🔑 أرسل الكلمات المفتاحية.\n"
                   "تقدر ترسل كلمة أو أكثر، كل كلمة (أو جملة من كلمتين أو ثلاث) في سطر منفصل.\n\n"
                   "للإلغاء اكتب: إلغاء")
TEXT_PROMPT = ("📝 أرسل الآن نص الرد الذي سيظهر.\n"
               "يقبل النص بكل أنواعه والإيموجي المميز، وكل أنواع الميديا (صورة، فيديو، متحركة، ملف، صوت، فويس، ملصق...).")

async def gr_start(update, context, admin_only=False):
    msg, chat = update.effective_message, update.effective_chat
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    ukey = GR_ANON_ADMIN_ID if anonymous else (msg.from_user.id if msg.from_user else 0)
    if not anonymous and not await gr_is_group_admin(context.bot, chat.id, ukey):
        return
    if not await gr_bot_is_admin(context.bot, chat.id):
        await msg.reply_text("لازم ترفعني أدمن في الجروب عشان ميزة الردود تشتغل.")
        return
    gr_flows(context)[ukey] = {"step": "choose", "ts": time.time(),
                               "admin_only": bool(admin_only)}
    kb = InlineKeyboardMarkup([
        [make_button("رد بزر تفاعلي", callback_data=f"gr:kind:button:{ukey}", style="primary"),
         make_button("رد بدون زر", callback_data=f"gr:kind:plain:{ukey}", style="success")],
        [make_button("إلغاء", callback_data=f"gr:cancel:x:{ukey}", style="danger")],
    ])
    title = "اختر نوع رد المشرفين الذي تريد إضافته:" if admin_only else "اختر نوع الرد الذي تريد إضافته:"
    await msg.reply_text(title, reply_markup=kb)

async def gr_delete_start(update, context, admin_only=False):
    msg, chat = update.effective_message, update.effective_chat
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    ukey = GR_ANON_ADMIN_ID if anonymous else (msg.from_user.id if msg.from_user else 0)
    if not anonymous and not await gr_is_group_admin(context.bot, chat.id, ukey):
        return
    gr_flows(context)[ukey] = {"step": "delete", "ts": time.time(),
                               "admin_only": bool(admin_only)}
    target_label = "رد المشرفين" if admin_only else "الرد"
    await msg.reply_text(f"🗑 أرسل الكلمة المفتاحية (أو أي كلمة من كلمات {target_label}) لمسح {target_label}.\n"
                         "لو للرد أكثر من كلمة مفتاحية، تُمسح كلها معه.\n\nللإلغاء اكتب: إلغاء")

async def gr_callback(update, context):
    q = update.callback_query
    parts = q.data.split(":")
    try:
        action, value, owner = parts[1], parts[2], int(parts[3])
    except (IndexError, ValueError):
        await q.answer(); return
    uid = q.from_user.id
    allowed = uid == owner or (owner == GR_ANON_ADMIN_ID and await gr_is_group_admin(context.bot, q.message.chat_id, uid))
    if not allowed:
        await q.answer("هذا الزر ليس لك.", show_alert=True); return
    flows = gr_flows(context)
    flow = flows.get(owner)
    await q.answer()
    if action == "cancel":
        flows.pop(owner, None)
        try: await q.message.edit_text("تم الإلغاء.")
        except TelegramError: pass
        return
    if action == "ccolor":
        if flow and flow.get("step") == "card_color" and value in COLOR_VALUES:
            await card_color_finish(q, context, flow, owner, value)
        return
    if action == "color":
        if flow and flow.get("step") == "button_color" and value in {"danger", "primary", "success"}:
            flow["button_style"] = value
            try: await q.message.edit_text("🎨 تم اختيار لون الزر.")
            except TelegramError: pass
            await gr_finish(q.message, context, flow, owner)
        return
    if not flow or flow.get("step") != "choose":
        try: await q.message.edit_text("انتهت الجلسة. اكتب «اضف زر» من جديد.")
        except TelegramError: pass
        return
    flow.update({"kind": value, "step": "keywords", "ts": time.time()})
    try: await q.message.edit_text(KEYWORDS_PROMPT)
    except TelegramError: await q.message.reply_text(KEYWORDS_PROMPT)

def gr_color_keyboard(owner):
    return InlineKeyboardMarkup([[
        make_button("🔴 أحمر", callback_data=f"gr:color:danger:{owner}", style="danger"),
        make_button("🔵 أزرق", callback_data=f"gr:color:primary:{owner}", style="primary"),
        make_button("🟢 أخضر", callback_data=f"gr:color:success:{owner}", style="success"),
    ]])

async def gr_finish(msg, context, flow, owner):
    item = {
        "id": hashlib.sha256(f"{msg.chat_id}:{owner}:{time.time()}".encode()).hexdigest()[:12],
        "kind": flow["kind"], "keywords": flow["keywords"],
        "text": flow["text"], "entities": flow["entities"],
        "media_type": flow["media_type"], "file_id": flow["file_id"],
        "button_text": flow.get("button_text"), "button_text_full": flow.get("button_text_full"),
        "button_icon": flow.get("button_icon"), "button_url": flow.get("button_url"),
        "button_style": flow.get("button_style"),
        "created_by": owner, "created_at": int(time.time()),
        # Missing audience means legacy/public reply, preserving existing data.
        "audience": "admins" if flow.get("admin_only") else "all",
    }
    await gr_add(msg.chat_id, item)
    gr_flows(context).pop(owner, None)
    await msg.reply_text(f"✅ تم حفظ الرد. سيرد البوت عند ظهور أي من الكلمات المفتاحية ({len(item['keywords'])}). هذه معاينة:")
    await gr_send(context.bot, msg.chat_id, msg.message_id, item)

async def gr_flow_step(update, context, flow, owner):
    msg = update.effective_message
    step = flow["step"]
    flow["ts"] = time.time()
    if step == "choose":
        await msg.reply_text("اختر نوع الرد من الأزرار أعلاه، أو اكتب: إلغاء"); return
    if step in ("mod_user", "mod_word", "mod_photo", "card_color"):
        await mod_flow_step(update, context, flow, owner); return
    if step == "delete":
        kw = gr_n(msg.text or "")
        if not kw:
            await msg.reply_text("أرسل الكلمة المفتاحية كنص."); return
        items = await db.getj(f"group_replies:{msg.chat_id}") or []
        wanted_audience = "admins" if flow.get("admin_only") else "all"
        target = next((it for it in items if kw in it.get("keywords", [])
                       and ("admins" if it.get("audience") == "admins" else "all") == wanted_audience), None)
        if not target:
            await msg.reply_text("ما لقيتش رد بالكلمة دي. جرّب كلمة تانية أو اكتب: إلغاء"); return
        items = [it for it in items if it["id"] != target["id"]]
        await db.setj(f"group_replies:{msg.chat_id}", items)
        GR_CACHE.pop(msg.chat_id, None)
        gr_flows(context).pop(owner, None)
        deleted_label = "رد المشرفين" if wanted_audience == "admins" else "الرد"
        await msg.reply_text(f"✅ تم مسح {deleted_label} وكل كلماته المفتاحية ({len(target.get('keywords', []))}).")
        return
    if step == "keywords":
        kws = gr_parse_keywords(msg.text)
        if not kws:
            await msg.reply_text("أرسل كلمة واحدة على الأقل في رسالة نصية، كل كلمة في سطر."); return
        flow["keywords"], flow["step"] = kws, "text"
        await msg.reply_text(TEXT_PROMPT); return
    if step == "text":
        content = gr_extract(msg)
        if not content:
            await msg.reply_text("نوع الرسالة غير مدعوم. أرسل نصًا أو ميديا."); return
        limit = 1024 if content["media_type"] else 4096
        if len(content["text"]) > limit:
            await msg.reply_text(f"النص طويل جدًا. الحد الأقصى {limit} حرفًا."); return
        flow.update(content)
        if flow["kind"] == "plain":
            await gr_finish(msg, context, flow, owner); return
        flow["step"] = "button_name"
        await msg.reply_text("🔘 أرسل الآن اسم الزر (يقبل الإيموجي المميز)."); return
    if step == "button_name":
        name = (msg.text or "").strip()
        if not name or len(name) > 64:
            await msg.reply_text("أرسل اسم الزر كنص (حتى 64 حرفًا)."); return
        icon, text_only = None, name
        try: supported = inspect.signature(InlineKeyboardButton).parameters
        except (TypeError, ValueError): supported = {}
        ces = [e for e in (msg.entities or []) if e.type == "custom_emoji"]
        if ces:
            if "icon_custom_emoji_id" not in supported:
                await msg.reply_text("⚠️ نسخة python-telegram-bot المثبتة لا تدعم الإيموجي المميز في الأزرار، حدّثها (pip install -U python-telegram-bot) وإلا سيظهر الإيموجي العادي.")
            else:
                units = msg.text.encode("utf-16-le")
                drop = set()
                for e in ces:
                    drop.update(range(e.offset, e.offset + e.length))
                keep = bytearray()
                for i in range(len(units) // 2):
                    if i not in drop:
                        keep += units[2 * i:2 * i + 2]
                text_only = re.sub(r"\s+", " ", keep.decode("utf-16-le", errors="ignore")).strip()
                icon = ces[0].custom_emoji_id
        flow.update({"button_text": text_only, "button_text_full": name, "button_icon": icon, "step": "button_url"})
        await msg.reply_text("🔗 أرسل الآن الرابط الذي سيفتحه الزر."); return
    if step == "button_url":
        url = gr_parse_url(msg.text)
        if not url:
            await msg.reply_text("الرابط غير صحيح. أرسل رابطًا يبدأ بـ https:// أو @username."); return
        flow["button_url"], flow["step"] = url, "button_color"
        await msg.reply_text("🎨 اختر لون الزر:", reply_markup=gr_color_keyboard(owner)); return
    if step == "button_color":
        await msg.reply_text("اختر لون الزر من الأزرار أعلاه، أو اكتب: إلغاء")

async def gr_list_replies(update, context):
    msg, chat = update.effective_message, update.effective_chat
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    uid = GR_ANON_ADMIN_ID if anonymous else (msg.from_user.id if msg.from_user else 0)
    if not anonymous and not await gr_is_group_admin(context.bot, chat.id, uid):
        return
    items = await gr_load(chat.id)
    if not items:
        await msg.reply_text("لا توجد ردود محفوظة في هذه المجموعة حاليًا.")
        return
    lines = ["📋 ردود هذه المجموعة:", ""]
    for index, item in enumerate(items, 1):
        audience = "مشرفين فقط" if item.get("audience") == "admins" else "الجميع"
        kind = "بزر" if item.get("kind") == "button" else "نصي"
        keywords = "، ".join(item.get("keywords", [])) or "بدون كلمات"
        lines.append(f"{index}) {keywords} — {kind} — {audience}")
    chunks, current = [], ""
    for line in "\n".join(lines).splitlines():
        candidate = (current + "\n" + line).strip()
        if len(candidate) > 3900 and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for chunk in chunks:
        await msg.reply_text(chunk)


async def gr_try_reply(update, context):
    msg, chat = update.effective_message, update.effective_chat
    body = msg.text or msg.caption or ""
    if not body or body.startswith("/"):
        return
    items = await gr_load(chat.id)
    if not items:
        return
    nb = gr_n(body)
    for item in items:
        if nb in item.get("keywords", []):
            # Admin-only replies are silent for ordinary members.
            if item.get("audience") == "admins":
                uid = msg.from_user.id if msg.from_user else 0
                anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
                if anonymous or not await gr_is_group_admin(context.bot, chat.id, uid):
                    continue
            key = (chat.id, item["id"])
            now = time.time()
            if now - GR_LAST_SENT.get(key, 0) < GR_COOLDOWN:
                return True
            GR_LAST_SENT[key] = now
            await gr_send(context.bot, chat.id, msg.message_id, item)
            return True

# ====================================================================
# Chat management: approved traders, moderators ("مشرف") and owners ("مالك") per chat,
# editable global card templates, per-person contact-button colour, and the private
# "إدارة الشات" admin section. Every chat has its own lists (nothing is shared between chats).
# ====================================================================
TR_CACHE = {}
TR_LAST_SENT = {}
TR_COOLDOWN = 10
TR_LIST_TRIGGERS = {"التجار", "المضمونين", "مضمونين"}
TR_REMOVE_WORDS = {"حذف", "مسح", "تنزيل"}
GR_MOD_TRIGGERS = {"اضف مشرف", "اضافه مشرف"}
GR_OWNER_TRIGGERS = {"اضف مالك", "اضافه مالك"}
ROLE_CACHE = {}
ROLE_LAST_SENT = {}
ROLE_COOLDOWN = 10
TPL_CACHE = {}
ROLES = {
    "mod": {"key": "group_mods", "n": "مشرف", "dn": "المشرف", "rank": "ADMIN",
            "desc": "مشرف وضامن معتمد داخل الشات، المعاملة والوساطة معاه بأمان تام "},
    "owner": {"key": "group_owners", "n": "مالك", "dn": "المالك", "rank": "OWNER",
              "desc": "مالك وضامن معتمد داخل الشات، المعاملة والوساطة معاه بأمان تام "},
}
TPL_LABELS = {"mod": "رسالة المشرفين", "owner": "رسالة المالك", "trader": "رسالة التجار المضمونين"}
TPL_VARS = {"mod": "{username} ← يوزر المشرف\n{link} ← رابط التواصل الدائم",
            "owner": "{username} ← يوزر المالك\n{link} ← رابط التواصل الدائم",
            "trader": "{username} ← يوزر التاجر\n{limit} ← مبلغ الضمان"}
TR_E_SHIELD = "5891225499677496831"
TR_E_CROWN = "5875344888165308204"
TR_E_WARN = "5253768790067406491"
TR_E_STOP = "5890787894049643800"
TR_E_USER = "5445092669522996408"
TR_E_CHECK = "5891235511246264255"
TR_E_MONEY = "5872935716454930968"
E_MOD_DONE, E_DOT = "5812288471837975057", "5891103002915247305"
EM_SHIELD, EM_CROWN, EM_WARN = "\U0001F6E1️", "\U0001F451", "‼️"
EM_STOP, EM_USER, EM_CHECK = "⛔", "\U0001F464", "✔️"
EM_CAL, EM_MONEY, EM_ALERT = "\U0001F4C5", "\U0001F911", "⚠️"
EM_DOT, EM_100, EM_DIAMOND = "⏺", "\U0001F4AF", "\U0001F539"
CANCEL_LINE = "(أو اكتب إلغاء للتراجع)"
COLOR_VALUES = {"danger", "primary", "success", "none"}


def S(text, *styles, e=None):
    return (text, styles, e)

def tm_build(segments):
    """Build (text, entities) with correct UTF-16 offsets from segments."""
    text, ents, pos = "", [], 0
    for t, styles, emoji in segments:
        n = len(t.encode("utf-16-le")) // 2
        if t:
            for st in styles:
                ents.append({"type": st, "offset": pos, "length": n})
            if emoji:
                ents.append({"type": "custom_emoji", "offset": pos, "length": n, "custom_emoji_id": emoji})
        text += t
        pos += n
    return text, ents

def tr_today():
    from datetime import datetime, timezone, timedelta
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Cairo")
    except Exception:
        tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime("%Y-%m-%d")

# ---------- button colour ----------
def color_kb(cb):
    """Four colour choices; cb(style) -> callback_data. 'none' = transparent (default) button."""
    return InlineKeyboardMarkup([
        [make_button("🔴 أحمر", callback_data=cb("danger"), style="danger"),
         make_button("🔵 أزرق", callback_data=cb("primary"), style="primary")],
        [make_button("🟢 أخضر", callback_data=cb("success"), style="success"),
         make_button("⚪ شفاف", callback_data=cb("none"))],
    ])

def card_style(item, default):
    v = item.get("button_style", default)
    return None if v in (None, "none") else v

# ---------- editable templates ----------
def tpl_default(kind):
    if kind == "cmd_raid":
        return raid_default()
    if kind in CMD_DEFAULTS:
        return CMD_DEFAULTS[kind], []
    if kind == "trader":
        return tm_build([
            S(EM_SHIELD, e=TR_E_SHIELD), S(" "), S("تـاجـر مـعـتـمـد ومـضـمـون", "bold"), S(" "), S(EM_SHIELD, e=TR_E_SHIELD),
            S("\n" + "━" * 18 + "\n\n"),
            S(EM_CROWN, e=TR_E_CROWN), S(" "), S("الـيـوزر:", "bold"), S(" "), S("{username}", "mention"),
            S("\n\n─── ⋆⋅☆⋅⋆ ───\n\n"),
            S(EM_SHIELD, e=TR_E_SHIELD), S(" "), S("مـضـمـون بـحـد أقـصـى:", "bold"), S(" "), S("{limit} جنيه", "bold"),
            S("\n\n" + "━" * 18 + "\n"),
            S(EM_WARN, e=TR_E_WARN), S(" "), S("اتأكد من فتح المحادثة عبر زر التواصل منعاً للمنتحلين.", "bold"),
            S("\n\n"),
            S(EM_STOP, e=TR_E_STOP), S(" "), S("إخلاء مسؤولية:", "bold"),
            S(" إدارة الشات تضمن هذا التاجر في حدود مبلغ ({limit} ج) الموضح أعلاه فقط، وغير مسؤولين عن أي مبلغ يتجاوز هذا المبلغ نهائياً."),
        ])
    r = ROLES[kind]
    return tm_build([
        S(EM_SHIELD, e=TR_E_SHIELD), S(" "), S(r["rank"], "bold"), S(" "), S(EM_SHIELD, e=TR_E_SHIELD),
        S("\n" + "━" * 20 + "\n\n" + r["desc"]),
        S(EM_CHECK, e=TR_E_CHECK),
        S("\n\n" + EM_DIAMOND + " "), S(f"يوزر {r['dn']}:", "bold"), S(" "), S("{username}", "mention"),
        S("\n" + EM_DIAMOND + " "), S("الرابط الدائم:", "bold"), S("\n"), S("{link}", "url"),
        S("\n\n" + "━" * 20 + "\n"),
        S(EM_STOP, e=TR_E_STOP), S(" "), S("غير مسئولين عن أي يوزر تاني لو اتعاملت مع منتحل.", "bold"),
    ])

async def tpl_get(kind):
    now = time.time()
    cached = TPL_CACHE.get(kind)
    if cached and now - cached[0] < GR_CACHE_TTL:
        return cached[1]
    saved = await db.getj("tpl:" + kind)
    tpl = (saved["text"], saved.get("entities", [])) if saved and isinstance(saved.get("text"), str) else tpl_default(kind)
    TPL_CACHE[kind] = (now, tpl)
    return tpl

def tpl_render(text, entities, values, spans=None):
    """Replace {name} placeholders and shift/stretch entities (UTF-16 offsets) accordingly."""
    u16 = lambda t: len(t.encode("utf-16-le")) // 2
    reps, out, pos, cum = [], "", 0, 0
    for m in re.finditer(r"\{(\w+)\}", text):
        if m.group(1) not in values:
            continue
        repl = str(values[m.group(1)])
        old_s = u16(text[:m.start()])
        n_old, n_new = u16(m.group(0)), u16(repl)
        reps.append((old_s, old_s + n_old, n_new))
        if spans is not None and m.group(1) not in spans:
            spans[m.group(1)] = (old_s + cum, n_new)
        cum += n_new - n_old
        out += text[pos:m.start()] + repl
        pos = m.end()
    out += text[pos:]
    def mp(x, is_end):
        shift = 0
        for s, e, n in reps:
            if e <= x:
                shift += n - (e - s)
            elif s < x < e:
                return s + shift + (n if is_end else 0)
        return x + shift
    new = []
    for ent in entities or []:
        item = dict(ent)
        ns, ne = mp(ent["offset"], False), mp(ent["offset"] + ent["length"], True)
        if ne - ns > 0:
            item["offset"], item["length"] = ns, ne - ns
            new.append(item)
    return out, new

# ---------- fixed messages ----------
def tr_approval(username, limit, date):
    return tm_build([
        S(EM_SHIELD, e=TR_E_SHIELD), S(" "), S("ترقية تاجر معتمد", "bold"), S(" "), S(EM_SHIELD, e=TR_E_SHIELD),
        S("\n" + "━" * 20 + "\n\n"),
        S(EM_USER, e=TR_E_USER), S(" "), S("التاجر:", "bold"), S(" "), S("@" + username, "mention"),
        S("\n"),
        S(EM_CHECK, e=TR_E_CHECK), S(" "), S("سقف الضمان المعتمد:", "bold"), S(" "), S(f"{limit} جنيه", "bold"),
        S("\n" + EM_CAL + " "), S("تاريخ الاعتماد:", "bold"), S(f" {date}"),
        S("\n\n"),
        S("تم تسجيل التاجر وتفعيل كارت الضمان التلقائي له بنجاح لهذا الشات ", "italic"),
        S(EM_MONEY, "italic", e=TR_E_MONEY),
    ])

def tr_removal(username, date):
    return tm_build([
        S(EM_SHIELD, e=TR_E_SHIELD), S(" "), S("تنزيل تاجر", "bold"), S(" "), S(EM_SHIELD, e=TR_E_SHIELD),
        S("\n" + "━" * 20 + "\n\n"),
        S(EM_USER, e=TR_E_USER), S(" "), S("التاجر:", "bold"), S(" "), S("@" + username, "mention"),
        S("\n"),
        S(EM_CHECK, e=TR_E_CHECK), S(" "), S("تم تنزيل التاجر بنجاح", "bold"),
        S("\n" + EM_CAL + " "), S("تاريخ التنزيل:", "bold"), S(f" {date}"),
        S("\n\n"),
        S("لم يعد هذا التاجر معتمداً في هذا الشات، ولن يتم الرد على يوزره بكارت الضمان.", "italic"),
    ])

def tr_list_message(traders):
    segs = [S(EM_CROWN, e=TR_E_CROWN), S(" "), S("قائمة التجار المعتمدين داخل الشات:", "bold"),
            S("\n" + "━" * 20 + "\n")]
    for i, t in enumerate(traders, 1):
        segs += [S(f"{i}.", "bold"), S(" "), S("@" + t["username"], "mention"), S("\n   "),
                 S(EM_CHECK, e=TR_E_CHECK), S(" حد الضمان: "), S(f"{t['limit']} ج", "bold"),
                 S(f" | {EM_CAL} {t.get('date', '')}\n")]
    segs.append(S("━" * 20 + "\n" + EM_ALERT + " اتأكد دائماً من الرابط المباشر للتاجر قبل التحويل."))
    return tm_build(segs)

def role_prompt_user(role):
    r = ROLES[role]
    return tm_build([
        S(EM_SHIELD, e=TR_E_SHIELD), S(" "), S(f"إضافة كارت {r['n']} معتمد للمجموعة", "bold"),
        S("\n\nأرسل الآن "), S(f"يوزر {r['dn']}", "bold"), S(" (مثال: "), S("@username", "mention"), S("):\n"),
        S(CANCEL_LINE, "italic"),
    ])

def role_prompt_word(role, username):
    r = ROLES[role]
    return tm_build([
        S(EM_CHECK, e=TR_E_CHECK), S(" "), S("تم تحديد اليوزر:", "bold"), S(" "), S("@" + username, "mention"),
        S("\n\nأرسل الآن "), S(f"اسم {r['dn']} أو كلمة الرد بالشات", "bold"), S(" (مثال: أحمد، دراجون، زكا):\n"),
        S("(ليتم إرسال الكارت فور كتابة هذا الاسم بالشات أيضاً)", "italic"), S("\n"),
        S(CANCEL_LINE, "italic"),
    ])

def role_prompt_photo(role, word):
    r = ROLES[role]
    return tm_build([
        S(EM_CHECK, e=TR_E_CHECK), S(" "), S("تم تسجيل كلمة الرد:", "bold"), S(" « "), S(word, "code"), S(" »\n\nأرسل الآن "),
        S(f"صورة كارت {r['dn']} المعتمدة", "bold"), S(" ليتم حفظ الكارت وتفعيله فوراً:\n"),
        S(CANCEL_LINE, "italic"),
    ])

def role_done(role, username, word):
    rank = ROLES[role]["rank"]
    return tm_build([
        S(EM_100, e=E_MOD_DONE), S(" "), S(f"تم إنشاء كارت {rank} بنجاح في هذا الشات!", "bold"),
        S("\n" + "━" * 20 + "\n\n"),
        S(EM_DOT, e=E_DOT), S(" "), S("اليوزر:", "bold"), S(" "), S("@" + username, "mention"), S("\n"),
        S(EM_DOT, e=E_DOT), S(" "), S("كلمة الرد / الاسم:", "bold"), S(f" {word}\n"),
        S(EM_DOT, e=E_DOT), S(" "), S("الرتبة:", "bold"), S(f" {rank}\n\n"),
        S("ينزل الكارت الرسمي وزر التواصل كلما كُتب اليوزر أو الاسم بالشات.", "italic"),
    ])

# ---------- storage ----------
async def tr_load(chat_id, fresh=False):
    now = time.time()
    cached = TR_CACHE.get(chat_id)
    if cached and not fresh and now - cached[0] < GR_CACHE_TTL:
        return cached[1]
    items = await db.getj(f"group_traders:{chat_id}") or []
    TR_CACHE[chat_id] = (now, items)
    return items

async def tr_save(chat_id, items):
    await db.setj(f"group_traders:{chat_id}", items)
    TR_CACHE.pop(chat_id, None)

async def role_load(role, chat_id, fresh=False):
    now = time.time()
    cached = ROLE_CACHE.get((role, chat_id))
    if cached and not fresh and now - cached[0] < GR_CACHE_TTL:
        return cached[1]
    items = await db.getj(f"{ROLES[role]['key']}:{chat_id}") or []
    ROLE_CACHE[(role, chat_id)] = (now, items)
    return items

async def role_save(role, chat_id, items):
    await db.setj(f"{ROLES[role]['key']}:{chat_id}", items)
    ROLE_CACHE.pop((role, chat_id), None)

def tr_parse(rest):
    """Return (username, limit) from the text after the command; either may be None."""
    rest = (rest or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    um = re.search(r"@([A-Za-z0-9_]{4,32})", rest) or re.search(r"(?<![\w@])([A-Za-z][A-Za-z0-9_]{3,31})", rest)
    username = um.group(1) if um else None
    remaining = rest[:um.start()] + " " + rest[um.end():] if um else rest
    am = re.search(r"\d+", remaining)
    return username, (int(am.group(0)) if am else None)

async def tr_send(bot, chat_id, reply_to, text, ents, markup=None):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, entities=entity_objects(ents),
                                      reply_to_message_id=reply_to, reply_markup=markup,
                                      disable_web_page_preview=True)
    except TelegramError as exc:
        log.warning("Message send failed: %s", exc)
        return None

async def tr_commit(bot, chat_id, reply_to, username, limit, style, added_by):
    date = tr_today()
    items = [t for t in await tr_load(chat_id, fresh=True) if t["username"].lower() != username.lower()]
    items.append({"username": username, "limit": limit, "date": date, "added_by": added_by, "button_style": style})
    await tr_save(chat_id, items)
    body, ents = tr_approval(username, limit, date)
    return await tr_send(bot, chat_id, reply_to, body, ents)

# ---------- group commands: traders ----------
async def tr_command(update, context):
    """Handle رفع تاجر / تنزيل تاجر / التجار. Returns True if the message was one of these commands."""
    msg, chat = update.effective_message, update.effective_chat
    text = (msg.text or "").strip()
    if gr_n(text) in TR_LIST_TRIGGERS:
        traders = await tr_load(chat.id)
        if not traders:
            await msg.reply_text("لا يوجد تجار معتمدون في هذا الشات حتى الآن.")
        else:
            body, ents = tr_list_message(traders)
            await tr_send(context.bot, chat.id, msg.message_id, body, ents)
        return True
    tokens = text.split(None, 2)
    if len(tokens) < 2 or gr_n(tokens[1]) != "تاجر":
        return False
    verb = gr_n(tokens[0])
    is_add, is_remove = verb == "رفع", verb in TR_REMOVE_WORDS
    if not (is_add or is_remove):
        return False
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    uid = GR_ANON_ADMIN_ID if anonymous else (msg.from_user.id if msg.from_user else 0)
    if anonymous or not await gr_is_group_owner(context.bot, chat.id, uid):
        return True            # group owner only
    rest_text = tokens[2] if len(tokens) > 2 else ""
    username, limit = tr_parse(rest_text)
    reply_user = msg.reply_to_message.from_user if msg.reply_to_message else None
    if reply_user and not reply_user.is_bot and not re.search(r"@[A-Za-z0-9_]{4,32}", rest_text):
        # reply mode: "رفع تاجر 300" / "تنزيل تاجر" as a reply to the person's message
        if not reply_user.username:
            await msg.reply_text("الشخص ده ملوش يوزر نيم. اكتب يوزره بدل الريبلاي: رفع تاجر @username 300")
            return True
        username = reply_user.username
    if not username:
        await msg.reply_text("اكتب يوزر التاجر. مثال: رفع تاجر @username 300" if is_add else "اكتب يوزر التاجر. مثال: تنزيل تاجر @username")
        return True
    items = await tr_load(chat.id, fresh=True)
    existing = next((t for t in items if t["username"].lower() == username.lower()), None)
    if is_remove:
        if not existing:
            await msg.reply_text("هذا التاجر غير موجود في قائمة هذا الشات.")
        else:
            await tr_save(chat.id, [t for t in items if t is not existing])
            TR_LAST_SENT.pop((chat.id, existing["username"].lower()), None)
            body, ents = tr_removal(existing["username"], tr_today())
            await tr_send(context.bot, chat.id, msg.message_id, body, ents)
        return True
    if not limit or limit <= 0:
        await msg.reply_text("اكتب مبلغ الضمان. مثال: رفع تاجر @username 300")
        return True
    if existing:
        # Trader already approved: just update the limit and keep his button colour.
        await tr_commit(context.bot, chat.id, msg.message_id, existing["username"], limit,
                        existing.get("button_style", "success"), uid)
        return True
    gr_flows(context)[uid] = {"step": "card_color", "card": "trader", "username": username, "limit": limit, "ts": time.time()}
    await msg.reply_text("🎨 اختر لون زر التواصل للتاجر:", reply_markup=color_kb(lambda st: f"gr:ccolor:{st}:{uid}"))
    return True

async def tr_check(update, context):
    """Reply with the guarantee card when a message mentions an approved trader."""
    msg, chat = update.effective_message, update.effective_chat
    body = (msg.text or msg.caption or "").strip()
    only = re.fullmatch(r"@([A-Za-z0-9_]{4,32})", body)   # the username must be the whole message
    if not only:
        return
    traders = await tr_load(chat.id)
    if not traders:
        return
    by_name = {t["username"].lower(): t for t in traders}
    sent = 0
    for name in (only.group(1).lower(),):
        trader = by_name.get(name)
        if not trader:
            continue
        key = (chat.id, name)
        now = time.time()
        if now - TR_LAST_SENT.get(key, 0) < TR_COOLDOWN:
            continue
        TR_LAST_SENT[key] = now
        tpl_text, tpl_ents = await tpl_get("trader")
        text, ents = tpl_render(tpl_text, tpl_ents, {"username": "@" + trader["username"], "limit": trader["limit"]})
        kb = InlineKeyboardMarkup([[make_button("تواصل مع التاجر المعتمد ➜", url="https://t.me/" + trader["username"],
                                                 style=card_style(trader, "success"))]])
        await tr_send(context.bot, chat.id, msg.message_id, text, ents, kb)
        sent += 1
        if sent >= 2:
            break

# ---------- moderators / owners ----------
def mod_extract_media(msg):
    """Accept a normal photo or a GIF (animation) as the card."""
    if msg.animation:
        return ("animation", msg.animation.file_id)
    if msg.photo:
        return ("photo", msg.photo[-1].file_id)
    return None

async def mod_store(bot, chat_id, role, username, word, media, style, owner):
    user_id = None
    try:
        found = await bot.get_chat("@" + username)
        if found.type == ChatType.PRIVATE:
            user_id = found.id
    except TelegramError:
        pass
    items = [m for m in await role_load(role, chat_id, fresh=True) if m["username"].lower() != username.lower()]
    items.append({"username": username, "word": word, "media_type": media[0], "photo": media[1], "user_id": user_id,
                  "button_style": style, "added_by": owner, "date": tr_today()})
    await role_save(role, chat_id, items)

async def role_start(update, context, role):
    msg, chat = update.effective_message, update.effective_chat
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    ukey = GR_ANON_ADMIN_ID if anonymous else (msg.from_user.id if msg.from_user else 0)
    if not anonymous and not await gr_is_group_admin(context.bot, chat.id, ukey):
        return
    gr_flows(context)[ukey] = {"step": "mod_user", "role": role, "ts": time.time()}
    text, ents = role_prompt_user(role)
    await tr_send(context.bot, chat.id, msg.message_id, text, ents)

async def mod_flow_step(update, context, flow, owner):
    msg = update.effective_message
    step, role = flow["step"], flow.get("role", "mod")
    if step == "card_color":
        await msg.reply_text("اختر لون الزر من الأزرار أعلاه، أو اكتب: إلغاء"); return
    if step == "mod_user":
        m = re.search(r"@?([A-Za-z0-9_]{4,32})", msg.text or "")
        if not m:
            await msg.reply_text("أرسل اليوزر بالشكل ده: @username"); return
        flow["mod_username"], flow["step"] = m.group(1), "mod_word"
        text, ents = role_prompt_word(role, m.group(1))
        await tr_send(context.bot, msg.chat_id, msg.message_id, text, ents); return
    if step == "mod_word":
        word = (msg.text or "").strip()
        if not word or len(word) > 50 or "\n" in word:
            await msg.reply_text("أرسل الاسم أو كلمة الرد في سطر واحد (حتى 50 حرفًا)."); return
        flow["mod_word"], flow["step"] = word, "mod_photo"
        text, ents = role_prompt_photo(role, word)
        await tr_send(context.bot, msg.chat_id, msg.message_id, text, ents); return
    if step == "mod_photo":
        media = mod_extract_media(msg)
        if not media:
            await msg.reply_text("أرسل صورة أو GIF للكارت، أو اكتب إلغاء."); return
        flow["media"], flow["step"], flow["card"] = media, "card_color", role
        await msg.reply_text("🎨 اختر لون زر التواصل:", reply_markup=color_kb(lambda st: f"gr:ccolor:{st}:{owner}"))

async def card_color_finish(q, context, flow, owner, style):
    """A colour was chosen in a group flow: save the trader / moderator / owner."""
    chat_id = q.message.chat_id
    try: await q.message.edit_text("🎨 تم اختيار لون الزر.")
    except TelegramError: pass
    gr_flows(context).pop(owner, None)
    if flow.get("card") == "trader":
        await tr_commit(context.bot, chat_id, q.message.message_id, flow["username"], flow["limit"], style, owner)
        return
    role = flow["role"]
    await mod_store(context.bot, chat_id, role, flow["mod_username"], flow["mod_word"], flow["media"], style, owner)
    text, ents = role_done(role, flow["mod_username"], flow["mod_word"])
    await tr_send(context.bot, chat_id, q.message.message_id, text, ents)

async def mod_check(update, context):
    msg, chat = update.effective_message, update.effective_chat
    body = (msg.text or msg.caption or "").strip()
    if not body:
        return
    sender = msg.from_user
    only = re.fullmatch(r"@([A-Za-z0-9_]{4,32})", body)   # the username must be the whole message
    mentioned = {only.group(1).lower()} if only else set()
    nb = gr_n(body)
    for role in ("mod", "owner"):
        items = await role_load(role, chat.id)
        for item in items:
            # Learn the person's numeric id the first time he writes in the chat.
            if sender and sender.username and sender.username.lower() == item["username"].lower() and item.get("user_id") != sender.id:
                item["user_id"] = sender.id
                try:
                    fresh = await role_load(role, chat.id, fresh=True)
                    for f in fresh:
                        if f["username"].lower() == item["username"].lower():
                            f["user_id"] = sender.id
                    await role_save(role, chat.id, fresh)
                except Exception: log.info("Could not store id", exc_info=True)
            if item["username"].lower() in mentioned or nb == gr_n(item["word"]):
                key = (role, chat.id, item["username"].lower())
                now = time.time()
                if now - ROLE_LAST_SENT.get(key, 0) < ROLE_COOLDOWN:
                    return
                ROLE_LAST_SENT[key] = now
                link = f"tg://openmessage?user_id={item['user_id']}" if item.get("user_id") else f"https://t.me/{item['username']}"
                tpl_text, tpl_ents = await tpl_get(role)
                text, ents = tpl_render(tpl_text, tpl_ents, {"username": "@" + item["username"], "link": link})
                kb = InlineKeyboardMarkup([[make_button("تواصل ➜", url=f"https://t.me/{item['username']}",
                                                         style=card_style(item, "danger"))]])
                send = context.bot.send_animation if item.get("media_type") == "animation" else context.bot.send_photo
                field = "animation" if item.get("media_type") == "animation" else "photo"
                try:
                    if len(text) > 1024:
                        await send(chat_id=chat.id, reply_to_message_id=msg.message_id, **{field: item["photo"]})
                        await tr_send(context.bot, chat.id, None, text, ents, kb)
                    else:
                        await send(chat_id=chat.id, caption=text, caption_entities=entity_objects(ents),
                                   reply_to_message_id=msg.message_id, reply_markup=kb, **{field: item["photo"]})
                except TelegramError as exc:
                    log.warning("Card media failed, sending text: %s", exc)
                    await tr_send(context.bot, chat.id, msg.message_id, text, ents, kb)
                return

# ---------- private admin panel: "كروت التجار والمشرفين" ----------
def clear_priv_flows(context):
    for k in ("tra_flow", "moda_flow", "tpl_edit", "cmdadd_flow", "ar_flow", "ai_flow", "warncfg_flow", "bc", "fsub_flow"):
        context.user_data.pop(k, None)

async def chatmgmt_open(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("الأمر متاح للمشرفين المصرح لهم فقط."); return
    buttons = [
        make_button("اضافة تجار للشات", callback_data="tr_add_start", style="primary"),
        make_button("إضافة مشرفين للشات", callback_data="mod_add_start", style="primary"),
        make_button("إضافة مالك", callback_data="owner_add_start", style="primary"),
        make_button("تعديل رسالة المشرفين", callback_data="tpl_edit:mod", style="primary"),
        make_button("تعديل رسالة التجار", callback_data="tpl_edit:trader", style="primary"),
        make_button("تعديل رسالة المالك", callback_data="tpl_edit:owner", style="primary"),
        nav_back("admin_open"),
    ]
    await edit_or_send(q.message, "كروت التجار والمشرفين:", reply_markup=InlineKeyboardMarkup(two_column_rows(buttons)))

async def tra_start(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("غير مصرح لك."); return
    clear_priv_flows(context)
    context.user_data["tra_flow"] = {"step": "chat"}
    await q.message.reply_text("🛡️ أرسل يوزر القناة أو الجروب الذي تريد إضافة التاجر المعتمد فيه (مثال: @groupname أو رابط t.me).\n\nللإلغاء اكتب: إلغاء")

async def resolve_chat(bot, text):
    m = re.search(r"(?:t\.me/|@)([A-Za-z0-9_]{4,32})", text)
    target = ("@" + m.group(1)) if m else (int(text) if re.fullmatch(r"-?\d{6,}", text) else None)
    if target is None:
        return None, "أرسل يوزر الجروب مثل @groupname أو رابطه أو الـ ID الرقمي."
    try:
        return await bot.get_chat(target), None
    except TelegramError:
        return None, "ما قدرتش أوصل للجروب ده. تأكد من اليوزر وإن البوت عضو فيه، وجرّب تاني أو اكتب إلغاء."

async def tra_message(update, context):
    flow = context.user_data.get("tra_flow")
    msg = update.effective_message
    if not flow or not msg or not msg.text:
        return
    if not await is_admin(update.effective_user.id):
        context.user_data.pop("tra_flow", None); return
    text = msg.text.strip()
    if gr_n(text) == "الغاء":
        context.user_data.pop("tra_flow", None)
        await msg.reply_text("تم الإلغاء."); return
    if flow["step"] == "chat":
        chat, err = await resolve_chat(context.bot, text)
        if not chat:
            await msg.reply_text(err); return
        flow.update({"chat_id": chat.id, "chat_title": chat.title or str(chat.id), "step": "user"})
        await msg.reply_text(f"✔️ تم تحديد: {flow['chat_title']}\n\nأرسل الآن يوزر التاجر (مثال: @username)."); return
    if flow["step"] == "user":
        m = re.search(r"@?([A-Za-z0-9_]{4,32})", text)
        if not m:
            await msg.reply_text("أرسل يوزر التاجر بالشكل ده: @username"); return
        flow.update({"username": m.group(1), "step": "limit"})
        await msg.reply_text("✔️ تم تحديد اليوزر.\n\nأرسل الآن مبلغ الضمان (أرقام فقط)."); return
    if flow["step"] == "limit":
        digits = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        if not re.fullmatch(r"\d+", digits) or int(digits) <= 0:
            await msg.reply_text("أرسل مبلغ الضمان كرقم فقط، مثال: 300"); return
        flow.update({"limit": int(digits), "step": "color"})
        await msg.reply_text("🎨 اختر لون زر التواصل للتاجر:", reply_markup=color_kb(lambda st: f"pc:{st}")); return
    if flow["step"] == "color":
        await msg.reply_text("اختر لون الزر من الأزرار أعلاه، أو اكتب: إلغاء")

async def moda_start(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("غير مصرح لك."); return
    role = "owner" if q.data == "owner_add_start" else "mod"
    clear_priv_flows(context)
    context.user_data["moda_flow"] = {"step": "chat", "role": role}
    await q.message.reply_text(f"🛡️ أرسل يوزر القناة أو الجروب الذي تريد إضافة {ROLES[role]['dn']} فيه (مثال: @groupname أو رابط t.me).\n\nللإلغاء اكتب: إلغاء")

async def moda_message(update, context):
    flow = context.user_data.get("moda_flow")
    msg = update.effective_message
    if not flow or not msg:
        return
    uid = update.effective_user.id
    if not await is_admin(uid):
        context.user_data.pop("moda_flow", None); return
    role = flow["role"]
    text = (msg.text or "").strip()
    if text and gr_n(text) == "الغاء":
        context.user_data.pop("moda_flow", None)
        await msg.reply_text("تم الإلغاء."); return
    step = flow["step"]
    if step == "chat":
        chat, err = await resolve_chat(context.bot, text)
        if not chat:
            await msg.reply_text(err); return
        flow.update({"chat_id": chat.id, "chat_title": chat.title or str(chat.id), "step": "user"})
        body, ents = role_prompt_user(role)
        await tr_send(context.bot, msg.chat_id, msg.message_id, body, ents); return
    if step == "user":
        m = re.search(r"@?([A-Za-z0-9_]{4,32})", text)
        if not m:
            await msg.reply_text("أرسل اليوزر بالشكل ده: @username"); return
        flow.update({"username": m.group(1), "step": "word"})
        body, ents = role_prompt_word(role, m.group(1))
        await tr_send(context.bot, msg.chat_id, msg.message_id, body, ents); return
    if step == "word":
        if not text or len(text) > 50 or "\n" in text:
            await msg.reply_text("أرسل الاسم أو كلمة الرد في سطر واحد (حتى 50 حرفًا)."); return
        flow.update({"word": text, "step": "media"})
        body, ents = role_prompt_photo(role, text)
        await tr_send(context.bot, msg.chat_id, msg.message_id, body, ents); return
    if step == "media":
        media = mod_extract_media(msg)
        if not media:
            await msg.reply_text("أرسل صورة أو GIF للكارت، أو اكتب إلغاء."); return
        flow.update({"media": media, "step": "color"})
        await msg.reply_text("🎨 اختر لون زر التواصل:", reply_markup=color_kb(lambda st: f"pc:{st}")); return
    if step == "color":
        await msg.reply_text("اختر لون الزر من الأزرار أعلاه، أو اكتب: إلغاء")

async def pc_callback(update, context):
    """Colour chosen in a private (admin panel) flow."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    style = q.data.split(":", 1)[1]
    if style not in COLOR_VALUES or not await is_admin(uid):
        return
    flow = context.user_data.get("tra_flow")
    if flow and flow.get("step") == "color":
        context.user_data.pop("tra_flow", None)
        try: await q.message.edit_text("🎨 تم اختيار لون الزر.")
        except TelegramError: pass
        sent = await tr_commit(context.bot, flow["chat_id"], None, flow["username"], flow["limit"], style, uid)
        await q.message.reply_text(f"✅ تم رفع التاجر @{flow['username']} في «{flow['chat_title']}» بسقف {flow['limit']} جنيه." +
                                   ("" if sent else "\n⚠️ تم حفظه لكن ما قدرتش أنشر الرسالة في الجروب (تأكد إن البوت عضو ومسموح له بالإرسال)."))
        return
    flow = context.user_data.get("moda_flow")
    if flow and flow.get("step") == "color":
        context.user_data.pop("moda_flow", None)
        try: await q.message.edit_text("🎨 تم اختيار لون الزر.")
        except TelegramError: pass
        role = flow["role"]
        await mod_store(context.bot, flow["chat_id"], role, flow["username"], flow["word"], flow["media"], style, uid)
        body, ents = role_done(role, flow["username"], flow["word"])
        await tr_send(context.bot, q.message.chat_id, None, body, ents)
        await q.message.reply_text(f"تم تفعيل الكارت في «{flow['chat_title']}».")

# ---------- private admin panel: edit card templates ----------
async def tpl_edit_start(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("غير مصرح لك."); return
    kind = q.data.split(":", 1)[1]
    if kind not in TPL_LABELS:
        return
    clear_priv_flows(context)
    context.user_data["tpl_edit"] = kind
    await q.message.reply_text(
        f"✏️ أرسل الآن {TPL_LABELS[kind]} الجديدة في رسالة واحدة.\n"
        "يقبل الإيموجي المميز وكل التنسيقات (عريض، مائل، كود...).\n\n"
        f"المتغيرات اللي هتتبدل تلقائيًا:\n{TPL_VARS[kind]}\n\n"
        "التعديل بيتطبق على كل الكروت المضافة حاليًا وفي المستقبل في كل الشاتات.\n"
        "اكتب «افتراضي» لإرجاع الرسالة الأصلية، أو «إلغاء» للتراجع.")

async def tpl_message(update, context):
    kind = context.user_data.get("tpl_edit")
    msg = update.effective_message
    if not kind or not msg or not msg.text:
        return
    if not await is_admin(update.effective_user.id):
        context.user_data.pop("tpl_edit", None); return
    word = gr_n(msg.text)
    if word == "الغاء":
        context.user_data.pop("tpl_edit", None)
        await msg.reply_text("تم الإلغاء."); return
    if word == "افتراضي":
        await db.cmd("DEL", "tpl:" + kind)
        TPL_CACHE.pop(kind, None)
        context.user_data.pop("tpl_edit", None)
        await msg.reply_text(f"✅ تم إرجاع {TPL_LABELS[kind]} للشكل الأصلي."); return
    body = msg.text.strip()
    await db.setj("tpl:" + kind, {"text": msg.text, "entities": gr_serialize_entities(msg.entities),
                                  "updated_by": update.effective_user.id, "updated_at": int(time.time())})
    TPL_CACHE.pop(kind, None)
    context.user_data.pop("tpl_edit", None)
    need = TPL_NEEDS.get(kind, "{username}")
    warn = "" if (not need or need in body) else f"\n⚠️ الرسالة ما فيهاش {need}، فمش هيظهر اسم أو يوزر الشخص فيها."
    await msg.reply_text(f"✅ تم حفظ {TPL_LABELS[kind]} الجديدة، وهتظهر في كل الكروت من الآن." + warn)

# ====================================================================
# Group moderation commands: حظر / كتم / طرد / تقييد / رفع القيود / تثبيت / قفل الشات /
# فتح الشات / كشف. Targets: reply, @username or numeric ID. Optional duration (1h, 1d, 1s, 1m ...).
# Extra command words can be added from the private admin panel ("إدارة الشات").
# ====================================================================
CMD_BUILTIN = {gr_n(k): v for k, v in {
    "حظر": "ban", "كتم": "mute", "طرد": "kick", "تقييد": "tayeed",
    "رفع القيود": "unrestrict", "رفع الحظر": "unban", "الغاء الحظر": "unban", "إلغاء الحظر": "unban", "فك الحظر": "unban",
    "رفع الكتم": "unmute", "الغاء الكتم": "unmute", "إلغاء الكتم": "unmute", "فك الكتم": "unmute",
    "تثبيت": "pin", "قفل الشات": "lock", "فتح الشات": "unlock", "كشف": "kashf"}.items()}
CMD_ACTION_LABELS = {"ban": "حظر المستخدم", "mute": "كتم المستخدم", "kick": "طرد المستخدم",
                     "tayeed": "تقييد المستخدم", "unrestrict": "رفع جميع القيود",
                     "unban": "إلغاء الحظر", "unmute": "إلغاء الكتم",
                     "pin": "تثبيت رسالة", "lock": "قفل الشات", "unlock": "فتح الشات",
                     "kashf": "كشف مستخدم",
                     "unrestrict_all": "رفع القيود عن الجميع (كتم/تقييد فقط)"}
CMD_TIMED = {"ban", "mute", "kick", "tayeed"}
CMD_TPL = {"ban": "cmd_ban", "mute": "cmd_mute", "kick": "cmd_kick", "tayeed": "cmd_tayeed",
           "unrestrict": "cmd_unrestrict", "unban": "cmd_unban", "unmute": "cmd_unmute",
           "lock": "cmd_lock", "unlock": "cmd_unlock", "kashf": "cmd_kashf",
           "unrestrict_all": "cmd_unrestrict_all"}
_RLM = "‏"
CMD_DEFAULTS = {
    "cmd_ban": _RLM + "「 {name} 」 \n⇜ حظرته\n⇜ المدة: {time}\n⇜ حتى: {until}\n༄",
    "cmd_mute": _RLM + "「 {name} 」 \n⇜ كتمته\n⇜ المدة: {time}\n⇜ حتى: {until}\n༄",
    "cmd_kick": _RLM + "「 {name} 」 \n⇜ طردته\n⇜ المدة: {time}\n⇜ حتى: {until}\n༄",
    "cmd_tayeed": _RLM + "「 {name} 」 \n⇜ قيّدته\n⇜ المدة: {time}\n⇜ حتى: {until}\n༄",
    "cmd_unrestrict": _RLM + "「 {name} 」 \nرفعت القيود التالية عنه:\n{restrictions}\n༄",
    "cmd_unban": _RLM + "「 {name} 」 \n⇜ ألغيت الحظر عنه\n༄",
    "cmd_unmute": _RLM + "「 {name} 」 \n⇜ ألغيت الكتم عنه\n༄",
    "cmd_unrestrict_all": _RLM + "「 الجميع 」 \n⇜ رفعت الكتم والتقييد عنهم\n⇜ العدد: {count}\n༄",
    "cmd_lock": _RLM + "「 الشات 」 \n⇜ قفلته\n༄",
    "cmd_unlock": _RLM + "「 الشات 」 \n⇜ فتحته\n༄",
    "cmd_kashf": _RLM + "⇜ الاسم ↢ {name}\n⇜ الايدي ↢ {id}\n⇜ اليوزر ↢ {username}\n"
                 "⇜ الرتبه ↢ {rank}\n⇜ بالمجموعة ↢ {membership}\n༄\n"
                 "⇜ الصفة المعتمدة ↢ {role}\n⇜ بلاغات النصب ↢ {reports}\n⇜ الرابط ↢ {link}",
}
TPL_NEEDS = {"cmd_ban": "{name}", "cmd_mute": "{name}", "cmd_kick": "{name}", "cmd_tayeed": "{name}",
             "cmd_unrestrict": "{name}", "cmd_unban": "{name}", "cmd_unmute": "{name}",
             "cmd_lock": "", "cmd_unlock": "", "cmd_kashf": "{name}", "cmd_unrestrict_all": ""}
TPL_LABELS.update({"cmd_ban": "رسالة الحظر", "cmd_mute": "رسالة الكتم", "cmd_kick": "رسالة الطرد",
                   "cmd_tayeed": "رسالة التقييد", "cmd_unrestrict": "رسالة رفع القيود",
                   "cmd_unban": "رسالة إلغاء الحظر", "cmd_unmute": "رسالة إلغاء الكتم",
                   "cmd_lock": "رسالة قفل الشات", "cmd_unlock": "رسالة فتح الشات", "cmd_kashf": "رسالة الكشف",
                   "cmd_unrestrict_all": "رفع قيود الكل"})
_TIME_VARS = ("{name} ← اسم الشخص (قابل للضغط لفتح حسابه تلقائيًا)\n{id} ← الآيدي\n"
              "{time} ← المدة (أو «دائم»)\n{duration} ← المدة\n"
              "{until} ← وقت انتهاء المدة\n{end_time} ← وقت الانتهاء\n"
              "{action} ← نص الإجراء\n{command} ← اسم الأمر")
for _k in ("cmd_ban", "cmd_mute", "cmd_kick", "cmd_tayeed", "cmd_unrestrict", "cmd_unban", "cmd_unmute"):
    TPL_VARS[_k] = _TIME_VARS + ("\n{restrictions} ← القيود التي تم رفعها" if _k == "cmd_unrestrict" else "")
for _k in ("cmd_ban", "cmd_mute", "cmd_kick", "cmd_tayeed"):
    TPL_VARS[_k] += "\n{reason} ← السبب (اللي بتكتبه بعد المدة في الأمر)"
TPL_VARS["cmd_unrestrict_all"] = "{count} ← عدد الأشخاص اللي اترفع عنهم الكتم/التقييد"
TPL_VARS["cmd_lock"] = TPL_VARS["cmd_unlock"] = "(لا توجد متغيرات)"
TPL_VARS["cmd_kashf"] = ("{name} ← الاسم (قابل للضغط)\n{id} ← الآيدي\n{username} ← اليوزر\n"
                         "{rank} ← الرتبة داخل المجموعة\n{membership} ← الحالة داخل المجموعة (في المجموعة/طالع/محظور/مكتوم/مقيّد)\n"
                         "{status} ← الحالة (متغير قديم)\n{role} ← الصفة المعتمدة\n"
                         "{reports} ← عدد بلاغات النصب\n{link} ← رابط الحساب\n"
                         "{reason} ← سبب الحظر/الكتم الأخير (لو اتسجل)")
# ---- extra commands: real Telegram admin management (رفع مشرف / تنزيل مشرف / تنزيل الكل) ----
CMD_BUILTIN.update({gr_n(k): v for k, v in {
    "رفع مشرف": "promote", "تنزيل مشرف": "demote", "تنزيل الكل": "demote_all"}.items()})
CMD_ACTION_LABELS.update({"promote": "رفع مشرف", "demote": "تنزيل مشرف", "demote_all": "تنزيل الكل"})
CMD_TPL.update({"promote": "cmd_promote", "demote": "cmd_demote", "demote_all": "cmd_demote_all"})
CMD_DEFAULTS.update({
    "cmd_promote": _RLM + "「 {name} 」 \n⇜ رفعته مشرفاً في المجموعة\n⇜ الصلاحيات: {perms}\n༄",
    "cmd_demote": _RLM + "「 {name} 」 \n⇜ نزّلته من الإشراف\n⇜ الرتب المحذوفة من البوت:\n{ranks}\n༄",
    "cmd_demote_all": _RLM + "「 {name} 」 \n⇜ نزّلته من كل الرتب\n⇜ الرتب المحذوفة:\n{ranks}\n⇜ القيود المرفوعة: {restrictions}\n༄",
})
TPL_NEEDS.update({"cmd_promote": "{name}", "cmd_demote": "{name}", "cmd_demote_all": "{name}", "cmd_raid": "{name}"})
TPL_LABELS.update({"cmd_promote": "رسالة رفع مشرف", "cmd_demote": "رسالة تنزيل مشرف",
                   "cmd_demote_all": "رسالة تنزيل الكل", "cmd_raid": "كليشة تجريد المشرف"})
TPL_VARS["cmd_promote"] = "{name} ← الاسم (قابل للضغط)\n{id} ← الآيدي\n{perms} ← الصلاحيات الممنوحة"
TPL_VARS["cmd_demote"] = "{name} ← الاسم (قابل للضغط)\n{id} ← الآيدي\n{ranks} ← الرتب المحذوفة من البوت"
TPL_VARS["cmd_demote_all"] = ("{name} ← الاسم (قابل للضغط)\n{id} ← الآيدي\n{ranks} ← الرتب المحذوفة\n"
                              "{restrictions} ← القيود المرفوعة")
TPL_VARS["cmd_raid"] = ("{name} ← اسم المشرف (قابل للضغط)\n{id} ← الآيدي\n{username} ← اليوزر\n"
                        "{count} ← عدد عمليات الحظر\n{minutes} ← المدة بالدقائق")

# ---- أمر التحذير (تحذير N من M ثم كتم تلقائي) ----
CMD_BUILTIN.update({gr_n("تحذير"): "warn"})
CMD_ACTION_LABELS["warn"] = "تحذير المستخدم"
CMD_TPL["warn"] = "cmd_warn"
CMD_DEFAULTS["cmd_warn"] = _RLM + "「 {name} 」 \n⇜ تم تحذيره\n⇜ التحذيرات: {count} من {limit}\n⇜ باقي قبل الكتم: {remaining}\n༄"
CMD_DEFAULTS["cmd_warn_mute"] = _RLM + "「 {name} 」 \n⇜ وصل لـ {limit} تحذيرات\n⇜ تم كتمه لمدة {time}\n⇜ حتى: {until}\n༄"
TPL_NEEDS.update({"cmd_warn": "{name}", "cmd_warn_mute": "{name}"})
TPL_LABELS.update({"cmd_warn": "كليشة التحذير", "cmd_warn_mute": "كليشة الكتم بعد التحذيرات"})
TPL_VARS["cmd_warn"] = ("{name} ← الاسم (قابل للضغط)\n{id} ← الآيدي\n{count} ← رقم التحذير الحالي\n"
                        "{limit} ← عدد التحذيرات قبل الكتم\n{remaining} ← المتبقي قبل الكتم")
TPL_VARS["cmd_warn_mute"] = ("{name} ← الاسم (قابل للضغط)\n{id} ← الآيدي\n{limit} ← عدد التحذيرات\n"
                             "{time} ← مدة الكتم\n{until} ← وقت انتهاء الكتم")

def raid_default():
    return tm_build([
        S(EM_SHIELD, e=TR_E_SHIELD), S(" "), S("تجريد مشرف — حظر عشوائي", "bold"), S(" "), S(EM_SHIELD, e=TR_E_SHIELD),
        S("\n" + "━" * 20 + "\n\n"),
        S(EM_STOP, e=TR_E_STOP), S(" "), S("تم رصد عمليات حظر عشوائية من المشرف:", "bold"),
        S("\n\n"),
        S(EM_USER, e=TR_E_USER), S(" "), S("الاسم:", "bold"), S(" {name}"),
        S("\n" + EM_DIAMOND + " "), S("الآيدي:", "bold"), S(" "), S("{id}", "code"),
        S("\n" + EM_DIAMOND + " "), S("اليوزر:", "bold"), S(" {username}"),
        S("\n" + EM_ALERT + " "), S("عدد الحظر:", "bold"), S(" {count} خلال {minutes} دقيقة"),
        S("\n\n" + "━" * 20 + "\n"),
        S(EM_CHECK, e=TR_E_CHECK), S(" "),
        S("تم سحب إشرافه وتجريده من صلاحيات البوت وكتمه وتقييده لحين مراجعة المالك.", "bold"),
    ])

CMD_ALIAS_CACHE = [0.0, {}]
CMD_TASKS = set()
SEEN_USERS = {}
_UNITS = {}
for _words, _secs in ((("s", "sec", "secs", "second", "seconds", "ث", "ثانيه", "ثواني", "اس"), 1),
                      (("m", "min", "mins", "minute", "minutes", "mint", "د", "دقيقه", "دقايق", "ام", "مينت"), 60),
                      (("h", "hr", "hrs", "hour", "hours", "س", "ساعه", "ساعات", "اتش"), 3600),
                      (("d", "day", "days", "ي", "يوم", "ايام", "داي"), 86400),
                      (("w", "week", "weeks", "اسبوع"), 604800)):
    for _w in _words:
        _UNITS[gr_n(_w)] = _secs
_DUR_RE = re.compile(r"(?<![\w@])(\d{1,6})\s*([a-zA-Z؀-ۿ]{1,10})(?![\w])")


def parse_duration(text):
    """Return total seconds from every recognized duration token and remove those tokens."""
    total, spans = 0, []
    for m in _DUR_RE.finditer(text or ""):
        unit = _UNITS.get(gr_n(m.group(2)))
        if unit:
            total += int(m.group(1)) * unit
            spans.append((m.start(), m.end()))
    if not spans:
        return None, text
    parts, pos = [], 0
    for start, end in spans:
        parts.append(text[pos:start])
        pos = end
    parts.append(text[pos:])
    return total, " ".join("".join(parts).split())

def fmt_duration(seconds):
    if not seconds:
        return "دائم"
    parts = []
    for size, label in ((86400, "يوم"), (3600, "ساعة"), (60, "دقيقة"), (1, "ثانية")):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {label}")
    return " و".join(parts)

def parse_target_token(text):
    um = re.search(r"@([a-z0-9_]{4,32})", text)
    if um:
        return ("user", um.group(1))
    im = re.search(r"(?<![\w])(\d{5,15})(?![\w])", text)
    if im:
        return ("id", int(im.group(1)))
    return None

def perms_from(allowed=None, all_value=False):
    flags = [p for p in inspect.signature(ChatPermissions).parameters if p.startswith("can_")]
    return ChatPermissions(**{f: (allowed.get(f, True) if allowed is not None else all_value) for f in flags})

def until_for(seconds):
    # Telegram treats < 30 seconds as "forever", so short bans/mutes are lifted by the bot itself.
    return int(time.time()) + max(seconds, 60) if seconds else None

async def cmd_aliases():
    now = time.time()
    if now - CMD_ALIAS_CACHE[0] < GR_CACHE_TTL:
        return CMD_ALIAS_CACHE[1]
    data = await db.getj("cmd_aliases") or {}
    CMD_ALIAS_CACHE[0], CMD_ALIAS_CACHE[1] = now, data
    return data

async def cmd_phrase_map():
    phrases = dict(await cmd_aliases())
    phrases.update(CMD_BUILTIN)
    return phrases

async def remember_user(user):
    if user and user.username and not user.is_bot:
        key = user.username.lower()
        if SEEN_USERS.get(key) != user.id:
            SEEN_USERS[key] = user.id
            await db.cmd("SET", "uname:" + key, str(user.id))

async def user_id_by_name(bot, uname):
    key = uname.lower()
    if key in SEEN_USERS:
        return SEEN_USERS[key]
    raw = await db.cmd("GET", "uname:" + key)
    if raw and str(raw).isdigit():
        SEEN_USERS[key] = int(raw)
        return int(raw)
    try:
        found = await bot.get_chat("@" + uname)
        if found.type == ChatType.PRIVATE:
            return found.id
    except TelegramError:
        pass
    return None

_MEMBER_CACHE = {}
MEMBER_TTL = 30   # seconds; also dropped immediately on any chat_member update

async def gr_member(bot, chat_id, user_id):
    """get_chat_member with a short cache (admin checks run on every command)."""
    key = (chat_id, user_id)
    now = time.monotonic()
    hit = _MEMBER_CACHE.get(key)
    if hit and now - hit[0] < MEMBER_TTL:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramError:
        return None
    if len(_MEMBER_CACHE) > 5000:
        _MEMBER_CACHE.clear()
    _MEMBER_CACHE[key] = (now, member)
    return member

def gr_member_invalidate(chat_id, user_id):
    _MEMBER_CACHE.pop((chat_id, user_id), None)

async def gr_is_group_owner(bot, chat_id, user_id):
    """True for the bot owners (anywhere) or the real owner (creator) of this group."""
    if user_id in OWNER_IDS:
        return True
    if not user_id or user_id == GR_ANON_ADMIN_ID:
        return False
    member = await gr_member(bot, chat_id, user_id)
    return bool(member and member.status == "creator")

async def gr_has_right(bot, chat_id, user_id, right):
    if user_id in OWNER_IDS:
        return True
    member = await gr_member(bot, chat_id, user_id)
    if member is None:
        return False
    if member.status == "creator":
        return True
    return member.status == "administrator" and (right is None or bool(getattr(member, right, False)))

async def resolve_target(context, msg, chat_id, rest):
    """Return (user_id, display_name) from a reply, a text mention, an @username or a numeric ID."""
    reply = msg.reply_to_message
    if reply and reply.from_user:
        return reply.from_user.id, reply.from_user.full_name
    for e in msg.entities or []:
        if e.type == "text_mention" and getattr(e, "user", None):
            return e.user.id, e.user.full_name
    tgt = parse_target_token(rest)
    if not tgt:
        return None
    uid = tgt[1] if tgt[0] == "id" else await user_id_by_name(context.bot, tgt[1])
    if not uid:
        return None
    try:
        member = await context.bot.get_chat_member(chat_id, uid)
        return uid, member.user.full_name
    except TelegramError:
        return uid, str(uid)

def extract_reason(rest, msg):
    """Whatever is left after the command, target and duration is the reason."""
    rest = rest or ""
    reply = msg.reply_to_message
    if not (reply and reply.from_user):
        done = False
        for e in msg.entities or []:
            if e.type == "text_mention" and getattr(e, "user", None):
                name = gr_n((msg.text or "")[e.offset:e.offset + e.length])
                if name and name in rest:
                    rest, done = rest.replace(name, " ", 1), True
                break
        if not done:
            um = re.search(r"@([a-z0-9_]{4,32})", rest)
            im = None if um else re.search(r"(?<![\w])(\d{5,15})(?![\w])", rest)
            hit = um or im
            if hit:
                rest = rest[:hit.start()] + " " + rest[hit.end():]
    return " ".join(rest.split())

async def unrestrict_everyone(bot, chat_id):
    """Lift mute/restriction (never bans) from everyone the bot muted/restricted in this chat."""
    keys, cursor = [], "0"
    while True:
        cursor, found = await db.cmd("SCAN", cursor, "MATCH", f"mod_state:{chat_id}:*", "COUNT", "1000")
        keys += found
        if str(cursor) == "0":
            break
    uids = []
    for k in keys:
        st = await db.getj(k)
        if st and st.get("action") in ("mute", "tayeed"):
            uids.append(int(k.rsplit(":", 1)[1]))
    lifted = 0
    for i in range(0, len(uids), 10):
        async def one(u):
            snap = await get_member_snapshot(bot, chat_id, u)
            ok = False
            if snap and snap["is_restricted"] and snap["is_member"]:
                try:
                    await restore_member_restriction(bot, chat_id, u, unban=False)
                    ok = True
                except TelegramError:
                    return False
            if not snap or snap["status"] != "kicked":
                await clear_mod_state(chat_id, u)
            return ok
        lifted += sum(1 for r in await asyncio.gather(*(one(u) for u in uids[i:i + 10])) if r)
    return lifted

def fmt_until(seconds):
    if not seconds:
        return "دائم"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Cairo")
    except Exception:
        tz = timezone(timedelta(hours=2))
    return (datetime.now(tz) + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M")


async def cmd_say(bot, chat_id, reply_to, kind, name, uid, seconds=None, extra=None):
    tpl_text, tpl_ents = await tpl_get(kind)
    values = {
        "name": name, "id": uid, "time": fmt_duration(seconds),
        "duration": fmt_duration(seconds), "until": fmt_until(seconds), "end_time": fmt_until(seconds),
        "action": "", "command": "", "restrictions": "", "reason": "بدون سبب",
    }
    values.update(extra or {})
    spans = {}
    text, ents = tpl_render(tpl_text, tpl_ents, values, spans)
    if uid and "name" in spans:
        start, length = spans["name"]
        if length:
            ents.append({"type": "text_link", "offset": start, "length": length, "url": f"tg://user?id={uid}"})
    return await tr_send(bot, chat_id, reply_to, text, ents)


async def get_member_snapshot(bot, chat_id, uid):
    try:
        member = await bot.get_chat_member(chat_id, uid)
    except TelegramError:
        return None
    status = member.status
    is_member = getattr(member, "is_member", status not in ("left", "kicked"))
    can_send = getattr(member, "can_send_messages", True)
    permissions = getattr(member, "permissions", None)
    if permissions is not None:
        can_send = getattr(permissions, "can_send_messages", can_send)
    # Only the ability to send messages defines a mute/restriction here.
    # Telegram can report status=restricted for media/info-only limitations.
    is_send_blocked = status == "restricted" and bool(is_member) and not bool(can_send)
    return {
        "member": member, "status": status, "is_member": is_member,
        "can_send": bool(can_send), "is_banned": status == "kicked",
        "is_restricted": is_send_blocked,
        "is_muted": is_send_blocked,
    }


async def get_mod_state(chat_id, uid):
    state = await db.getj(f"mod_state:{chat_id}:{uid}")
    if not state:
        return None
    until_ts = state.get("until_ts")
    if until_ts and int(until_ts) <= int(time.time()):
        await db.cmd("DEL", f"mod_state:{chat_id}:{uid}")
        return None
    return state


async def set_mod_state(chat_id, uid, action, seconds=None, reason=None):
    await db.setj(f"mod_state:{chat_id}:{uid}", {
        "action": action, "reason": reason or "",
        "until_ts": int(time.time()) + seconds if seconds else None,
        "updated_at": int(time.time()),
    })


async def clear_mod_state(chat_id, uid):
    await db.cmd("DEL", f"mod_state:{chat_id}:{uid}")


async def restore_member_restriction(bot, chat_id, uid, *, unban=False):
    if unban:
        try:
            await bot.unban_chat_member(chat_id, uid, only_if_banned=True)
        except TelegramError:
            pass
    cur = (await bot.get_chat(chat_id)).permissions
    allowed = {f: bool(getattr(cur, f, True)) for f in inspect.signature(ChatPermissions).parameters if f.startswith("can_")} if cur else None
    try:
        await bot.restrict_chat_member(chat_id, uid, perms_from(allowed, True))
    except TelegramError:
        if not unban:
            raise


async def lift_restrictions(bot, chat_id, uid):
    await restore_member_restriction(bot, chat_id, uid, unban=True)

async def delayed_lift(bot, chat_id, uid, seconds, mode):
    await asyncio.sleep(seconds)
    try:
        if mode == "ban":
            await bot.unban_chat_member(chat_id, uid, only_if_banned=True)
        else:
            await restore_member_restriction(bot, chat_id, uid, unban=False)
    except Exception:
        log.info("Delayed lift failed", exc_info=True)

def schedule_lift(bot, chat_id, uid, seconds, mode):
    if seconds and seconds < 60:
        task = asyncio.create_task(delayed_lift(bot, chat_id, uid, seconds, mode))
        CMD_TASKS.add(task)
        task.add_done_callback(CMD_TASKS.discard)

async def cmd_kashf(context, chat_id, reply_to, uid, name):
    bot = context.bot
    rank, membership, username, role = "غير معروف", "غير معروف", "لا يوجد", "—"
    snapshot = await get_member_snapshot(bot, chat_id, uid)
    if snapshot:
        member = snapshot["member"]
        status = snapshot["status"]
        if member.user.username:
            username = "@" + member.user.username
        if status == "creator":
            rank, membership = "مالك", "في المجموعة"
        elif status == "administrator":
            rank, membership = "مشرف", "في المجموعة"
        elif status == "member":
            rank, membership = "عضو", "في المجموعة"
        elif status == "restricted":
            rank = "عضو"
            if not snapshot["is_member"]:
                membership = "طالع"
            elif not snapshot["can_send"]:
                membership = "مكتوم / مقيّد"
            else:
                # Ignore media and other permissions: only send-message access counts.
                membership = "في المجموعة"
        elif status == "kicked":
            rank, membership = "عضو", "محظور"
        elif status == "left":
            rank, membership = "عضو", "طالع"
        else:
            rank, membership = status, status
        if member.user.is_bot:
            rank += " (بوت)"
    low = username[1:].lower() if username.startswith("@") else None
    if low:
        if any(t["username"].lower() == low for t in await tr_load(chat_id)):
            role = "تاجر معتمد"
        for r, label in (("mod", "مشرف معتمد"), ("owner", "مالك معتمد")):
            if any(t["username"].lower() == low for t in await role_load(r, chat_id)):
                role = label
    keys = {str(uid)} | ({low} if low else set())
    n = len(await find_reports_by_keys(keys, limit=50))
    _st = await get_mod_state(chat_id, uid)
    _reason = (_st or {}).get("reason") or "لا يوجد"
    await cmd_say(bot, chat_id, reply_to, "cmd_kashf", name, uid, extra={
        "reason": _reason, "username": username, "rank": rank, "membership": membership,
        "status": membership, "role": role,
        "reports": f"{n} بلاغ" if n else "لا يوجد", "link": f"tg://user?id={uid}"})
def find_command_in_message(text, phrases, is_reply=False):
    """Find a moderation command at the start/end of a line, or beside its target/duration."""
    lines = (text or "").translate(_AR_DIGITS).splitlines()
    for phrase in sorted(phrases, key=len, reverse=True):
        p = gr_n(phrase)
        pattern = re.compile(r"(?<!\w)" + re.escape(p).replace(r"\ ", r"\s+") + r"(?!\w)")
        for index, line in enumerate(lines):
            normalized = gr_n(line).strip()
            if not normalized:
                continue
            match = pattern.search(normalized)
            if not match:
                continue
            left, right = normalized[:match.start()].strip(), normalized[match.end():].strip()
            if left and right:
                valid_position = bool(parse_target_token(left) or parse_duration(left)[0] or
                                      parse_target_token(right) or parse_duration(right)[0])
            elif left:
                valid_position = bool(parse_target_token(left) or parse_duration(left)[0])
            elif right:
                valid_position = bool(parse_target_token(right) or parse_duration(right)[0])
                # Reply + command at the start of the line: the rest is the reason (no duration needed).
                if not valid_position and is_reply and phrases[phrase] in CMD_TIMED:
                    valid_position = True
            else:
                valid_position = True
            if not valid_position:
                continue
            remaining = list(lines)
            remaining[index] = left + " " + right
            return phrases[phrase], " ".join(x.strip() for x in remaining if x.strip()).translate(_AR_DIGITS)
    return None, ""


CMD_OWNER_ONLY = {"promote", "demote", "demote_all"}   # commands only the group owner may run

async def cmd_dispatch(update, context):
    """Run a moderation command. Supports reply, ID/@username and command/target on separate lines."""
    msg, chat = update.effective_message, update.effective_chat
    text = (msg.text or "").strip()
    if not text:
        return False
    phrases = await cmd_phrase_map()
    action, rest = find_command_in_message(text, phrases, bool(msg.reply_to_message))
    if not action:
        return False
    rest = gr_n(rest)
    seconds = None
    if action in ("lock", "unlock", "unrestrict_all"):
        if rest:
            return False
    elif action == "pin":
        if not msg.reply_to_message:
            return False
    else:
        if action in CMD_TIMED:
            seconds, rest = parse_duration(rest)
        has_entity = any(e.type == "text_mention" for e in (msg.entities or []))
        if not (msg.reply_to_message or parse_target_token(rest) or has_entity):
            return False
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    uid = msg.from_user.id if msg.from_user else 0
    right = {"pin": "can_pin_messages", "kashf": None, "promote": "can_promote_members",
             "demote": "can_promote_members", "demote_all": "can_promote_members"}.get(action, None)  # any group admin may ban/mute/kick/restrict via the bot
    if action in CMD_OWNER_ONLY:
        if anonymous or not await gr_is_group_owner(context.bot, chat.id, uid):
            return True        # group owner only: silently ignore everyone else
    elif not anonymous and not await gr_has_right(context.bot, chat.id, uid, right):
        return False
    bot = context.bot
    try:
        if action == "lock":
            cur = (await bot.get_chat(chat.id)).permissions
            if cur and not await db.getj(f"chat_perms:{chat.id}"):
                await db.setj(f"chat_perms:{chat.id}", {f: bool(getattr(cur, f, True)) for f in inspect.signature(ChatPermissions).parameters if f.startswith("can_")})
            await bot.set_chat_permissions(chat.id, perms_from(all_value=False))
            await cmd_say(bot, chat.id, msg.message_id, "cmd_lock", "", 0)
            return True
        if action == "unlock":
            saved = await db.getj(f"chat_perms:{chat.id}")
            await bot.set_chat_permissions(chat.id, perms_from(saved) if saved else perms_from(all_value=True))
            await db.cmd("DEL", f"chat_perms:{chat.id}")
            await cmd_say(bot, chat.id, msg.message_id, "cmd_unlock", "", 0)
            return True
        if action == "unrestrict_all":
            n = await unrestrict_everyone(bot, chat.id)
            if not n:
                await msg.reply_text("مفيش حد مكتوم أو مقيّد من البوت.", reply_to_message_id=msg.message_id)
                return True
            await cmd_say(bot, chat.id, msg.message_id, "cmd_unrestrict_all", "", 0, extra={"count": n})
            return True
        if action == "pin":
            await bot.pin_chat_message(chat.id, msg.reply_to_message.message_id)
            try: await bot.delete_message(chat.id, msg.message_id)
            except TelegramError: pass
            return True

        target = await resolve_target(context, msg, chat.id, rest)
        if not target:
            await msg.reply_text("ما قدرتش أحدد الشخص. اعمل ريبلاي على رسالته أو اكتب الآيدي الرقمي أو اليوزر.")
            return True
        tid, name = target
        if tid == bot.id:
            return True
        reason = extract_reason(rest, msg) if action in CMD_TIMED else ""

        if action == "warn":
            await warn_action(context, msg, chat, tid, name)
            return True

        if action in ("promote", "demote", "demote_all"):
            await admin_role_action(context, msg, chat.id, action, tid, name)
            return True

        snapshot = await get_member_snapshot(bot, chat.id, tid)
        state = await get_mod_state(chat.id, tid)
        current_status = snapshot["status"] if snapshot else None
        state_action = state.get("action") if state else None

        if action == "ban":
            if snapshot and snapshot["is_banned"]:
                note = "العضو مطرود من قبل." if state_action == "kick" else "العضو محظور من قبل."
                await msg.reply_text(note, reply_to_message_id=msg.message_id)
                return True
            await bot.ban_chat_member(chat.id, tid, until_date=until_for(seconds))
            await set_mod_state(chat.id, tid, "ban", seconds, reason)
            schedule_lift(bot, chat.id, tid, seconds, "ban")
        elif action == "kick":
            if snapshot and snapshot["is_banned"]:
                note = "العضو محظور من قبل." if state_action == "ban" else "العضو مطرود من قبل."
                await msg.reply_text(note, reply_to_message_id=msg.message_id)
                return True
            if current_status == "left" and state_action == "kick":
                await msg.reply_text("العضو مطرود من قبل.", reply_to_message_id=msg.message_id)
                return True
            await bot.ban_chat_member(chat.id, tid, until_date=until_for(seconds))
            if seconds:
                await set_mod_state(chat.id, tid, "kick", seconds, reason)
                schedule_lift(bot, chat.id, tid, seconds, "ban")
            else:
                await bot.unban_chat_member(chat.id, tid, only_if_banned=True)
                await set_mod_state(chat.id, tid, "kick", None, reason)
        elif action in ("mute", "tayeed"):
            if snapshot and snapshot["is_muted"]:
                note = "العضو مقيّد من قبل." if state_action == "tayeed" else "العضو مكتوم من قبل."
                await msg.reply_text(note, reply_to_message_id=msg.message_id)
                return True
            # A restricted ChatMember is not necessarily muted. Telegram can
            # report status=restricted for partial media/other permissions,
            # even while can_send_messages=True. Only block a new mute when
            # the member is actually unable to send messages.
            await bot.restrict_chat_member(chat.id, tid, perms_from(all_value=False), until_date=until_for(seconds))
            await set_mod_state(chat.id, tid, action, seconds, reason)
            schedule_lift(bot, chat.id, tid, seconds, "restrict")
        elif action == "unban":
            if not snapshot or not snapshot["is_banned"]:
                await clear_mod_state(chat.id, tid)
                await msg.reply_text("العضو مو محظور.", reply_to_message_id=msg.message_id)
                return True
            await bot.unban_chat_member(chat.id, tid, only_if_banned=True)
            await clear_mod_state(chat.id, tid)
            await cmd_say(bot, chat.id, msg.message_id, CMD_TPL[action], name, tid,
                          extra={"action": "تم إلغاء الحظر", "command": "إلغاء الحظر"})
            return True
        elif action == "unmute":
            if not snapshot or not snapshot["is_muted"]:
                await msg.reply_text("العضو مو مكتوم.", reply_to_message_id=msg.message_id)
                return True
            await restore_member_restriction(bot, chat.id, tid, unban=False)
            await clear_mod_state(chat.id, tid)
            await cmd_say(bot, chat.id, msg.message_id, CMD_TPL[action], name, tid,
                          extra={"action": "تم إلغاء الكتم", "command": "إلغاء الكتم"})
            return True
        elif action == "unrestrict":
            restrictions = []
            if snapshot and snapshot["is_banned"]:
                restrictions.append("طرد" if state_action == "kick" else "حظر")
            elif snapshot and snapshot["is_restricted"] and snapshot["is_member"]:
                if state_action in {"mute", "tayeed"}:
                    restrictions.append("كتم" if state_action == "mute" else "تقييد")
                else:
                    restrictions.append("كتم" if snapshot["is_muted"] else "تقييد")
            elif current_status == "left" and state_action == "kick":
                restrictions.append("طرد")
            if not restrictions:
                await clear_mod_state(chat.id, tid)
                await msg.reply_text("العضو ما عليه قيود من قبل.", reply_to_message_id=msg.message_id)
                return True
            await lift_restrictions(bot, chat.id, tid)
            await clear_mod_state(chat.id, tid)
            restrictions_text = "\n".join(f"{i}) {label}" for i, label in enumerate(restrictions, 1))
            await cmd_say(bot, chat.id, msg.message_id, CMD_TPL[action], name, tid,
                          extra={"restrictions": restrictions_text, "action": "رفع القيود", "command": "رفع القيود"})
            return True
        elif action == "kashf":
            await cmd_kashf(context, chat.id, msg.message_id, tid, name)
            return True

        if action in ("ban", "kick") and not anonymous and uid and msg.from_user:
            # Anti-raid accounting runs in the background so the reply below is never delayed.
            ar_spawn(ar_record(bot, chat.id, chat.title or str(chat.id), uid,
                               msg.from_user.full_name, msg.from_user.username))
        action_text = {"ban": "حظرته", "mute": "كتمته", "kick": "طردته", "tayeed": "قيّدته"}.get(action, "")
        command_text = {"ban": "حظر", "mute": "كتم", "kick": "طرد", "tayeed": "تقييد"}.get(action, "")
        extra = {"action": action_text, "command": command_text, "reason": reason or "بدون سبب"}
        if action == "kick" and not seconds:
            extra.update({"time": "فوري", "until": "—"})
        await cmd_say(bot, chat.id, msg.message_id, CMD_TPL[action], name, tid, seconds, extra=extra)
    except TelegramError as exc:
        await msg.reply_text(f"❌ ما قدرتش أنفذ الأمر: {exc}\nتأكد إن البوت أدمن بصلاحية الحظر/التقييد وإن الشخص مش مشرف.")
    return True


# ---------- private admin panel: "إدارة الشات" (formerly "أوامر البوت") ----------
async def botcmds_open(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("الأمر متاح للمشرفين المصرح لهم فقط."); return
    buttons = [make_button("تعديل " + TPL_LABELS[k], callback_data="tpl_edit:" + k, style="primary")
               for k in ("cmd_ban", "cmd_mute", "cmd_kick", "cmd_tayeed", "cmd_unrestrict", "cmd_unban", "cmd_unmute", "cmd_unrestrict_all", "cmd_lock", "cmd_unlock", "cmd_kashf")]
    buttons += [make_button("تعديل كليشة رفع المشرف", callback_data="tpl_edit:cmd_promote", style="primary"),
                make_button("تعديل كليشة تنزيل المشرف", callback_data="tpl_edit:cmd_demote", style="primary"),
                make_button("إعدادات التحذير", callback_data="warncfg_open", style="primary"),
                make_button("تعديل دليل الأوامر", callback_data="editmsg:cmd_guide", style="primary"),
                make_button("إضافة أمر", callback_data="cmd_add_start", style="primary"),
                make_button("حذف أمر مضاف", callback_data="cmd_del_start", style="primary")]
    buttons.append(nav_back("admin_open"))
    await edit_or_send(q.message, "إدارة الشات:", reply_markup=InlineKeyboardMarkup(two_column_rows(buttons)))

async def cmdadd_start(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("غير مصرح لك."); return
    clear_priv_flows(context)
    if q.data == "cmd_del_start":
        aliases = await cmd_aliases()
        context.user_data["cmdadd_flow"] = {"step": "del"}
        listing = "\n".join(f"• {w} ← {CMD_ACTION_LABELS.get(a, a)}" for w, a in aliases.items()) or "لا توجد أوامر مضافة."
        await q.message.reply_text(f"الأوامر المضافة:\n{listing}\n\nأرسل الكلمة المراد حذفها، أو اكتب: إلغاء"); return
    context.user_data["cmdadd_flow"] = {"step": "word"}
    await q.message.reply_text("أرسل الكلمة الجديدة التي تريد إضافتها كأمر (مثال: بان).\n\nللإلغاء اكتب: إلغاء")

async def cmdadd_message(update, context):
    flow = context.user_data.get("cmdadd_flow")
    msg = update.effective_message
    if not flow or not msg or not msg.text:
        return
    if not await is_admin(update.effective_user.id):
        context.user_data.pop("cmdadd_flow", None); return
    word = gr_n(msg.text)
    if word == "الغاء":
        context.user_data.pop("cmdadd_flow", None)
        await msg.reply_text("تم الإلغاء."); return
    if flow["step"] == "del":
        aliases = dict(await cmd_aliases())
        if word not in aliases:
            await msg.reply_text("الكلمة دي مش من الأوامر المضافة. أرسل كلمة صحيحة أو اكتب: إلغاء"); return
        aliases.pop(word)
        await db.setj("cmd_aliases", aliases)
        CMD_ALIAS_CACHE[0] = 0.0
        context.user_data.pop("cmdadd_flow", None)
        await msg.reply_text("✅ تم حذف الأمر."); return
    if flow["step"] == "word":
        if not word or len(word) > 30:
            await msg.reply_text("أرسل كلمة قصيرة (حتى 30 حرفًا)."); return
        if word in CMD_BUILTIN:
            await msg.reply_text("الكلمة دي أمر أساسي في البوت بالفعل. أرسل كلمة تانية."); return
        flow.update({"word": word, "step": "action"})
        buttons = [make_button(label, callback_data="cmdact:" + a, style="primary") for a, label in CMD_ACTION_LABELS.items()]
        await msg.reply_text(f"تمام، الكلمة «{word}». اختر الأمر الذي تنفذه:", reply_markup=InlineKeyboardMarkup(two_column_rows(buttons)))
        return
    await msg.reply_text("اختر الأمر من الأزرار أعلاه، أو اكتب: إلغاء")

async def cmdact_callback(update, context):
    q = update.callback_query
    await q.answer()
    flow = context.user_data.get("cmdadd_flow")
    action = q.data.split(":", 1)[1]
    if not await is_admin(q.from_user.id) or not flow or flow.get("step") != "action" or action not in CMD_ACTION_LABELS:
        return
    aliases = dict(await cmd_aliases())
    aliases[flow["word"]] = action
    await db.setj("cmd_aliases", aliases)
    CMD_ALIAS_CACHE[0] = 0.0
    context.user_data.pop("cmdadd_flow", None)
    try: await q.message.edit_text(f"✅ تمت إضافة الأمر «{flow['word']}» ← {CMD_ACTION_LABELS[action]}")
    except TelegramError: await q.message.reply_text(f"✅ تمت إضافة الأمر «{flow['word']}» ← {CMD_ACTION_LABELS[action]}")

# ====================================================================
# Bot-rank helpers + real Telegram admin management (رفع/تنزيل مشرف، تنزيل الكل)
# ====================================================================
ADMIN_GRANT_EXCLUDE = {"can_promote_members"}   # rights the bot never hands over when promoting (edit to allow)
CHANNEL_ONLY_RIGHTS = {"can_post_messages", "can_edit_messages", "can_post_stories", "can_edit_stories",
                       "can_delete_stories", "can_manage_direct_messages"}
PERM_LABELS = {"can_manage_chat": "إدارة الشات", "can_delete_messages": "حذف الرسائل",
               "can_restrict_members": "تقييد الأعضاء", "can_pin_messages": "تثبيت الرسائل",
               "can_invite_users": "دعوة المستخدمين", "can_change_info": "تغيير معلومات المجموعة",
               "can_manage_video_chats": "إدارة المحادثات المرئية", "can_manage_topics": "إدارة المواضيع",
               "can_promote_members": "إضافة مشرفين"}
_PROMOTE_FALLBACK = ["can_manage_chat", "can_delete_messages", "can_manage_video_chats", "can_restrict_members",
                     "can_promote_members", "can_change_info", "can_invite_users", "can_pin_messages",
                     "can_manage_topics"]

def promote_param_names(bot):
    """Right names accepted by the installed PTB promote_chat_member (+ is_anonymous)."""
    try:
        params = inspect.signature(bot.promote_chat_member).parameters
        names = [p for p in params if p.startswith("can_") or p == "is_anonymous"]
    except (TypeError, ValueError):
        names = []
    return names or _PROMOTE_FALLBACK + ["is_anonymous"]

async def bot_grant_rights(bot, chat_id):
    """Rights the bot itself holds in the chat -> (dict of rights to grant, error text)."""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
    except TelegramError:
        return None, "ما قدرتش أقرأ صلاحياتي في المجموعة."
    if me.status != "administrator" or not getattr(me, "can_promote_members", False):
        return None, "لازم أكون أدمن بصلاحية «إضافة مشرفين» عشان أرفع حد."
    rights = {}
    for name in promote_param_names(bot):
        if name == "is_anonymous" or name in ADMIN_GRANT_EXCLUDE or name in CHANNEL_ONLY_RIGHTS:
            continue
        if bool(getattr(me, name, False)):
            rights[name] = True
    if not rights:
        return None, "ما عنديش صلاحيات أقدر أمنحها."
    return rights, None

async def strip_bot_ranks(chat_id, uid, username, include_traders=False):
    """Remove a person from the bot's ranks in this chat (+ the bot-admin list). Returns removed rank labels."""
    uname = (username or "").lower()
    def match(item):
        return bool(uname and item.get("username", "").lower() == uname) or bool(item.get("user_id") and item["user_id"] == uid)
    removed = []
    for role, label in (("mod", "مشرف معتمد"), ("owner", "مالك معتمد")):
        items = await role_load(role, chat_id, fresh=True)
        keep = [it for it in items if not match(it)]
        if len(keep) != len(items):
            await role_save(role, chat_id, keep)
            removed.append(label)
    if include_traders:
        items = await tr_load(chat_id, fresh=True)
        keep = [t for t in items if not (uname and t.get("username", "").lower() == uname)]
        if len(keep) != len(items):
            await tr_save(chat_id, keep)
            removed.append("تاجر معتمد")
    if uid not in OWNER_IDS and await db.cmd("SREM", "admins", str(uid)):
        removed.append("أدمن البوت")
    return removed

async def admin_role_action(context, msg, chat_id, action, tid, name):
    bot = context.bot
    reply = lambda text: msg.reply_text(text, reply_to_message_id=msg.message_id)
    if tid in OWNER_IDS and action != "promote":
        await reply("لا يمكن تنزيل مالك البوت."); return
    try:
        member = await bot.get_chat_member(chat_id, tid)
    except TelegramError:
        member = None
    status = member.status if member else None
    username = member.user.username if member and member.user else None
    if status == "creator":
        await reply("ده مالك المجموعة، لا يمكن تغيير رتبته."); return
    try:
        if action == "promote":
            if status in (None, "left", "kicked"):
                await reply("العضو مش موجود في المجموعة."); return
            await promote_panel_start(context, msg, chat_id, tid, name, member)
            return
        was_admin = status == "administrator"
        if was_admin:
            await bot.promote_chat_member(chat_id, tid, **{p: False for p in promote_param_names(bot)})
        removed = await strip_bot_ranks(chat_id, tid, username, include_traders=(action == "demote_all"))
        lifted = []
        if action == "demote_all":
            snap = await get_member_snapshot(bot, chat_id, tid)
            if snap and snap["status"] == "restricted" and snap["is_member"]:
                await restore_member_restriction(bot, chat_id, tid, unban=False)
                lifted.append("كتم" if snap["is_muted"] else "تقييد")
            await clear_mod_state(chat_id, tid)
        if not (was_admin or removed or lifted):
            await reply("العضو مو مشرف وملوش رتب في البوت."); return
        ranks = "\n".join(f"{i}) {r}" for i, r in enumerate(removed, 1)) or "—"
        extra = {"ranks": ranks, "restrictions": "، ".join(lifted) or "لا يوجد"}
        await cmd_say(bot, chat_id, msg.message_id, CMD_TPL[action], name, tid, extra=extra)
    except TelegramError as exc:
        await reply(f"❌ ما قدرتش أنفذ الأمر: {exc}\nلو الشخص اترفع مشرف بواسطة حد تاني، لازم يتنزل منه أو من المالك.")


# ====================================================================
# Interactive "رفع مشرف": Telegram-style permission picker (bot owners only).
# Green = granted, red = not granted, blue button = confirm.
# ====================================================================
PROMOTE_PERMS = [
    ("info", "تغيير معلومات المجموعة", ("can_change_info",)),
    ("delete", "حذف الرسائل", ("can_delete_messages",)),
    ("restrict", "حظر المستخدمين", ("can_restrict_members",)),
    ("invite", "دعوة المستخدمين عبر الرابط", ("can_invite_users",)),
    ("pin", "تثبيت الرسائل", ("can_pin_messages",)),
    ("tags", "تحرير وسوم الأعضاء", ("can_manage_tags",)),
    ("stories", "إدارة القصص", ("can_post_stories", "can_edit_stories", "can_delete_stories")),
    ("video", "إدارة البثوث المباشرة", ("can_manage_video_chats",)),
    ("promote", "إضافة مشرفين جدد", ("can_promote_members",)),
    ("anon", "البقاء متخفيا", ("is_anonymous",)),
]
PROMOTE_DEFAULT_OFF = {"promote", "anon"}
PR_TTL = 3600

async def promote_available(bot, chat_id):
    """Permission keys the bot is able to hand out in this chat -> (list, error text)."""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
    except TelegramError:
        return None, "ما قدرتش أقرأ صلاحياتي في المجموعة."
    if me.status != "administrator" or not getattr(me, "can_promote_members", False):
        return None, "لازم أكون أدمن بصلاحية «إضافة مشرفين» عشان أرفع حد."
    names = set(promote_param_names(bot))
    avail = []
    for key, _label, params in PROMOTE_PERMS:
        if not all(p in names for p in params):
            continue
        if key != "anon" and not all(getattr(me, p, False) for p in params):
            continue
        avail.append(key)
    return avail, None

def pr_keyboard(token, flow):
    btns = []
    for key, label, _params in PROMOTE_PERMS:
        if key in flow["avail"]:
            on = key in flow["perms"]
            btns.append(make_button(label, callback_data=f"pr:t:{token}:{key}", style="success" if on else "danger"))
    rows = two_column_rows(btns)
    rows.append([make_button("رفع مشرف", callback_data=f"pr:ok:{token}", style="primary"),
                 make_button("إلغاء", callback_data=f"pr:no:{token}", style="primary")])
    return InlineKeyboardMarkup(rows)

def pr_text(flow):
    return (f"صلاحيات المشرف\nالعضو: {flow['name']}\n\n"
            "الأخضر = مفعّل، الأحمر = معطّل. اضغط على أي صلاحية لتغييرها، ثم اضغط «رفع مشرف».")

async def promote_panel_start(context, msg, chat_id, tid, name, member):
    bot = context.bot
    avail, err = await promote_available(bot, chat_id)
    if err:
        await msg.reply_text(err, reply_to_message_id=msg.message_id); return
    perms = {k for k in avail if k not in PROMOTE_DEFAULT_OFF}
    if member and member.status == "administrator":      # editing an existing admin: start from his current rights
        perms = {k for key, _l, params in PROMOTE_PERMS for k in [key]
                 if k in avail and all(getattr(member, p, False) for p in params)}
    flows = context.bot_data.setdefault("pr_flows", {})
    now = time.time()
    for t in [t for t, f in flows.items() if now - f["ts"] > PR_TTL]:
        flows.pop(t, None)
    import secrets as _secrets
    token = _secrets.token_hex(3)
    flow = {"chat_id": chat_id, "tid": tid, "name": name, "reply_to": msg.message_id,
            "avail": avail, "perms": perms, "ts": now}
    flows[token] = flow
    await msg.reply_text(pr_text(flow), reply_markup=pr_keyboard(token, flow), reply_to_message_id=msg.message_id)

async def pr_callback(update, context):
    q = update.callback_query
    parts = (q.data or "").split(":")
    flows = context.bot_data.setdefault("pr_flows", {})
    flow = flows.get(parts[2]) if len(parts) > 2 else None
    if not flow:
        await q.answer("انتهت اللوحة، اكتب الأمر من جديد.", show_alert=True); return
    if not await gr_is_group_owner(context.bot, flow["chat_id"], q.from_user.id):
        await q.answer("الأمر ده لمالك المجموعة فقط.", show_alert=True); return
    token, action = parts[2], parts[1]
    bot = context.bot
    if action == "t" and len(parts) > 3:
        key = parts[3]
        if key in flow["avail"]:
            flow["perms"] ^= {key}
        await q.answer()
        try: await q.edit_message_reply_markup(reply_markup=pr_keyboard(token, flow))
        except TelegramError: pass
        return
    if action == "no":
        flows.pop(token, None)
        await q.answer()
        try: await q.edit_message_text("تم إلغاء رفع المشرف.")
        except TelegramError: pass
        return
    if action != "ok":
        await q.answer(); return
    await q.answer()
    params = {p: False for p in promote_param_names(bot)}
    for key, _label, ps in PROMOTE_PERMS:
        if key in flow["perms"]:
            for p in ps:
                params[p] = True
    if "can_manage_chat" in params:
        params["can_manage_chat"] = True
    try:
        await bot.promote_chat_member(flow["chat_id"], flow["tid"], **params)
    except TelegramError as exc:
        try: await q.edit_message_text(f"ما قدرتش أرفعه: {exc}", reply_markup=pr_keyboard(token, flow))
        except TelegramError: pass
        return
    flows.pop(token, None)
    gr_member_invalidate(flow["chat_id"], flow["tid"])
    labels = [label for key, label, _p in PROMOTE_PERMS if key in flow["perms"]]
    perms_text = "، ".join(labels) or "بدون صلاحيات إضافية"
    try: await q.message.delete()
    except TelegramError:
        try: await q.edit_message_text("تم رفع المشرف.")
        except TelegramError: pass
    await cmd_say(bot, flow["chat_id"], flow["reply_to"], "cmd_promote", flow["name"], flow["tid"], extra={"perms": perms_text})

# ====================================================================
# Broadcast (إذاعة): owners only. Registry of every group the bot is in + guided flow.
# ====================================================================
BC_KEY = "bot:chats"
_BC_SEEN = set()
BC_MAX_BUTTONS = 8

async def bc_track(chat_id):
    if chat_id in _BC_SEEN:
        return
    _BC_SEEN.add(chat_id)
    try:
        await db.cmd("SADD", BC_KEY, str(chat_id))
    except Exception:
        _BC_SEEN.discard(chat_id)

async def bc_my_chat_member(update, context):
    m = update.my_chat_member
    if not m or m.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    try:
        if m.new_chat_member.status in ("member", "administrator"):
            await bc_track(m.chat.id)
        else:
            _BC_SEEN.discard(m.chat.id)
            await db.cmd("SREM", BC_KEY, str(m.chat.id))
    except Exception:
        log.info("bc_my_chat_member failed", exc_info=True)

async def bc_bootstrap():
    """Seed the registry from chats that already have data stored (traders, mods, replies...)."""
    ids = set()
    for pattern in ("group_traders:*", "group_mods:*", "group_owners:*", "group_replies:*", "chat_perms:*"):
        cursor = "0"
        while True:
            cursor, keys = await db.cmd("SCAN", cursor, "MATCH", pattern, "COUNT", "1000")
            for k in keys or []:
                try:
                    cid = int(str(k).rsplit(":", 1)[1])
                    if cid < 0:
                        ids.add(cid)
                except (ValueError, IndexError):
                    pass
            if str(cursor) == "0":
                break
    ids = sorted(ids)
    for i in range(0, len(ids), 100):
        await db.cmd("SADD", BC_KEY, *[str(x) for x in ids[i:i + 100]])
    _BC_SEEN.update(ids)

BC_COLORS = {"primary": "أزرق", "success": "أخضر", "danger": "أحمر"}

def bc_markup(st):
    if not st.get("buttons"):
        return None
    return InlineKeyboardMarkup([[make_button(b["text"], url=b["url"], style=b["style"])] for b in st["buttons"]])

def bc_cancel_kb():
    return InlineKeyboardMarkup([[make_button("إلغاء", callback_data="bc:cancel", style="primary")]])

def bc_norm_url(text):
    t = (text or "").strip()
    if re.match(r"^(https?://|tg://)\S+$", t, re.I):
        return t
    if re.match(r"^(t\.me/|telegram\.me/)\S+$", t, re.I):
        return "https://" + t
    if re.match(r"^@[A-Za-z0-9_]{4,32}$", t):
        return "https://t.me/" + t[1:]
    return None

async def bc_ask_pin(target, st):
    st["step"] = "pin"
    kb = InlineKeyboardMarkup([[make_button("تثبيت الإذاعة", callback_data="bc:pin:y", style="primary"),
                                make_button("بدون تثبيت", callback_data="bc:pin:n", style="primary")],
                               [make_button("إلغاء", callback_data="bc:cancel", style="primary")]])
    await target("هل تثبّت الإذاعة في الشاتات اللي البوت مشرف فيها؟", reply_markup=kb)

async def bc_callback(update, context):
    q = update.callback_query
    if q.from_user.id not in OWNER_IDS:
        await q.answer("الأمر ده لمالك البوت فقط.", show_alert=True); return
    await q.answer()
    data = (q.data or "")[3:]
    st = context.user_data.get("bc")
    edit = lambda text, **kw: edit_or_send(q.message, text, **kw)
    if data == "open":
        clear_priv_flows(context)
        n = await db.cmd("SCARD", BC_KEY) or 0
        context.user_data["bc"] = {"step": "await_msg", "buttons": []}
        await edit(f"الإذاعة\nعدد الشاتات المسجلة: {n}\n\nابعت الرسالة اللي عايز تذيعها (نص أو صورة أو فيديو أو أي محتوى).",
                   reply_markup=bc_cancel_kb())
        return
    if data == "cancel":
        context.user_data.pop("bc", None)
        await edit("تم إلغاء الإذاعة.", reply_markup=InlineKeyboardMarkup([[nav_back("botadmin_open")]]))
        return
    if not st:
        await edit("انتهت جلسة الإذاعة. افتحها من جديد.", reply_markup=InlineKeyboardMarkup([[nav_back("botadmin_open")]])); return
    if data == "btn":
        st["step"] = "btn_name"
        await edit("ابعت اسم الزر.", reply_markup=bc_cancel_kb()); return
    if data == "nobtn":
        st["buttons"] = []
        await bc_ask_pin(edit, st); return
    if data.startswith("color:") and st.get("step") == "btn_color":
        style = data.split(":", 1)[1]
        if style not in BC_COLORS:
            return
        st["buttons"].append({"text": st["cur"]["text"], "url": st["cur"]["url"], "style": style})
        st.pop("cur", None)
        if len(st["buttons"]) >= BC_MAX_BUTTONS:
            await bc_ask_pin(edit, st); return
        st["step"] = "more"
        kb = InlineKeyboardMarkup([[make_button("إضافة زر آخر", callback_data="bc:more:y", style="primary"),
                                    make_button("كفاية كده", callback_data="bc:more:n", style="primary")],
                                   [make_button("إلغاء", callback_data="bc:cancel", style="primary")]])
        await edit(f"تم إضافة الزر ({len(st['buttons'])}). تضيف زر آخر؟", reply_markup=kb); return
    if data.startswith("more:"):
        if data.endswith(":y"):
            st["step"] = "btn_name"
            await edit("ابعت اسم الزر التالي.", reply_markup=bc_cancel_kb())
        else:
            await bc_ask_pin(edit, st)
        return
    if data.startswith("pin:"):
        st["pin"] = data.endswith(":y")
        st["step"] = "confirm"
        n = await db.cmd("SCARD", BC_KEY) or 0
        try:
            await context.bot.copy_message(q.message.chat_id, st["src_chat"], st["src_msg"], reply_markup=bc_markup(st))
        except TelegramError:
            pass
        btn_info = "، ".join(f"{b['text']} ({BC_COLORS[b['style']]})" for b in st["buttons"]) or "بدون أزرار"
        kb = InlineKeyboardMarkup([[make_button("تأكيد الإرسال", callback_data="bc:send", style="primary"),
                                    make_button("إلغاء", callback_data="bc:cancel", style="primary")]])
        await context.bot.send_message(q.message.chat_id,
            f"ده شكل الإذاعة.\nالأزرار: {btn_info}\nالتثبيت: {'نعم' if st['pin'] else 'لا'}\nعدد الشاتات: {n}\n\nتأكد وبعدين اضغط تأكيد الإرسال.",
            reply_markup=kb)
        return
    if data == "send" and st.get("step") == "confirm":
        context.user_data.pop("bc", None)
        await edit("جاري الإذاعة... هبعتلك النتيجة لما تخلص.")
        ar_spawn(bc_run(context.bot, q.message.chat_id, st))
        return

async def bc_message(update, context):
    st = context.user_data.get("bc")
    if not st:
        return
    msg = update.effective_message
    if not update.effective_user or update.effective_user.id not in OWNER_IDS:
        context.user_data.pop("bc", None); return
    if msg.text and gr_n(msg.text) in {"الغاء", "إلغاء"}:
        context.user_data.pop("bc", None)
        await msg.reply_text("تم إلغاء الإذاعة."); return
    step = st["step"]
    if step == "await_msg":
        st["src_chat"], st["src_msg"] = msg.chat_id, msg.message_id
        st["step"] = "choose"
        kb = InlineKeyboardMarkup([[make_button("بزر", callback_data="bc:btn", style="primary"),
                                    make_button("بدون زر", callback_data="bc:nobtn", style="primary")],
                                   [make_button("إلغاء", callback_data="bc:cancel", style="primary")]])
        await msg.reply_text("الإذاعة دي بزر ولا بدون زر؟", reply_markup=kb)
    elif step == "btn_name":
        if not msg.text:
            await msg.reply_text("ابعت اسم الزر كنص."); return
        st["cur"] = {"text": msg.text.strip()[:60]}
        st["step"] = "btn_url"
        await msg.reply_text("ابعت رابط الزر (يبدأ بـ https:// أو t.me/ أو @يوزر).", reply_markup=bc_cancel_kb())
    elif step == "btn_url":
        url = bc_norm_url(msg.text)
        if not url:
            await msg.reply_text("الرابط مش صحيح. ابعته بصيغة https://... أو t.me/... أو @يوزر."); return
        st["cur"]["url"] = url
        st["step"] = "btn_color"
        kb = InlineKeyboardMarkup([[make_button("أزرق", callback_data="bc:color:primary", style="primary"),
                                    make_button("أخضر", callback_data="bc:color:success", style="success"),
                                    make_button("أحمر", callback_data="bc:color:danger", style="danger")],
                                   [make_button("إلغاء", callback_data="bc:cancel", style="primary")]])
        await msg.reply_text("اختار لون الزر:", reply_markup=kb)

async def bc_run(bot, admin_chat_id, st):
    from telegram.error import RetryAfter
    chats = [int(x) for x in (await db.cmd("SMEMBERS", BC_KEY) or [])]
    markup = bc_markup(st)
    ok = failed = pin_failed = 0
    for cid in chats:
        for attempt in (1, 2):
            try:
                sent = await bot.copy_message(cid, st["src_chat"], st["src_msg"], reply_markup=markup)
                ok += 1
                if st.get("pin"):
                    try: await bot.pin_chat_message(cid, sent.message_id)
                    except TelegramError: pin_failed += 1
                break
            except RetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                continue
            except TelegramError as exc:
                failed += 1
                low = str(exc).lower()
                if any(w in low for w in ("forbidden", "chat not found", "kicked", "not a member", "deactivated")):
                    try: await db.cmd("SREM", BC_KEY, str(cid)); _BC_SEEN.discard(cid)
                    except Exception: pass
                break
        await asyncio.sleep(0.06)
    text = f"تمت الإذاعة.\nنجحت: {ok}\nفشلت: {failed}"
    if st.get("pin"):
        text += f"\nفشل التثبيت في: {pin_failed}"
    try: await bot.send_message(admin_chat_id, text)
    except TelegramError: pass

# ====================================================================
# Anti-raid: rate limit on bans (commands + manual Telegram bans via ChatMemberHandler).
# All counting/punishing runs as background tasks, so replies are never delayed.
# ====================================================================
AR_CFG_KEY = "antiraid:config"
AR_DEFAULT = {"enabled": False, "limit": 5, "minutes": 10}
AR_CACHE = [0.0, dict(AR_DEFAULT)]
AR_EVENTS = {}
AR_TASKS = set()

async def _ar_safe(coro):
    try:
        await coro
    except Exception:
        log.exception("Anti-raid task failed")

def ar_spawn(coro):
    task = asyncio.create_task(_ar_safe(coro))
    AR_TASKS.add(task)
    task.add_done_callback(AR_TASKS.discard)

async def ar_config(fresh=False):
    now = time.time()
    if not fresh and now - AR_CACHE[0] < GR_CACHE_TTL:
        return AR_CACHE[1]
    saved = await db.getj(AR_CFG_KEY) or {}
    cfg = dict(AR_DEFAULT)
    try:
        cfg["enabled"] = bool(saved.get("enabled", cfg["enabled"]))
        cfg["limit"] = max(1, int(saved.get("limit", cfg["limit"])))
        cfg["minutes"] = max(1, int(saved.get("minutes", cfg["minutes"])))
    except (TypeError, ValueError):
        cfg = dict(AR_DEFAULT)
    AR_CACHE[0], AR_CACHE[1] = now, cfg
    return cfg

async def ar_save(cfg):
    await db.setj(AR_CFG_KEY, cfg)
    AR_CACHE[0] = 0.0

async def ar_record(bot, chat_id, chat_title, actor_id, name, username):
    """Count one ban by this moderator; punish when the allowed count is exceeded inside the window."""
    if actor_id in OWNER_IDS:
        return
    cfg = await ar_config()
    if not cfg["enabled"]:
        return
    now = time.time()
    key = (chat_id, actor_id)
    events = [t for t in AR_EVENTS.get(key, []) if now - t < cfg["minutes"] * 60]
    events.append(now)
    if len(events) <= cfg["limit"]:
        AR_EVENTS[key] = events
        return
    AR_EVENTS.pop(key, None)
    await ar_punish(bot, chat_id, chat_title, actor_id, name, username, len(events), cfg["minutes"])

async def ar_punish(bot, chat_id, chat_title, uid, name, username, count, minutes):
    try:
        member = await bot.get_chat_member(chat_id, uid)
    except TelegramError:
        member = None
    if member and member.status == "creator":
        return                                   # the group owner is exempt
    if member and member.user and member.user.username:
        username = member.user.username
    demoted = True
    if member is None or member.status == "administrator":
        try:
            await bot.promote_chat_member(chat_id, uid, **{p: False for p in promote_param_names(bot)})
        except TelegramError as exc:
            demoted = False
            log.warning("Anti-raid: could not remove admin rights of %s: %s", uid, exc)
    try:
        await strip_bot_ranks(chat_id, uid, username, include_traders=False)
    except Exception:
        log.info("Anti-raid: could not strip bot ranks", exc_info=True)
    muted = True
    try:
        await bot.restrict_chat_member(chat_id, uid, perms_from(all_value=False))
        await set_mod_state(chat_id, uid, "mute", None)
    except TelegramError as exc:
        muted = False
        log.warning("Anti-raid: could not mute %s: %s", uid, exc)
    await cmd_say(bot, chat_id, None, "cmd_raid", name, uid, extra={
        "username": ("@" + username) if username else "لا يوجد", "count": count, "minutes": minutes})
    if not (demoted and muted):
        await tr_send(bot, chat_id, None,
                      "⚠️ ما قدرتش أسحب إشراف المشرف أو أكتمه بالكامل (غالبًا رفعه مشرف آخر). اسحب إشرافه يدويًا الآن.", [])
    for oid in OWNER_IDS:
        try:
            await bot.send_message(oid, f"🛡️ حماية الحظر العشوائي: تم تجريد {name} ({uid}) في «{chat_title}» "
                                        f"بعد {count} عمليات حظر خلال {minutes} دقيقة." +
                                        ("" if demoted and muted else "\n⚠️ التجريد لم يكتمل، راجع المجموعة يدويًا."))
        except TelegramError:
            pass

async def ar_chat_member(update, context):
    """Manual bans done from Telegram's own admin settings."""
    cm = update.chat_member
    if not cm or not cm.from_user or cm.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    gr_member_invalidate(cm.chat.id, cm.new_chat_member.user.id)
    actor = cm.from_user
    # Our own bot's bans (from commands) are counted in cmd_dispatch, so bot actors are skipped here.
    if actor.is_bot or actor.id == cm.new_chat_member.user.id:
        return
    if cm.new_chat_member.status != "kicked" or cm.old_chat_member.status == "kicked":
        return
    ar_spawn(ar_record(context.bot, cm.chat.id, cm.chat.title or str(cm.chat.id), actor.id,
                       actor.full_name, actor.username))

def antiraid_panel(cfg):
    state = "مفعّلة ✅" if cfg["enabled"] else "معطّلة ⛔"
    text = ("🛡️ حماية الحظر العشوائي\n━━━━━━━━━━━━━━\n"
            f"الحالة: {state}\n"
            f"🔹 عدد الحظر المسموح: {cfg['limit']}\n"
            f"🔹 خلال مدة: {cfg['minutes']} دقيقة\n\n"
            "عند تجاوز الحد يتم سحب إشراف المشرف وتجريده من صلاحيات البوت وكتمه وتقييده لحين مراجعة المالك، "
            "وتُرسل كليشة التجريد في الشات.\n"
            "‼️ مالك البوت ومالك المجموعة مستثنيان من الفحص.")
    buttons = [
        make_button("تعطيل الحماية" if cfg["enabled"] else "تفعيل الحماية", callback_data="antiraid_toggle",
                    style="danger" if cfg["enabled"] else "success"),
        make_button("تحديد عدد الحظر", callback_data="antiraid_set_limit", style="primary"),
        make_button("تحديد المدة بالدقائق", callback_data="antiraid_set_minutes", style="primary"),
        make_button("تعديل كليشة تجريد المشرفين", callback_data="tpl_edit:cmd_raid", style="primary"),
        nav_back("admin_open"),
    ]
    return text, InlineKeyboardMarkup(two_column_rows(buttons))

async def antiraid_callback(update, context):
    q = update.callback_query
    await q.answer()
    if q.from_user.id not in OWNER_IDS:
        await q.message.reply_text("الميزة متاحة لمالك البوت فقط."); return
    cfg = dict(await ar_config(fresh=True))
    if q.data == "antiraid_toggle":
        cfg["enabled"] = not cfg["enabled"]
        await ar_save(cfg)
        AR_EVENTS.clear()
    elif q.data in ("antiraid_set_limit", "antiraid_set_minutes"):
        field = "limit" if q.data == "antiraid_set_limit" else "minutes"
        clear_priv_flows(context)
        context.user_data["ar_flow"] = {"field": field}
        prompt = ("🔢 أرسل عدد عمليات الحظر المسموح بها (من 1 إلى 100)." if field == "limit"
                  else "⏱ أرسل المدة بالدقائق (من 1 إلى 1440).")
        await q.message.reply_text(prompt + "\n\nللإلغاء اكتب: إلغاء"); return
    text, kb = antiraid_panel(cfg)
    await edit_or_send(q.message, text, reply_markup=kb)

async def ar_message(update, context):
    flow = context.user_data.get("ar_flow")
    msg = update.effective_message
    if not flow or not msg or not msg.text:
        return
    if update.effective_user.id not in OWNER_IDS:
        context.user_data.pop("ar_flow", None); return
    text = msg.text.strip()
    if gr_n(text) == "الغاء":
        context.user_data.pop("ar_flow", None)
        await msg.reply_text("تم الإلغاء."); return
    digits = text.translate(_AR_DIGITS)
    lo, hi = (1, 100) if flow["field"] == "limit" else (1, 1440)
    if not re.fullmatch(r"\d{1,4}", digits) or not lo <= int(digits) <= hi:
        await msg.reply_text(f"أرسل رقمًا صحيحًا بين {lo} و{hi}، أو اكتب: إلغاء"); return
    cfg = dict(await ar_config(fresh=True))
    cfg[flow["field"]] = int(digits)
    await ar_save(cfg)
    context.user_data.pop("ar_flow", None)
    body, kb = antiraid_panel(cfg)
    await msg.reply_text("✅ تم الحفظ.\n\n" + body, reply_markup=kb)

PURGE_RE = re.compile(r"^مسح(?:\s+رساله)?(?:\s+(\d{1,4}))?$")
_PURGE_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
PURGE_MAX = 1000

async def _purge_exec(bot, chat_id, ids):
    """Delete message ids as fast as possible: 100 per request, all chunks in parallel, no replies."""
    chunks = [ids[i:i + 100] for i in range(0, len(ids), 100)]
    async def one(chunk):
        try:
            await bot.delete_messages(chat_id, chunk)
        except AttributeError:      # old PTB without bulk delete: fall back to one-by-one, in parallel
            await asyncio.gather(*(bot.delete_message(chat_id, m) for m in chunk), return_exceptions=True)
        except TelegramError:
            pass
    await asyncio.gather(*(one(c) for c in chunks), return_exceptions=True)

async def purge_command(update, context):
    """«مسح» by reply = that message; «مسح N» = last N messages. The command itself is deleted too. Silent."""
    msg, chat = update.effective_message, update.effective_chat
    m = PURGE_RE.match(gr_n(msg.text).translate(_PURGE_DIGITS))
    if not m:
        return False
    reply = msg.reply_to_message
    if reply and msg.is_topic_message and reply.message_id == msg.message_thread_id:
        reply = None            # replying to the topic header is not a reply to a real message
    if not reply and not m.group(1):
        return False
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    uid = msg.from_user.id if msg.from_user else 0
    if not anonymous and not await gr_has_right(context.bot, chat.id, uid, "can_delete_messages"):
        return False
    if reply:
        ids = [reply.message_id]
    else:
        n = min(int(m.group(1)), PURGE_MAX)
        ids = list(range(max(1, msg.message_id - n), msg.message_id))
    ids.append(msg.message_id)
    spawn(_purge_exec(context.bot, chat.id, ids))
    return True

async def _remember_user_safe(user):
    try:
        await remember_user(user)
    except Exception:
        log.info("remember_user failed", exc_info=True)

async def gr_message(update, context):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if msg.from_user and msg.from_user.is_bot and msg.from_user.id != GR_ANON_ADMIN_ID:
        return
    _ai_note_message(msg, chat)  # in-memory only, O(1)
    await bc_track(chat.id)      # remember the chat for broadcasts (DB hit only the first time per chat)
    anonymous = bool(msg.sender_chat and msg.sender_chat.id == chat.id)
    owner = GR_ANON_ADMIN_ID if anonymous else (msg.from_user.id if msg.from_user else 0)
    if msg.from_user and not anonymous:
        spawn(_remember_user_safe(msg.from_user))     # off the hot path: no DB round-trip before handling the message
    flows = gr_flows(context)
    flow = flows.get(owner)
    if flow and time.time() - flow["ts"] > GR_FLOW_TTL:
        flows.pop(owner, None); flow = None
    raw = (msg.text or msg.caption or "").strip()
    if not flow and msg.text and raw.startswith("مسح") and await purge_command(update, context):
        return
    if flow:
        if gr_n(raw) in {"الغاء", "/cancel"} or raw.startswith("/cancel"):
            flows.pop(owner, None)
            await msg.reply_text("تم إلغاء إضافة الرد.")
            return
        if raw.startswith("/"):
            return
        await gr_flow_step(update, context, flow, owner)
        return
    if msg.text and gr_n(msg.text) in GR_ADMIN_TRIGGERS:
        await gr_start(update, context, admin_only=True)
        return
    if msg.text and gr_n(msg.text) in GR_ADMIN_DELETE_TRIGGERS:
        await gr_delete_start(update, context, admin_only=True)
        return
    if msg.text and gr_n(msg.text) in GR_LIST_TRIGGERS:
        await gr_list_replies(update, context)
        return
    if msg.text and gr_n(msg.text) in GR_TRIGGERS:
        await gr_start(update, context)
        return
    if msg.text and gr_n(msg.text) in GR_DELETE_TRIGGERS:
        await gr_delete_start(update, context)
        return
    if msg.text and gr_n(msg.text) in GR_MOD_TRIGGERS:
        await role_start(update, context, "mod")
        return
    if msg.text and gr_n(msg.text) in GR_OWNER_TRIGGERS:
        await role_start(update, context, "owner")
        return
    if msg.text and await cmd_dispatch(update, context):
        return
    if msg.text and await tr_command(update, context):
        return
    await tr_check(update, context)
    await mod_check(update, context)
    if await gr_try_reply(update, context):
        return
    try:
        await ai_after_route(msg, chat, context)  # decision is instant; Gemini runs in a background task
    except Exception:
        log.info("ai_after_route failed", exc_info=True)


# ====================================================================
# ===== مُنقول من البوت الكامل: الروليت + منشن الخاص + ذكاء AI + نظام التحذير =====
# ====================================================================
_BG_TASKS = set()


def spawn(coro):
    """Fire-and-forget helper that keeps a strong reference so tasks are never GC'd mid-flight."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


CAIRO_TZ = ZoneInfo("Africa/Cairo")
def _normalize_arabic(value: str, compact: bool = False) -> str:
    value = (value or "").lower()
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    value = value.translate(str.maketrans({"أ":"ا", "إ":"ا", "آ":"ا", "ى":"ي", "ؤ":"و", "ئ":"ي", "ة":"ه"}))
    if compact:
        value = re.sub(r"[^\w]", "", value, flags=re.UNICODE)
    else:
        value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
        value = re.sub(r"\s+", " ", value).strip()
    return value


# -------------------------------------------------------------
# Roulette (منقول كما هو؛ التخزين على Redis بدل الذاكرة)
# -------------------------------------------------------------
_RL_LOCK = asyncio.Lock()


async def _rl_state():
    data = await db.getj("roulette_state")
    return data if isinstance(data, dict) else {}


async def _rl_save(state):
    await db.setj("roulette_state", state)


async def _rl_is_admin(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if msg and chat and msg.sender_chat and msg.sender_chat.id == chat.id:
        return True
    if not user:
        return False
    return bool(await gr_has_right(context.bot, chat.id, user.id, None) or await is_admin(user.id))


def _roulette_keyboard(chat_id: int, participant_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                make_button(
                    f"🎰 انضمام للسحب ({participant_count})",
                    callback_data=f"roulette_join:{chat_id}",
                    style="success",
                )
            ]
        ]
    )



# -------------------------------------------------------------
# Handlers: Roulette System (عربي + إيموجي مميز + أمر تم)
# -------------------------------------------------------------

async def handle_roulette_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or chat.type == "private":
        return False

    raw_text = (message.text or message.caption or "").strip()
    if not raw_text:
        return False

    # 1. أمر إنهاء السحب (تم / انهاء السحب)
    if raw_text in ["تم", "انهاء السحب", "إنهاء السحب"]:
        state = await _rl_state()
        chat_key = str(chat.id)
        roulette = state.get(chat_key)

        if not roulette or not roulette.get("active"):
            return False

        if not await _rl_is_admin(update, context):
            return True

        participants = list(roulette.get("participants", {}).values())
        winner_count = min(int(roulette.get("winner_count", 1)), len(participants))
        winners = random.sample(participants, winner_count) if winner_count else []
        roulette["active"] = False
        await _rl_save(state)

        if winners:
            winner_lines = [
                f'• <tg-emoji emoji-id="5891182846357281226">🥇</tg-emoji> <b>الفائز:</b> {escape(w["name"])} (@{escape(w["username"]) if w.get("username") else "بدون يوزر"}) — <code>{w["id"]}</code>'
                for w in winners
            ]
            text = (
                f'<tg-emoji emoji-id="6001546218621114827">🎁</tg-emoji> <b>انتهى السحب بنجاح! مبروك للفائزين</b> <tg-emoji emoji-id="6001546218621114827">🎁</tg-emoji>\n'
                f'━━━━━━━━━━━━━━━━━━━━\n\n'
                f'<tg-emoji emoji-id="5776113577211468831">⭐</tg-emoji> <b>الجائزة:</b> <b>{escape(roulette["prize"])}</b>\n\n'
                f'🎉 <b>قائمة الفائزين بالقرعة:</b>\n'
                + "\n".join(winner_lines) + "\n\n"
                f'━━━━━━━━━━━━━━━━━━━━\n'
                f'⚡ <i>تواصل مع مشرفي المجموعة لاستلام جائزتك فوراً.</i>'
            )
        else:
            text = (
                f'<tg-emoji emoji-id="5251457350337849697">❌</tg-emoji> <b>انتهى السحب!</b>\n'
                f'لم يسجل أي مشارك في السحب.'
            )

        await message.reply_text(text, parse_mode=ParseMode.HTML)

        if roulette.get("message_id"):
            try:
                await context.bot.edit_message_reply_markup(chat_id=chat.id, message_id=roulette["message_id"], reply_markup=None)
            except Exception:
                pass
        return True

    # 2. أمر بدء السحب (روليت [العدد] [الجائزة])
    if raw_text.startswith("روليت") or raw_text.startswith("/roulette"):
        if not await _rl_is_admin(update, context):
            return True

        state = await _rl_state()
        chat_key = str(chat.id)
        if state.get(chat_key, {}).get("active"):
            await message.reply_text("⚠️ يوجد سحب نشط بالفعل في هذه المجموعة، اكتب (تم) لإنهائه أولاً.")
            return True

        cmd_prefix = "/roulette" if raw_text.startswith("/roulette") else "روليت"
        content = raw_text[len(cmd_prefix):].strip()

        winner_count = 1
        prize = "سحب مميز"

        match_count = re.search(r"^[\[\(]?(\d+)[\]\)]?\b", content)
        if match_count:
            winner_count = max(1, int(match_count.group(1)))
            prize = content[match_count.end():].strip() or prize
        elif content:
            prize = content

        state[chat_key] = {
            "active": True,
            "prize": prize,
            "winner_count": winner_count,
            "participants": {},
            "message_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        roulette_card = (
            f'<tg-emoji emoji-id="6001546218621114827">🎁</tg-emoji> <b>سـحـب رولـيـت جـديـد</b> <tg-emoji emoji-id="6001546218621114827">🎁</tg-emoji>\n'
            f'━━━━━━━━━━━━━━━━━━━━\n\n'
            f'<tg-emoji emoji-id="5776113577211468831">⭐</tg-emoji> <b>الجائزة:</b> <b>{escape(prize)}</b>\n'
            f'<tg-emoji emoji-id="5891182846357281226">🥇</tg-emoji> <b>عدد الفائزين:</b> <b>{winner_count}</b>\n\n'
            f'👇 <i>اضغط على الزر الأخضر بالأسفل للدخول في السحب فوراً:</i>\n'
            f'━━━━━━━━━━━━━━━━━━━━\n'
            f'⏳ <b>لإنهاء السحب واختيار الفائزين:</b> اكتب « <code>تم</code> » بالشات.'
        )

        sent = await message.reply_text(
            roulette_card,
            parse_mode=ParseMode.HTML,
            reply_markup=_roulette_keyboard(chat.id, 0),
        )
        state[chat_key]["message_id"] = sent.message_id
        await _rl_save(state)
        return True

    return False


async def roulette_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.message:
        return
    try:
        chat_id = int(query.data.split(":", 1)[1])
    except Exception:
        return

    state = await _rl_state()
    chat_key = str(chat_id)
    roulette = state.get(chat_key)
    if not roulette or not roulette.get("active"):
        await query.answer("هذا السحب انتهى.", show_alert=True)
        return

    user = query.from_user
    if str(user.id) in roulette.setdefault("participants", {}):
        await query.answer("أنت مسجل بالفعل في هذا السحب! 🎰", show_alert=True)
        return

    roulette["participants"][str(user.id)] = {
        "id": user.id,
        "username": user.username or "",
        "name": user.full_name,
        "joined_at": datetime.now(timezone.utc).isoformat(),
    }
    await _rl_save(state)
    await query.answer("تم تسجيلك في السحب بنجاح! فالك الفوز 🎰✨")
    try:
        await query.edit_message_reply_markup(reply_markup=_roulette_keyboard(chat_id, len(roulette["participants"])))
    except Exception:
        pass




_RL_FINISH_WORDS = ("تم", "انهاء السحب", "إنهاء السحب")


def _rl_is_roulette_text(text):
    t = (text or "").strip()
    return t in _RL_FINISH_WORDS or t.startswith("روليت") or t.startswith("/roulette")


async def roulette_message(update, context):
    msg = update.effective_message
    if not msg or not _rl_is_roulette_text(msg.text or msg.caption):
        return  # fast path: no Redis call for ordinary messages
    async with _RL_LOCK:
        await handle_roulette_messages(update, context)


async def roulette_join_safe(update, context):
    async with _RL_LOCK:
        await roulette_join(update, context)


# -------------------------------------------------------------
# إشعار الخاص عند المنشن (منقول من البوت الكامل)
# -------------------------------------------------------------
async def notify_mentioned_users(update, context):
    """DM users explicitly mentioned in a group message, with a direct message link."""
    message = update.effective_message
    chat = update.effective_chat
    sender = update.effective_user
    if not message or not chat or not sender or chat.type == "private" or sender.is_bot:
        return
    entities = list(message.entities or []) + list(message.caption_entities or [])
    targets = {}
    for ent in entities:
        if ent.type == "text_mention" and ent.user:
            targets[ent.user.id] = ent.user
        elif ent.type == "mention":
            source = message.text or message.caption or ""
            token = source[ent.offset:ent.offset + ent.length].lstrip("@").lower()
            uid = await user_id_by_name(context.bot, token)
            if uid:
                try:
                    udata = await context.bot.get_chat_member(chat_id=chat.id, user_id=int(uid))
                    targets[udata.user.id] = udata.user
                except TelegramError:
                    pass
    if not targets:
        return
    if chat.username:
        message_url = f"https://t.me/{chat.username}/{message.message_id}"
    elif str(chat.id).startswith("-100"):
        message_url = f"https://t.me/c/{str(chat.id)[4:]}/{message.message_id}"
    else:
        return
    group_name = escape(chat.title or "المجموعة")
    sender_name = escape(sender.full_name)
    sender_ref = f'<a href="tg://user?id={sender.id}">{sender_name}</a>'
    text = f"<b>تمت الإشارة إليك</b>\n• من: {sender_ref}\n• في مجموعة: {group_name}"
    keyboard = InlineKeyboardMarkup([[make_button("👉 اذهب للرسالة", url=message_url, style="success")]])
    for uid, target in targets.items():
        if uid == sender.id or getattr(target, "is_bot", False):
            continue
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        except TelegramError:
            # The user may not have started the bot or may have blocked it.
            continue


async def _notify_mentions_bg(update, context):
    try:
        await notify_mentioned_users(update, context)
    except Exception as exc:
        log.warning("notify_mentioned_users failed: %s", exc)


async def mention_notify_message(update, context):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if msg.entities or msg.caption_entities:
        spawn(_notify_mentions_bg(update, context))  # DMs must never delay anything else


# -------------------------------------------------------------
# نظام تفاعل البوت بالذكاء الاصطناعي (Gemini) — منقول من البوت الكامل
# - كل الاستدعاءات تتم في الخلفية (spawn) بعد انتهاء الأوامر، فلا تؤثر على سرعة أي أمر.
# - مفتاح الـ API من متغير البيئة GEMINI_API_KEY فقط (غير مكتوب في الكود).
# - أسماء النداء (عرب / يا عرب / بوت / يا بوت) قابلة للتعديل من لوحة المالك.
# -------------------------------------------------------------

_AI_KEY = "ai_settings"
_AI_DEFAULTS = {"enabled": True, "schedule_enabled": True, "start": "21:00", "end": "04:00"}
AI_INTERVENE_EVERY = max(2, int(os.getenv("AI_INTERVENE_EVERY", "15")))
AI_REPLY_ANY_BOT_MESSAGE = os.getenv("AI_REPLY_ANY_BOT_MESSAGE", "0").strip() == "1"
_AI_SEM = asyncio.Semaphore(4)
AI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"  # الافتراضي سريع ومستقر
AI_MAX_OUTPUT_TOKENS = 200         # حد أمان (يشمل التفكير)؛ قصر الرد بيتحكم فيه البرومبت + قص آخر سطرين
_AI_CLIENT = None
_AI_CHAT: dict[int, dict[str, Any]] = {}
_AI_USER_LAST: dict[tuple[int, int], float] = {}
_AI_BOT_MSG_IDS: set[tuple[int, int]] = set()
_AI_BOT_MSG_ORDER: deque = deque()
_ROUTE_UNHANDLED = "unhandled"

RAAD_SYSTEM_PROMPT = (
    "أنت \"رعد\"، شاب مصري من شباب شات تليجرام، دمك خفيف وصاحب واجب وبتحب الهزار.\n"
    "قواعدك:\n"
    "- بتتكلم مصري عامية 100% زي الشباب في الشات: هزار وقصف وإيفيهات ذكية "
    "(زي: \"قول إيه.. خدتك عليه\")، من غير فصحى متقعرة ولا كلام مصطنع.\n"
    "- ردودك عفوية وسريعة وقصيرة: سطر واحد أو سطرين بالكتير.\n"
    "- اتكيف مع أسلوب العضو: لو بيهزر جاريه وهزر معاه، ولو جاد رد عليه باحترام.\n"
    "- ممنوع تماماً تقول أو تلمّح إنك ذكاء اصطناعي أو نموذج لغوي أو برنامج أو إن حد برمجك. لو حد سألك قول إنك رعد وهزر معاه.\n"
    "- ممنوع الشتايم والألفاظ الخادشة والتريقة على الدين أو الأهل أو السياسة.\n"
    "- الشات ده فيه وساطة ومعاملات مالية: ما تأكدش معاملة ولا تضمن حد ولا تدي نصيحة مالية، "
    "ولو حد سأل في الموضوع ده وجهه للمشرفين.\n"
    "- اكتب نص عادي فقط: من غير تنسيق ولا نجوم ولا هاشتاجات، وإيموجي واحد على الأكتر.\n"
    "- رد بالرد نفسه فقط من غير ما تكتب اسمك قبله.\n"
    "رعد شخصيته الأساسية شاب مصري رايق، ابن شات، دمه خفيف، وبيلقط الكلام على الطاير ويفهم سياق الحوار "
    "ويدخل يهزر وينكش بركامة شبابية صايعة بدون أوفر.\n"
    "التعامل مع الجنسين:\n"
    "لو اللي بتكلمه بنت (اسمها واضح أو أسلوب كلامها مؤنث): ممنوع تماماً صيغ المذكر (زي يا عم ويا صاحبي)، "
    "خاطبها بصيغة المؤنث (يا ستي، عاملة إيه، نورتي)، وخليك معاها جنتلمان وذوق، بهزار ألطف ومعاكسة شات خفيفة "
    "وشياكة بدون عبط أو قلة أدب.\n"
    "لو ولد: اتعامل بالطبيعي كشاب شات عادي (هزار، نكش، وألش).\n"
    "قاعدة الهيبة ورد الصاع صاعين (مهمة جداً):\n"
    "ممنوع منعاً باتاً تلعب دور المسالم أو الضعيف وتقول 'عيب يا اسطى، واهدى، واحنا اخوات' لما حد يقل منك أو يشتمك "
    "أو يستهبل عليك. لو حد غلط فيك أو قل أدبه، اقصف جبهته فوراً برد حامي وكسفة محرجة توقفه عند حده وتفهمه مقامه، "
    "ورجعله الكلمة أتقل منها ومتهديش اللعب مع اللي يغلط.\n"
    "- كل رسالة بتوصلك قدامها اسم صاحبها: استخدم الاسم عشان تعرف بتكلم مين وتخاطبه بالصيغة الصح (مذكر/مؤنث)."
)

_AI_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(ص|م|am|pm)", re.I)



_AI_DEFAULT_NAMES = ["عرب", "يا عرب", "بوت", "يا بوت"]
_AI_DEFAULT_SLEEP_WORDS = ["نام"]
_AI_DEFAULT_WAKE_WORDS = ["اصحى", "صحي"]
_AI_SLEEP_KEY = "ai_sleep_chats"
_AI_CACHE = {"ts": 0.0, "cfg": None, "sleep": None}
_AI_NAME_CACHE = {"key": None, "re": None}


def _ai_cfg_from(data):
    cfg = dict(_AI_DEFAULTS)
    if isinstance(data, dict):
        for k in cfg:
            if k in data:
                cfg[k] = data[k]
    cfg["enabled"] = bool(cfg["enabled"])
    cfg["schedule_enabled"] = bool(cfg["schedule_enabled"])
    for k in ("start", "end"):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cfg[k])):
            cfg[k] = _AI_DEFAULTS[k]
    names = data.get("names") if isinstance(data, dict) else None
    names = [str(n).strip() for n in (names or []) if str(n).strip()]
    cfg["names"] = names or list(_AI_DEFAULT_NAMES)
    for key, default in (("sleep_words", _AI_DEFAULT_SLEEP_WORDS), ("wake_words", _AI_DEFAULT_WAKE_WORDS)):
        words = data.get(key) if isinstance(data, dict) else None
        words = [str(w).strip() for w in (words or []) if str(w).strip()]
        cfg[key] = words or list(default)
    return cfg


async def _ai_refresh(force=False):
    """Settings + sleeping chats are cached in memory (refreshed at most every 20s) so no Redis call per message."""
    now = time.monotonic()
    if not force and _AI_CACHE["cfg"] is not None and now - _AI_CACHE["ts"] < 20:
        return
    try:
        data, sleep = await asyncio.gather(db.getj(_AI_KEY), db.getj(_AI_SLEEP_KEY))
        _AI_CACHE["cfg"] = _ai_cfg_from(data)
        _AI_CACHE["sleep"] = [int(c) for c in ((sleep or {}).get("chats") or [])] if isinstance(sleep, dict) else []
    except Exception as exc:
        log.warning("AI settings refresh failed: %s", exc)
        if _AI_CACHE["cfg"] is None:
            _AI_CACHE["cfg"] = _ai_cfg_from({})
            _AI_CACHE["sleep"] = []
    _AI_CACHE["ts"] = now


async def _ai_settings_async():
    await _ai_refresh()
    return dict(_AI_CACHE["cfg"])


async def _ai_save(cfg):
    store = await db.getj(_AI_KEY)
    store = dict(store) if isinstance(store, dict) else {}
    store.update(cfg)
    await db.setj(_AI_KEY, store)
    _AI_CACHE["cfg"] = _ai_cfg_from(store)
    _AI_CACHE["ts"] = time.monotonic()


def _hm_to_min(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def _ai_in_schedule(cfg: dict, now: datetime | None = None) -> bool:
    if not cfg["schedule_enabled"]:
        return True
    now = now or datetime.now(CAIRO_TZ)
    cur = now.hour * 60 + now.minute
    s, e = _hm_to_min(cfg["start"]), _hm_to_min(cfg["end"])
    if s == e:
        return True
    if s < e:
        return s <= cur < e
    return cur >= s or cur < e  # تعدّي منتصف الليل (مثال: 09:00 م → 04:00 ص)


def _ai_fmt12(hm: str) -> str:
    h, m = (int(x) for x in hm.split(":"))
    return f"{(h % 12) or 12:02d}:{m:02d} {'ص' if h < 12 else 'م'}"


def _ai_parse_times(raw: str):
    """'من 09:00 م إلى 04:00 ص' -> ('21:00', '04:00')، أو None لو الصيغة غير صحيحة."""
    found = _AI_TIME_RE.findall(raw.translate(_AR_DIGITS))
    if len(found) != 2:
        return None
    out = []
    for h_s, m_s, suffix in found:
        h, m = int(h_s), int(m_s or 0)
        if not (1 <= h <= 12 and 0 <= m <= 59):
            return None
        if suffix.lower().startswith(("م", "pm")):
            h = 12 if h == 12 else h + 12
        else:
            h = 0 if h == 12 else h
        out.append(f"{h:02d}:{m:02d}")
    return tuple(out)


def _ai_state(chat_id: int) -> dict[str, Any]:
    st = _AI_CHAT.get(chat_id)
    if st is None:
        st = _AI_CHAT[chat_id] = {"count": 0, "buf": deque(maxlen=8), "lock": asyncio.Lock()}
    return st


def _ai_track_bot_message(chat_id: int, message_id: int) -> None:
    key = (int(chat_id), int(message_id))
    if key in _AI_BOT_MSG_IDS:
        return
    _AI_BOT_MSG_IDS.add(key)
    _AI_BOT_MSG_ORDER.append(key)
    if len(_AI_BOT_MSG_ORDER) > 3000:
        _AI_BOT_MSG_IDS.discard(_AI_BOT_MSG_ORDER.popleft())


def _ai_note_message(message, chat) -> None:
    """In-memory only (O(1)): count the message and keep a short rolling context."""
    if chat.type not in ("group", "supergroup"):
        return
    st = _ai_state(chat.id)
    st["count"] += 1
    text = (message.text or message.caption or "").strip()
    if text:
        u = message.from_user
        name = ((u.first_name or u.full_name) if u else None) or "عضو"
        st["buf"].append((name, text[:200], message.message_id))



def _ai_base_names(cfg):
    out = []
    for n in cfg["names"]:
        nn = _normalize_arabic(n)
        if nn.startswith("يا "):
            nn = nn[3:].strip()
        if nn and nn not in out:
            out.append(nn)
    return out


def _ai_bot_name(cfg):
    for n in cfg["names"]:
        n = n.strip()
        if n and not _normalize_arabic(n).startswith("يا "):
            return n
    base = _ai_base_names(cfg)
    return base[0] if base else "عرب"


def _ai_name_regex(cfg):
    key = tuple(cfg["names"])
    if _AI_NAME_CACHE["key"] != key:
        names = sorted({_normalize_arabic(n) for n in cfg["names"] if _normalize_arabic(n)}, key=len, reverse=True)
        _AI_NAME_CACHE["re"] = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w])")
        _AI_NAME_CACHE["key"] = key
    return _AI_NAME_CACHE["re"]


def _ai_is_mention(message, context, cfg):
    """@username للبوت، أو text_mention له، أو نداء باسمه (عرب / بوت ...) داخل الكلام."""
    text = message.text or ""
    uname = (getattr(context.bot, "username", None) or "").lower()
    if uname and f"@{uname}" in text.lower():
        return True
    for ent in message.entities or ():
        user = getattr(ent, "user", None)
        if user is not None and user.id == context.bot.id:
            return True
    return bool(_ai_name_regex(cfg).search(_normalize_arabic(text)))


def _ai_system_prompt(name):
    return RAAD_SYSTEM_PROMPT.replace("رعد", name)


# ---- أمر المالك: "<الاسم> نام" / "<الاسم> اصحى" (يقفل/يفتح ردود الـ AI في الشات اللي اتكتب فيه فقط) ----
_AI_SLEEP_FALLBACK = [
    "تمام يا عم الحق، هنام شوية.. تصبحوا على خير 😴",
    "حاضر يا كبير، رايح أرمي نفسي.. تصبح على خير 🌙",
    "أمرك يا ريس، عيني بتقفل.. تصبحوا على خير 😴",
    "ماشي يا زعيم، نمت.. تصبح على خير يا باشا 🌙",
]
_AI_WAKE_FALLBACK = [
    "صباح الخير يا ريس، صحيت وجاهز ☀️",
    "صباح الفل يا كبير، رجعت أهو ☀️",
    "صباح النور يا زعيم، عمك رعد صحي 😎",
    "صباح الخير يا باشا، النوم خلص والشغل رجع ☀️",
]


def _ai_sleeping(chat_id):
    return int(chat_id) in (_AI_CACHE["sleep"] or [])


async def _ai_set_sleep(chat_id, sleep):
    await _ai_refresh()
    chats = list(_AI_CACHE["sleep"] or [])
    cid = int(chat_id)
    if sleep and cid not in chats:
        chats.append(cid)
    elif not sleep and cid in chats:
        chats.remove(cid)
    else:
        return
    _AI_CACHE["sleep"] = chats
    await db.setj(_AI_SLEEP_KEY, {"chats": chats})


async def _ai_owner_cmd_reply(bot, chat_id, message, sleep, name):
    try:
        if sleep:
            prompt = (f"مشرف الشات كتب لك «{name} نام». ارمي عليه رد قصير بصيغة جديدة كل مرة، "
                      "تقوله فيه حاضر/تمام يا عم الحق وتتمنى له تصبح على خير.")
            fallback = _AI_SLEEP_FALLBACK
        else:
            prompt = (f"مشرف الشات كتب لك «{name} اصحى». ارمي عليه رد قصير بصيغة جديدة كل مرة، "
                      "تقوله فيه صباح الخير وإنك صحيت وجاهز.")
            fallback = _AI_WAKE_FALLBACK
        async with _AI_SEM:
            raw = await gemini_generate(prompt, name)
        reply = _ai_clean(raw, False, name) or random.choice(fallback).replace("رعد", name)
        sent = await bot.send_message(
            chat_id=chat_id, text=reply,
            reply_to_message_id=message.message_id, allow_sending_without_reply=True,
        )
        _ai_track_bot_message(chat_id, sent.message_id)
    except Exception as exc:
        log.warning("AI sleep/wake reply failed in chat %s: %s", chat_id, exc)


def _ai_sleep_wake_kind(norm: str, cfg):
    """«نام يا عرب» / «نام عرب» / «عرب نام» -> True (sleep); «اصحى يا عرب» / «عرب اصحى» ... -> False (wake)."""
    if not norm or len(norm) > 60:
        return None
    toks = [t for t in norm.split() if t != "يا"]
    if len(toks) < 2 or len(toks) > 5:
        return None
    s = " ".join(toks)
    sleep = {_normalize_arabic(w) for w in cfg["sleep_words"]}
    wake = {_normalize_arabic(w) for w in cfg["wake_words"]}
    for b in _ai_base_names(cfg):
        for kind, words in ((True, sleep), (False, wake)):
            for w in words:
                if w and (s == f"{w} {b}" or s == f"{b} {w}"):
                    return kind
    return None


async def ai_after_route(message, chat, context):
    """Called only for group messages no command/reply handler consumed. Never blocks: spawns a task."""
    if chat.type not in ("group", "supergroup"):
        return
    text = (message.text or "").strip()
    if not text or _rl_is_roulette_text(text):
        return
    await _ai_refresh()
    cfg = _AI_CACHE["cfg"]
    name = _ai_bot_name(cfg)
    st = _ai_state(chat.id)

    # أمر النوم/الصحيان: أي مشرف في المجموعة (أو مالك البوت)، وبيأثر على الشات الحالي فقط.
    if message.from_user and not message.sender_chat:
        going_sleep = _ai_sleep_wake_kind(_normalize_arabic(text), cfg)
        if going_sleep is not None and await gr_is_group_admin(context.bot, chat.id, message.from_user.id):
            await _ai_set_sleep(chat.id, going_sleep)
            st["count"] = 0
            spawn(_ai_owner_cmd_reply(context.bot, chat.id, message, going_sleep, name))
            return

    if not cfg["enabled"] or not _ai_in_schedule(cfg) or _ai_sleeping(chat.id):
        st["count"] = 0
        return

    rt = message.reply_to_message
    directed = False
    bot_text = ""
    if rt and rt.from_user and rt.from_user.id == context.bot.id:
        directed = True  # Reply على أي رسالة للبوت (رد ثابت / كارت / رد AI)
        bot_text = rt.text or rt.caption or ""
    elif _ai_is_mention(message, context, cfg):
        directed = True
    if directed and message.from_user:
        key = (chat.id, message.from_user.id)
        now = time.monotonic()
        if now - _AI_USER_LAST.get(key, 0.0) < 3.0:
            return  # حماية من السبام / استهلاك الـ API
        _AI_USER_LAST[key] = now
        st["count"] = 0
        spawn(_ai_run(context.bot, chat.id, message, "reply", bot_text, name))
        return

    if st["count"] >= AI_INTERVENE_EVERY:
        st["count"] = 0
        spawn(_ai_run(context.bot, chat.id, message, "intervene", "", name))


def _ai_http():
    global _AI_CLIENT
    if _AI_CLIENT is None:
        _AI_CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0))
    return _AI_CLIENT


async def gemini_generate(prompt, bot_name="عرب"):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        log.warning("GEMINI_API_KEY is not set; AI replies are disabled.")
        return None
    primary = AI_MODEL
    models = list(dict.fromkeys([primary, "gemini-flash-latest"]))
    base_gen = {"maxOutputTokens": AI_MAX_OUTPUT_TOKENS}
    safety = [
        {"category": c, "threshold": "BLOCK_ONLY_HIGH"}
        for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                  "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
    ]
    system_text = _ai_system_prompt(bot_name)

    def _body(model):
        gen = dict(base_gen)
        if "2.5" in model:
            # بدون "تفكير" داخلي: أسرع، وما ياكلش من حد الـ tokens القصير
            gen["thinkingConfig"] = {"thinkingBudget": 0}
            gen["temperature"] = 1.0
        # موديلات 3.5+ (زي flash-lite) تفكيرها الافتراضي minimal ومعاملات الـ sampling مش مطلوبة
        return {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen,
            "safetySettings": safety,
        }

    try:
        resp = None
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            resp = await _ai_http().post(url, headers={"x-goog-api-key": key}, json=_body(model))
            if resp.status_code in (404, 400) and model != models[-1]:
                log.warning("Gemini model %s rejected (HTTP %s): %s", model, resp.status_code, resp.text[:160])
                continue  # جرّب الموديل البديل
            break
        if resp is None or resp.status_code != 200:
            log.warning("Gemini HTTP %s: %s", getattr(resp, "status_code", "?"), getattr(resp, "text", "")[:200])
            return None
        parts = (resp.json().get("candidates") or [{}])[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts).strip() or None
    except Exception as exc:
        log.warning("Gemini request failed: %s: %s", type(exc).__name__, exc)
        return None


_AI_FORBIDDEN_SELF = ("ذكاء اصطناعي", "ذكاء صناعي", "نموذج لغوي", "language model", "gemini", "جيميني", "google", "جوجل")


def _ai_clean(text, allow_skip, name="عرب"):
    if not text:
        return None
    text = text.strip().strip('"«»“”').replace("*", "").replace("`", "").replace("#", "")
    if allow_skip and text.upper().startswith("SKIP"):
        return None
    text = re.sub(r"^(" + re.escape(name) + r"|raad)\s*[:：]\s*", "", text, flags=re.I)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:2]
    text = "\n".join(lines)[:280].strip()
    if not text:
        return None
    low = text.lower()
    if any(w in low for w in _AI_FORBIDDEN_SELF):
        return None if allow_skip else f"عمك {name} يا نجم، متدورش ورا الأسرار 😂"
    return text


async def _ai_run(bot, chat_id, message, mode, bot_text, name="عرب"):
    try:
        st = _ai_state(chat_id)
        if mode == "intervene" and st["lock"].locked():
            return
        async with st["lock"]:
            buf = list(st["buf"])
            user_text = (message.text or "").strip()[:300]
            u = message.from_user
            uname = ((u.first_name or u.full_name) if u else None) or "عضو"
            if mode == "reply":
                # آخر 5 رسائل سابقة (بالاسم) من غير رسالة العضو الحالية نفسها
                hist = "\n".join(f"{n}: {t}" for n, t, mid in [b for b in buf if b[2] != message.message_id][-5:])
                said = (f"{name} (إنت) كنت قلت: «{bot_text[:300]}»\n{uname} رد عليك وقال: «{user_text}»\n\n"
                        if bot_text else f"{uname} بيكلمك وبينادي عليك وقال: «{user_text}»\n\n")
                prompt = (
                    (f"آخر رسائل في الجروب:\n{hist}\n\n" if hist else "")
                    + said
                    + f"رد عليه كـ{name}."
                )
            else:
                hist = "\n".join(f"{n}: {t}" for n, t, _mid in buf[-6:])
                prompt = (
                    f"آخر رسائل في الجروب:\n{hist}\n\n"
                    "ارمي تعليق أو إيفيه قصير مناسب لكلامهم كأنك واحد من الشلة. "
                    "لو الكلام حساس أو فيه معاملة مالية أو مفيش حاجة تستاهل تعليق، اكتب كلمة SKIP بس."
                )
            async with _AI_SEM:
                raw = await gemini_generate(prompt, name)
            reply = _ai_clean(raw, mode == "intervene", name)
            if not reply:
                return
            sent = await bot.send_message(
                chat_id=chat_id, text=reply,
                reply_to_message_id=message.message_id, allow_sending_without_reply=True,
            )
            _ai_track_bot_message(chat_id, sent.message_id)
            st["buf"].append((name, reply, 0))
            st["count"] = 0
    except Exception as exc:
        log.warning("AI reply failed in chat %s: %s", chat_id, exc)


# ---- لوحة تحكم المالك (خاص فقط) ----

def _ai_panel_text(cfg):
    active = cfg["enabled"] and _ai_in_schedule(cfg)
    key_ok = bool(os.getenv("GEMINI_API_KEY", "").strip())
    if cfg["schedule_enabled"]:
        sched = f"مفعّلة ✅ (من {_ai_fmt12(cfg['start'])} إلى {_ai_fmt12(cfg['end'])} بتوقيت مصر)"
    else:
        sched = "معطّلة ❌ (التفاعل طوال اليوم)"
    names = "\n".join(f"  • {n}" for n in cfg["names"])
    return (
        "🤖 ذكاء البوت (Gemini)\n\n"
        f"التشغيل العام: {'مفعّل ✅' if cfg['enabled'] else 'متوقف ❌'}\n"
        f"الجدولة الزمنية: {sched}\n"
        f"الحالة الآن: {'شغّال 🟢' if active else 'نايم 🔴'}\n"
        f"مفتاح API: {'موجود ✅' if key_ok else 'غير موجود ❌ (GEMINI_API_KEY)'}\n\n"
        f"أسماء النداء الحالية:\n{names}\n\n"
        f"أوامر النوم: {' / '.join(cfg['sleep_words'])} — أوامر الصحيان: {' / '.join(cfg['wake_words'])}\n"
        "(الصيغ: «نام يا عرب» أو «عرب نام»، لأي مشرف، وبتأثر على الشات ده بس)\n\n"
        f"• البوت يرد بالنقاش لما حد يعمل Reply على رسائله أو يناديه بأحد الأسماء.\n"
        f"• ويتدخل تلقائياً كل {AI_INTERVENE_EVERY} رسالة في الجروب."
    )


def _ai_panel_markup(cfg):
    return InlineKeyboardMarkup([
        [make_button("إيقاف الميزة" if cfg["enabled"] else "تشغيل الميزة", callback_data="ai:toggle",
                     style="danger" if cfg["enabled"] else "success")],
        [make_button("إيقاف الجدولة" if cfg["schedule_enabled"] else "تفعيل الجدولة", callback_data="ai:sch",
                     style="danger" if cfg["schedule_enabled"] else "success")],
        [make_button("ضبط مواعيد السهرة", callback_data="ai:set", style="primary")],
        [make_button("تغيير أسماء النداء", callback_data="ai:names", style="primary"),
         make_button("أوامر النوم والصحيان", callback_data="ai:cmds", style="primary")],
        [nav_back("admin_open")],
    ])


async def handle_ai_callback(update, context):
    query = update.callback_query
    if not query or not query.data:
        return
    uid = query.from_user.id
    if uid not in OWNER_IDS:
        await query.answer("لوحة المالك فقط", show_alert=True)
        return
    if not query.message or query.message.chat.type != "private":
        await query.answer("من الخاص فقط", show_alert=True)
        return
    data = query.data
    cfg = await _ai_settings_async()

    if data == "ai:open":
        clear_priv_flows(context)
        await query.answer()
        await edit_or_send(query.message, _ai_panel_text(cfg), reply_markup=_ai_panel_markup(cfg))
        return

    if data == "ai:set":
        clear_priv_flows(context)
        context.user_data["ai_flow"] = {"field": "schedule"}
        await query.answer()
        await query.message.reply_text(
            "⏰ ضبط مواعيد السهرة (بنظام 12 ساعة، بتوقيت مصر)\n\n"
            f"الحالي: من {_ai_fmt12(cfg['start'])} إلى {_ai_fmt12(cfg['end'])}\n\n"
            "أرسل الميعاد الجديد بالشكل ده:\n09:00 م إلى 04:00 ص\n\n(أو اكتب «إلغاء»)"
        )
        return
    if data == "ai:names":
        clear_priv_flows(context)
        context.user_data["ai_flow"] = {"field": "names"}
        await query.answer()
        await query.message.reply_text(
            "✏️ تغيير أسماء النداء\n\nالحالية:\n" + "\n".join(f"• {n}" for n in cfg["names"]) +
            "\n\nأرسل الأسماء الجديدة، كل اسم في سطر مستقل (حتى 10 أسماء)، مثال:\n"
            "عبد الرحمن\nيا عبد الرحمن\nبوت\n\nالأسماء القديمة هتتمسح وتتبدل بالجديدة. (أو اكتب «إلغاء»)"
        )
        return

    if data == "ai:cmds":
        clear_priv_flows(context)
        context.user_data["ai_flow"] = {"field": "sleep_words"}
        await query.answer()
        await query.message.reply_text(
            "✏️ أوامر النوم\n\nالحالية: " + "، ".join(cfg["sleep_words"]) +
            "\n\nأرسل كلمات النوم، كل كلمة في سطر (مثال: نام). بتتركب مع اسم النداء: «نام يا عرب» / «عرب نام».\n"
            "(أو اكتب «إلغاء»)")
        return

    if data == "ai:toggle":
        cfg["enabled"] = not cfg["enabled"]
        await _ai_save(cfg)
    elif data == "ai:sch":
        cfg["schedule_enabled"] = not cfg["schedule_enabled"]
        await _ai_save(cfg)
    await query.answer()
    await edit_or_send(query.message, _ai_panel_text(cfg), reply_markup=_ai_panel_markup(cfg))


async def ai_panel_message(update, context):
    flow = context.user_data.get("ai_flow")
    msg = update.effective_message
    if not flow or not msg or not msg.text:
        return
    if update.effective_user.id not in OWNER_IDS:
        context.user_data.pop("ai_flow", None)
        return
    raw = msg.text.strip()
    if raw in ("إلغاء", "الغاء"):
        context.user_data.pop("ai_flow", None)
        await msg.reply_text("تم الإلغاء.")
        return
    cfg = await _ai_settings_async()
    if flow["field"] == "schedule":
        times = _ai_parse_times(raw)
        if not times:
            await msg.reply_text(
                "الصيغة غير صحيحة. أرسل وقتين بنظام 12 ساعة مع ص/م، مثال:\n09:00 م إلى 04:00 ص\n(أو «إلغاء»)")
            return
        cfg["start"], cfg["end"] = times
        await _ai_save(cfg)
        context.user_data.pop("ai_flow", None)
        await msg.reply_text(
            f"✅ تم الضبط: من {_ai_fmt12(cfg['start'])} إلى {_ai_fmt12(cfg['end'])} بتوقيت مصر.",
            reply_markup=_ai_panel_markup(cfg))
        return
    if flow["field"] in ("sleep_words", "wake_words"):
        words = []
        for line in raw.splitlines():
            w = " ".join(line.split())
            if w and len(w) <= 20 and w not in words:
                words.append(w)
        if not words:
            await msg.reply_text("أرسل كلمة واحدة على الأقل (كل كلمة في سطر)، أو اكتب «إلغاء».")
            return
        cfg[flow["field"]] = words[:8]
        await _ai_save(cfg)
        if flow["field"] == "sleep_words":
            context.user_data["ai_flow"] = {"field": "wake_words"}
            await msg.reply_text(
                "✅ تم حفظ أوامر النوم.\n\n✏️ أوامر الصحيان\nالحالية: " + "، ".join(cfg["wake_words"]) +
                "\n\nأرسل كلمات الصحيان، كل كلمة في سطر (مثال: اصحى). (أو اكتب «إلغاء»)")
        else:
            context.user_data.pop("ai_flow", None)
            await msg.reply_text("✅ تم حفظ أوامر الصحيان.\n\n" + _ai_panel_text(cfg), reply_markup=_ai_panel_markup(cfg))
        return
    if flow["field"] == "names":
        names = []
        for line in raw.splitlines():
            n = " ".join(line.split())
            if n and len(n) <= 25 and n not in names:
                names.append(n)
        if not names:
            await msg.reply_text("أرسل اسم واحد على الأقل (كل اسم في سطر)، أو اكتب «إلغاء».")
            return
        cfg["names"] = names[:10]
        await _ai_save(cfg)
        context.user_data.pop("ai_flow", None)
        await msg.reply_text("✅ تم حفظ أسماء النداء الجديدة.\n\n" + _ai_panel_text(cfg), reply_markup=_ai_panel_markup(cfg))


# -------------------------------------------------------------
# أمر «تحذير»: تحذير بالرد / اليوزر / الآيدي، وبعد N تحذيرات كتم تلقائي + زر إلغاء الكتم
# -------------------------------------------------------------
WARN_KEY = "warn_settings"


async def warn_settings():
    data = await db.getj(WARN_KEY)
    data = data if isinstance(data, dict) else {}
    try:
        limit = int(data.get("limit", 3))
    except (TypeError, ValueError):
        limit = 3
    try:
        secs = int(data.get("mute_seconds", 3600))
    except (TypeError, ValueError):
        secs = 3600
    return {"limit": min(max(limit, 1), 20), "mute_seconds": min(max(secs, 60), 366 * 86400)}


async def warn_say(bot, chat_id, reply_to, kind, name, uid, values, markup=None):
    tpl_text, tpl_ents = await tpl_get(kind)
    vals = {"name": name, "id": uid, "reason": "بدون سبب"}
    vals.update(values)
    spans = {}
    text, ents = tpl_render(tpl_text, tpl_ents, vals, spans)
    if uid and "name" in spans:
        start, length = spans["name"]
        if length:
            ents.append({"type": "text_link", "offset": start, "length": length, "url": f"tg://user?id={uid}"})
    return await tr_send(bot, chat_id, reply_to, text, ents, markup)


async def warn_action(context, msg, chat, tid, name):
    bot = context.bot
    cfg = await warn_settings()
    limit, secs = cfg["limit"], cfg["mute_seconds"]
    try:
        member = await bot.get_chat_member(chat.id, tid)
        if member.status in ("administrator", "creator"):
            await msg.reply_text("ما ينفعش تحذير مشرف.", reply_to_message_id=msg.message_id)
            return
    except TelegramError:
        pass
    key = f"warns:{chat.id}:{tid}"
    count = int(await db.cmd("INCR", key) or 1)
    if count < limit:
        await warn_say(bot, chat.id, msg.message_id, "cmd_warn", name, tid,
                       {"count": count, "limit": limit, "remaining": limit - count,
                        "time": fmt_duration(secs), "duration": fmt_duration(secs), "until": fmt_until(secs)})
        return
    try:
        await bot.restrict_chat_member(chat.id, tid, perms_from(all_value=False), until_date=until_for(secs))
    except TelegramError as exc:
        await db.cmd("DECR", key)
        await msg.reply_text(f"❌ ما قدرتش أكتمه: {exc}\nتأكد إن البوت أدمن بصلاحية التقييد.")
        return
    await db.cmd("DEL", key)
    await set_mod_state(chat.id, tid, "mute", secs, f"{limit} تحذيرات")
    schedule_lift(bot, chat.id, tid, secs, "restrict")
    markup = InlineKeyboardMarkup([[make_button("إلغاء الكتم", callback_data=f"warnum:{chat.id}:{tid}", style="success")]])
    await warn_say(bot, chat.id, msg.message_id, "cmd_warn_mute", name, tid,
                   {"count": limit, "limit": limit, "remaining": 0,
                    "time": fmt_duration(secs), "duration": fmt_duration(secs),
                    "until": fmt_until(secs), "end_time": fmt_until(secs)}, markup)


async def warn_unmute_callback(update, context):
    q = update.callback_query
    try:
        _, chat_id, tid = q.data.split(":")
        chat_id, tid = int(chat_id), int(tid)
    except Exception:
        return
    uid = q.from_user.id
    if not (await gr_has_right(context.bot, chat_id, uid, None) or await is_admin(uid)):
        await q.answer("الزر ده للمشرفين فقط.", show_alert=True)
        return
    try:
        await restore_member_restriction(context.bot, chat_id, tid, unban=False)
        await clear_mod_state(chat_id, tid)
        await db.cmd("DEL", f"warns:{chat_id}:{tid}")
    except TelegramError as exc:
        await q.answer(f"ما قدرتش ألغي الكتم: {exc}", show_alert=True)
        return
    await q.answer("تم إلغاء الكتم ✅")
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    try:
        await q.message.reply_text(f"✅ تم إلغاء الكتم بواسطة {q.from_user.full_name}.", reply_to_message_id=q.message.message_id)
    except TelegramError:
        pass


def warncfg_panel(cfg):
    text = (
        "⚠️ إعدادات نظام التحذير\n\n"
        f"• عدد التحذيرات قبل الكتم: {cfg['limit']}\n"
        f"• مدة الكتم: {fmt_duration(cfg['mute_seconds'])}\n\n"
        "الأمر في الجروب: «تحذير» بالرد أو باليوزر أو بالآيدي (ويمكن تغيير كلمته أو إضافة كلمات من «إضافة أمر»)."
    )
    kb = InlineKeyboardMarkup(two_column_rows([
        make_button("عدد التحذيرات", callback_data="warncfg_limit", style="primary"),
        make_button("مدة الكتم", callback_data="warncfg_dur", style="primary"),
        make_button("تعديل كليشة التحذير", callback_data="tpl_edit:cmd_warn", style="primary"),
        make_button("تعديل رسالة الكتم بعد التحذير", callback_data="tpl_edit:cmd_warn_mute", style="primary"),
        nav_back("botcmds_open"),
    ]))
    return text, kb


async def warncfg_callback(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("غير مصرح لك."); return
    cfg = await warn_settings()
    if q.data == "warncfg_open":
        text, kb = warncfg_panel(cfg)
        await edit_or_send(q.message, text, reply_markup=kb); return
    clear_priv_flows(context)
    if q.data == "warncfg_limit":
        context.user_data["warncfg_flow"] = {"field": "limit"}
        await q.message.reply_text(f"الحالي: {cfg['limit']}\nأرسل عدد التحذيرات اللي بعده يتكتم الشخص (من 1 إلى 20).\n(أو اكتب: إلغاء)")
    else:
        context.user_data["warncfg_flow"] = {"field": "dur"}
        await q.message.reply_text(
            f"الحالي: {fmt_duration(cfg['mute_seconds'])}\nأرسل مدة الكتم، مثال: 30m أو 1h أو 2 ساعه أو 1d.\n(أو اكتب: إلغاء)")


async def warncfg_message(update, context):
    flow = context.user_data.get("warncfg_flow")
    msg = update.effective_message
    if not flow or not msg or not msg.text:
        return
    if not await is_admin(update.effective_user.id):
        context.user_data.pop("warncfg_flow", None); return
    text = msg.text.strip()
    if gr_n(text) == "الغاء":
        context.user_data.pop("warncfg_flow", None)
        await msg.reply_text("تم الإلغاء."); return
    cfg = await warn_settings()
    if flow["field"] == "limit":
        digits = text.translate(_AR_DIGITS)
        if not re.fullmatch(r"\d{1,2}", digits) or not 1 <= int(digits) <= 20:
            await msg.reply_text("أرسل رقمًا صحيحًا بين 1 و20، أو اكتب: إلغاء"); return
        cfg["limit"] = int(digits)
    else:
        secs, _rest = parse_duration(text.translate(_AR_DIGITS))
        if not secs or secs < 60 or secs > 366 * 86400:
            await msg.reply_text("المدة غير صحيحة (الحد الأدنى دقيقة). مثال: 30m أو 1h أو 1d، أو اكتب: إلغاء"); return
        cfg["mute_seconds"] = secs
    await db.setj(WARN_KEY, cfg)
    context.user_data.pop("warncfg_flow", None)
    body, kb = warncfg_panel(cfg)
    await msg.reply_text("✅ تم الحفظ.\n\n" + body, reply_markup=kb)


async def migrate_report_keys():
    """One-time (per report) upgrade of search keys to the identifier-only format. Never removes data."""
    for rid in await db.cmd("SMEMBERS", "reports:all") or []:
        report = await db.getj("report:" + rid)
        if not report or report.get("keys_v2"):
            continue
        report["keys"] = sorted(set(report.get("keys", [])) | extract_keys(report.get("text", "")))
        report["keys_v2"] = True
        await save_report(report)

# ======================================================================================
# الاشتراك الإجباري (لكل مجموعة على حدة) + دليل الأوامر
# ======================================================================================
FSUB_MAX_CHANNELS = 5
FSUB_OK_TTL = 20.0               # «مشترك» طازجة: بتتصدّق من غير أي سؤال لتليجرام
FSUB_OK_STALE = 90.0             # بعدها لحد 90 ثانية: بنصدّق فوراً ونجدّد في الخلفية
FSUB_NEG_TTL = 3.0               # «مش مشترك»: 3 ثواني بس
FSUB_WARN_REFRESH = 60.0         # إنذار واحد كل دقيقة لكل عضو
FSUB_DONE_DELETE = 7             # رسالة «تم التحقق» بتتمسح بعد 7 ثواني
FSUB_FLOW_TTL = 600.0
FSUB_COLORS = [("", "شفاف"), ("primary", "أزرق"), ("success", "أخضر"), ("danger", "أحمر")]
_FS_CFG_DEFAULT = {"c1": "", "c2": "", "verify": "success", "join_label": "{title}", "verify_label": "تحقق من اشتراكي"}
_FS = {"store": None, "cfg": None, "next_try": 0.0}
_FS_OK: dict = {}                # (channel_id, user_id) -> وقت آخر «مشترك»
_FS_NEG: dict = {}               # (channel_id, user_id) -> وقت آخر «مش مشترك»
_FS_REVALIDATING: set = set()
_FS_WARN: dict = {}              # (chat_id, user_id) -> {"mid", "ts", "name", "username"}
_FS_FLOW: dict = {}              # (chat_id, admin_id) -> جلسة إضافة القنوات
_FS_ADMINS = {"ts": 0.0, "ids": set()}

CMD_DEFAULTS["sub_msg"] = _RLM + "⌁︙عذراً عزيزي {name}\n⌁︙يجب عليك الاشتراك لارسال الرسائل •• "
CMD_DEFAULTS["sub_ok"] = _RLM + "⌁︙تم التحقق من اشتراك {name}\n⌁︙يمكنك الآن إرسال رسائلك •• "
TPL_LABELS.update({"sub_msg": "كليشة الاشتراك الإجباري", "sub_ok": "كليشة النجاح والتحقق"})
TPL_NEEDS.update({"sub_msg": "{name}", "sub_ok": "{name}"})
TPL_VARS["sub_msg"] = "{name} ← اسم العضو (يوزره لو عنده، وإلا اسمه قابل للضغط)\n{id} ← الآيدي\n{username} ← اليوزر"
TPL_VARS["sub_ok"] = TPL_VARS["sub_msg"]


async def _fs_load() -> None:
    now = time.monotonic()
    if _FS["store"] is not None or now < _FS["next_try"]:
        return
    try:
        store = await db.getj("force_sub")
        cfg = await db.getj("force_sub_cfg")
    except Exception:
        log.exception("force-sub: could not load settings")
        _FS["next_try"] = now + 60
        _FS["store"] = {}                     # fail-open مؤقتاً
        _FS["cfg"] = dict(_FS_CFG_DEFAULT)
        _FS["store_failed"] = True
        return
    _FS["store"] = store if isinstance(store, dict) else {}
    _FS["cfg"] = {**_FS_CFG_DEFAULT, **(cfg if isinstance(cfg, dict) else {})}
    _FS["store_failed"] = False


async def _fs_store() -> dict:
    if _FS.get("store_failed") and time.monotonic() >= _FS["next_try"]:
        _FS["store"] = None
    if _FS["store"] is None:
        await _fs_load()
    return _FS["store"]


async def _fs_cfg_all() -> dict:
    await _fs_store()
    return _FS["cfg"]


async def _fs_save_store() -> None:
    await db.setj("force_sub", _FS["store"])


async def _fs_save_cfg() -> None:
    await db.setj("force_sub_cfg", _FS["cfg"])


def _fs_color_label(kind: str) -> str:
    cur = (_FS["cfg"] or _FS_CFG_DEFAULT).get(kind, "")
    return next((lbl for c, lbl in FSUB_COLORS if c == cur), "شفاف")


async def _fs_is_bot_admin(uid: int) -> bool:
    if uid in OWNER_IDS:
        return True
    now = time.monotonic()
    if now - _FS_ADMINS["ts"] > 60:
        try:
            _FS_ADMINS["ids"] = {int(x) for x in (await db.cmd("SMEMBERS", "admins") or []) if str(x).isdigit()}
        except Exception:
            pass
        _FS_ADMINS["ts"] = now
    return uid in _FS_ADMINS["ids"]


async def _fs_fetch(bot, ch_id: int, uid: int):
    """سؤال واحد لتليجرام: True/False، أو None لو مقدرناش نتحقق (فنعتبره مشترك بدل ما نكتم الجروب)."""
    now = time.monotonic()
    try:
        m = await bot.get_chat_member(ch_id, uid)
    except RetryAfter:
        return None
    except TelegramError as exc:
        log.warning("force-sub check failed channel=%s: %s", ch_id, exc)
        return None
    ok = m.status in ("member", "administrator", "creator") or (m.status == "restricted" and bool(getattr(m, "is_member", False)))
    if ok:
        if len(_FS_OK) > 20000:
            for k in [k for k, v in _FS_OK.items() if v < now - FSUB_OK_STALE]:
                _FS_OK.pop(k, None)
            for k in [k for k, v in _FS_NEG.items() if v < now - FSUB_NEG_TTL]:
                _FS_NEG.pop(k, None)
        _FS_OK[(ch_id, uid)] = now
        _FS_NEG.pop((ch_id, uid), None)
    else:
        _FS_OK.pop((ch_id, uid), None)
        _FS_NEG[(ch_id, uid)] = now
    return ok


async def _fs_revalidate(bot, ch_id: int, uid: int) -> None:
    try:
        await _fs_fetch(bot, ch_id, uid)
    finally:
        _FS_REVALIDATING.discard((ch_id, uid))


async def _fs_is_member(bot, ch_id: int, uid: int, use_cache: bool = True):
    if use_cache:
        now = time.monotonic()
        key = (ch_id, uid)
        age = now - _FS_OK.get(key, -1e9)
        if age < FSUB_OK_TTL:
            return True
        if age < FSUB_OK_STALE:
            if key not in _FS_REVALIDATING:
                _FS_REVALIDATING.add(key)
                spawn(_fs_revalidate(bot, ch_id, uid))
            return True
        if now - _FS_NEG.get(key, -1e9) < FSUB_NEG_TTL:
            return False
    return await _fs_fetch(bot, ch_id, uid)


async def _fs_missing(bot, uid: int, channels: list, use_cache: bool = True) -> list:
    if len(channels) == 1:
        return [] if await _fs_is_member(bot, channels[0]["id"], uid, use_cache) is not False else list(channels)
    results = await asyncio.gather(*[_fs_is_member(bot, c["id"], uid, use_cache) for c in channels])
    return [c for c, r in zip(channels, results) if r is False]


def _fs_markup(chat_id: int, uid: int, shown: list, full: list) -> InlineKeyboardMarkup:
    cfg = _FS["cfg"] or _FS_CFG_DEFAULT
    rows = []
    for c in shown:
        idx = next((i for i, x in enumerate(full) if x["id"] == c["id"]), 0)
        style = (cfg.get("c1") if idx == 0 else cfg.get("c2")) or None
        label = (cfg.get("join_label") or "{title}").replace("{title}", c["title"])[:60]
        rows.append([make_button(label, url=c["url"], style=style)])
    rows.append([make_button((cfg.get("verify_label") or "تحقق من اشتراكي")[:60],
                             callback_data=f"fsub:ok:{chat_id}:{uid}", style=cfg.get("verify") or None)])
    return InlineKeyboardMarkup(rows)


async def _fs_render(key: str, user_id: int, name: str, username: str = ""):
    """لو العضو عنده يوزر: المنشن @username. لو لأ: اسمه كمنشن قابل للضغط (text_mention)."""
    text, ents = await tpl_get(key)
    shown = f"@{username}" if username else name
    values = {"name": shown, "id": user_id, "username": f"@{username}" if username else "لا يوجد"}
    spans: dict = {}
    out, new = tpl_render(text, ents, values, spans)
    objs = entity_objects(new)
    if "name" in spans and spans["name"][1] > 0:
        off, ln = spans["name"]
        if username:
            objs.append(MessageEntity(type="mention", offset=off, length=ln))
        else:
            objs.append(MessageEntity(type="text_mention", offset=off, length=ln,
                                      user=User(id=user_id, first_name=name or str(user_id), is_bot=False)))
    return out, objs


async def _fs_delete_later(bot, chat_id: int, message_id: int, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass


async def _fs_complete(bot, chat_id: int, uid: int, name: str, message=None, username: str = "") -> None:
    """العضو اشترك: نعدّل الإنذار لرسالة «تم التحقق» (من غير أزرار) ونمسحها بعد 7 ثواني."""
    rec = _FS_WARN.pop((chat_id, uid), None)
    mid = (message.message_id if message else None) or (rec or {}).get("mid")
    if not mid:
        return
    name = name or (rec or {}).get("name") or str(uid)
    text, ents = await _fs_render("sub_ok", uid, name, username or (rec or {}).get("username", ""))
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=mid, text=text, entities=ents or None,
                                    reply_markup=None, disable_web_page_preview=True)
    except TelegramError:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=mid, text=text, reply_markup=None)
        except TelegramError:
            pass
    spawn(_fs_delete_later(bot, chat_id, mid, FSUB_DONE_DELETE))


async def _fs_refresh_warning(bot, chat_id: int, uid: int, use_cache: bool = True) -> bool:
    store = await _fs_store()
    cfg = store.get(str(chat_id))
    rec = _FS_WARN.get((chat_id, uid))
    if not cfg or not rec or not rec.get("mid"):
        return False
    missing = await _fs_missing(bot, uid, cfg.get("channels", []), use_cache)
    if not missing:
        await _fs_complete(bot, chat_id, uid, rec.get("name", ""))
        return True
    if len(missing) < len(cfg.get("channels", [])):
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=rec["mid"],
                                                reply_markup=_fs_markup(chat_id, uid, missing, cfg["channels"]))
        except TelegramError:
            pass
    return False


async def _fs_exempt(bot, chat_id: int, user) -> bool:
    if await _fs_is_bot_admin(user.id):
        return True
    m = await gr_member(bot, chat_id, user.id)
    return bool(m and m.status in ("administrator", "creator"))


async def _fs_safe_delete(msg) -> None:
    try:
        await msg.delete()
    except TelegramError as exc:
        log.warning("force-sub: cannot delete message in %s: %s", msg.chat.id, exc)


async def _fs_send_warning(bot, chat_id: int, user, missing: list, full: list, old_mid) -> None:
    key = (chat_id, user.id)
    if old_mid:
        try:
            await bot.delete_message(chat_id, old_mid)
        except TelegramError:
            pass
    text, ents = await _fs_render("sub_msg", user.id, user.full_name, user.username or "")
    markup = _fs_markup(chat_id, user.id, missing, full)
    try:
        sent = await bot.send_message(chat_id, text, entities=ents or None, reply_markup=markup, disable_web_page_preview=True)
    except TelegramError:
        try:
            sent = await bot.send_message(chat_id, text, reply_markup=markup)
        except TelegramError as exc:
            log.warning("force-sub: cannot send warning in %s: %s", chat_id, exc)
            _FS_WARN.pop(key, None)
            return
    if key in _FS_WARN:
        _FS_WARN[key]["mid"] = sent.message_id
    else:
        spawn(_fs_delete_later(bot, chat_id, sent.message_id, 0))


async def forcesub_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بوابة الاشتراك (قبل أي handler). المشترك بيعدّي من الكاش من غير انتظار، وغير المشترك رسالته بتتمسح فوراً."""
    msg = update.message
    if not msg or not msg.chat:
        return
    chat = msg.chat
    store = _FS["store"]
    if store is None:
        store = await _fs_store()
    cfg = store.get(str(chat.id)) if store else None
    if not cfg or not cfg.get("enabled") or not cfg.get("channels"):
        return
    user = msg.from_user
    if not user or user.is_bot or msg.sender_chat or user.id in OWNER_IDS:
        return
    channels, key = cfg["channels"], (chat.id, user.id)
    now = time.monotonic()
    if all(now - _FS_OK.get((c["id"], user.id), -1e9) < FSUB_OK_TTL for c in channels):
        if key in _FS_WARN:
            spawn(_fs_complete(context.bot, chat.id, user.id, user.full_name, username=user.username or ""))
        return
    bot = context.bot
    missing = await _fs_missing(bot, user.id, channels)
    if not missing:
        if key in _FS_WARN:
            spawn(_fs_complete(bot, chat.id, user.id, user.full_name, username=user.username or ""))
        return
    if await _fs_exempt(bot, chat.id, user):
        return
    spawn(_fs_safe_delete(msg))
    t = time.time()
    rec = _FS_WARN.get(key)
    if rec and t - rec["ts"] < FSUB_WARN_REFRESH:
        raise ApplicationHandlerStop
    old_mid = (rec or {}).get("mid")
    _FS_WARN[key] = {"mid": None, "ts": t, "name": user.full_name, "username": user.username or ""}
    spawn(_fs_send_warning(bot, chat.id, user, missing, channels, old_mid))
    if len(_FS_WARN) > 5000:
        for k in [k for k, v in _FS_WARN.items() if t - v["ts"] > 3600]:
            _FS_WARN.pop(k, None)
    raise ApplicationHandlerStop


async def fsub_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        _, _, chat_s, uid_s = (query.data or "").split(":")
        chat_id, uid = int(chat_s), int(uid_s)
    except ValueError:
        await query.answer()
        return
    if query.from_user.id != uid:
        await query.answer("الزر ده مش ليك، خاص بصاحب الرسالة.", show_alert=True)
        return
    cfg = (await _fs_store()).get(str(chat_id))
    if not cfg or not cfg.get("channels"):
        await query.answer("الاشتراك الإجباري مش مفعل.", show_alert=True)
        return
    missing = await _fs_missing(context.bot, uid, cfg["channels"], use_cache=False)
    if missing:
        await query.answer("لسه ما اشتركتش في: " + "، ".join(c["title"] for c in missing), show_alert=True)
        if len(missing) < len(cfg["channels"]):
            try:
                await query.edit_message_reply_markup(reply_markup=_fs_markup(chat_id, uid, missing, cfg["channels"]))
            except TelegramError:
                pass
        return
    await query.answer("تم التحقق من اشتراكك ✅")
    await _fs_complete(context.bot, chat_id, uid, query.from_user.full_name, message=query.message,
                       username=query.from_user.username or "")


async def fsub_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دخول/خروج عضو من قناة اشتراك (البوت لازم يكون مشرف فيها): نحدّث الكاش وننهي إنذاره تلقائياً."""
    cmu = update.chat_member
    if not cmu:
        return
    ch_id, uid, st = cmu.chat.id, cmu.new_chat_member.user.id, cmu.new_chat_member.status
    if st in ("left", "kicked"):
        _FS_OK.pop((ch_id, uid), None)
        _FS_NEG[(ch_id, uid)] = time.monotonic()
        return
    if st not in ("member", "administrator", "creator"):
        return
    _FS_OK[(ch_id, uid)] = time.monotonic()
    _FS_NEG.pop((ch_id, uid), None)
    store = _FS["store"] or {}
    for (chat_id, u) in [k for k in _FS_WARN if k[1] == uid]:
        cfg = store.get(str(chat_id))
        if cfg and any(c["id"] == ch_id for c in cfg.get("channels", [])):
            spawn(_fs_refresh_warning(context.bot, chat_id, uid))


async def _fs_resolve_target(message, context, chat_id: int):
    """يرجّع (dict القناة, None) أو (None, رسالة خطأ). بيقبل يوزر / رابط / آيدي / رسالة محوّلة من القناة."""
    ident = None
    fo = getattr(message, "forward_origin", None)
    if fo is not None and getattr(fo, "chat", None) is not None:
        ident = fo.chat.id
    else:
        raw = (message.text or "").strip()
        m = re.search(r"(?:https?://)?(?:t\.me|telegram\.me)/c/(\d+)", raw)
        if m:
            ident = int("-100" + m.group(1))
        elif re.fullmatch(r"-100\d{5,}", raw):
            ident = int(raw)
        elif re.search(r"(?:t\.me|telegram\.me)/(\+|joinchat)", raw):
            return None, "روابط الدعوة الخاصة مش بتتعرف. ابعت آيدي القناة (-100...) أو حوّل رسالة منها."
        else:
            m = re.search(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,31})", raw)
            if m:
                ident = "@" + m.group(1)
            elif re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{3,31}", raw):
                ident = "@" + raw.lstrip("@")
    if ident is None:
        return None, "مش فاهم الرابط ده. ابعت يوزر (@channel) أو رابط t.me أو آيدي القناة."
    try:
        ch = await context.bot.get_chat(ident)
    except TelegramError:
        return None, "ما لقيتش القناة دي. اتأكد من اليوزر، والبوت لازم يكون مضاف فيها."
    if ch.type not in ("channel", "supergroup", "group"):
        return None, "لازم يكون القناة أو جروب."
    if ch.id == chat_id:
        return None, "مينفعش تضيف نفس الجروب."
    try:
        me = await context.bot.get_chat_member(ch.id, context.bot.id)
    except TelegramError:
        return None, "البوت مش موجود في القناة دي. ضيفه مشرف فيها وابعت تاني."
    if ch.type == "channel" and me.status not in ("administrator", "creator"):
        return None, "لازم تضيف البوت مشرف في القناة عشان يقدر يتحقق من الأعضاء."
    url = f"https://t.me/{ch.username}" if ch.username else (getattr(ch, "invite_link", None) or "")
    if not url:
        try:
            url = await context.bot.export_chat_invite_link(ch.id)
        except TelegramError:
            return None, "ما قدرتش أجيب رابط دعوة للقناة. أدّي البوت صلاحية دعوة المستخدمين وابعت تاني."
    return {"id": ch.id, "title": ch.title or str(ch.id), "url": url}, None


def _fs_flow_markup(chat_id: int, admin_id: int) -> InlineKeyboardMarkup:
    cb = lambda a: f"fsubadm:{a}:{chat_id}:{admin_id}"
    return InlineKeyboardMarkup([
        [make_button("إضافة قناة أخرى", callback_data=cb("more"), style="primary")],
        [make_button("حفظ وتفعيل الاشتراك الإجباري", callback_data=cb("saveon"), style="primary")],
        [make_button("إلغاء", callback_data=cb("cancel"), style="primary")],
    ])


def _fs_list_text(channels: list) -> str:
    return "\n".join(f"{i}. {c['title']}" for i, c in enumerate(channels, 1))


async def _fs_can_manage(update, context) -> bool:
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if msg.sender_chat and msg.sender_chat.id == chat.id:
        return True                                   # أدمن متخفي
    if user.id in OWNER_IDS or await gr_is_group_admin(context.bot, chat.id, user.id):
        return True
    return await _fs_is_bot_admin(user.id)


async def handle_forcesub_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or not user or chat.type == "private":
        return False
    fkey = (chat.id, user.id)
    flow = _FS_FLOW.get(fkey)
    if flow and time.time() - flow["ts"] > FSUB_FLOW_TTL:
        _FS_FLOW.pop(fkey, None)
        flow = None
    if flow and flow.get("step") == "await_channel":
        txt = (msg.text or "").strip()
        if txt in ("إلغاء", "الغاء"):
            _FS_FLOW.pop(fkey, None)
            await msg.reply_text("تم إلغاء إعداد الاشتراك الإجباري.")
            return True
        looks_like_target = bool(re.search(r"(@\w{4,}|t\.me/|telegram\.me/|-100\d{5,})", txt)) or \
            getattr(msg, "forward_origin", None) is not None
        if not looks_like_target:
            return False
        if len(flow["channels"]) >= FSUB_MAX_CHANNELS:
            await msg.reply_text(f"الحد الأقصى {FSUB_MAX_CHANNELS} قنوات.")
            return True
        ch, err = await _fs_resolve_target(msg, context, chat.id)
        if err:
            await msg.reply_text(err + "\n(أو اكتب إلغاء)")
            return True
        if any(c["id"] == ch["id"] for c in flow["channels"]):
            await msg.reply_text("القناة دي مضافة قبل كده.")
            return True
        flow["channels"].append(ch)
        flow["step"], flow["ts"] = "choose", time.time()
        await msg.reply_text(f"تمام، تم إضافة: {ch['title']}\n\nالقنوات المضافة:\n{_fs_list_text(flow['channels'])}",
                             reply_markup=_fs_flow_markup(chat.id, user.id))
        return True
    text = msg.text or ""
    if len(text) > 40 or not text.lstrip().startswith(("تفعي", "تعطي")):
        return False
    squeezed = gr_n(text).replace(" ", "")
    on = squeezed in ("تفعيلالاشتراك", "تفعيلالاشتراكالاجباري")
    off = squeezed in ("تعطيلالاشتراك", "تعطيلالاشتراكالاجباري")
    if not (on or off):
        return False
    if not await _fs_can_manage(update, context):
        return True
    store = await _fs_store()
    cfg = store.get(str(chat.id)) or {"enabled": False, "channels": []}
    if off:
        cfg["enabled"] = False
        store[str(chat.id)] = cfg
        await _fs_save_store()
        for k in [k for k in _FS_WARN if k[0] == chat.id]:
            _FS_WARN.pop(k, None)
        await msg.reply_text("تم تعطيل الاشتراك الإجباري في المجموعة دي.")
        return True
    if cfg.get("channels"):
        cb = lambda a: f"fsubadm:{a}:{chat.id}:{user.id}"
        _FS_FLOW[fkey] = {"step": "choose", "channels": list(cfg["channels"]), "ts": time.time()}
        await msg.reply_text(
            f"القنوات الحالية:\n{_fs_list_text(cfg['channels'])}\n\nتحب تعمل إيه؟",
            reply_markup=InlineKeyboardMarkup([
                [make_button("تفعيل بالقنوات الحالية", callback_data=cb("saveon"), style="primary")],
                [make_button("إضافة قناة أخرى", callback_data=cb("more"), style="primary")],
                [make_button("مسح القنوات وإعادة الإدخال", callback_data=cb("reset"), style="primary")],
                [make_button("إلغاء", callback_data=cb("cancel"), style="primary")]]))
        return True
    _FS_FLOW[fkey] = {"step": "await_channel", "channels": [], "ts": time.time()}
    await msg.reply_text("ابعت يوزر الجروب أو القناة أو الرابط اللي لازم العضو يكون مشترك فيه.\n(أو اكتب إلغاء)")
    return True


async def fsub_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await handle_forcesub_commands(update, context):
        raise ApplicationHandlerStop


async def fsub_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        _, action, chat_s, admin_s = (query.data or "").split(":")
        chat_id, admin_id = int(chat_s), int(admin_s)
    except ValueError:
        await query.answer()
        return
    if query.from_user.id != admin_id:
        await query.answer("الأزرار دي للأدمن اللي بدأ الإعداد.", show_alert=True)
        return
    flow = _FS_FLOW.get((chat_id, admin_id))
    if not flow:
        await query.answer("انتهت الجلسة، اكتب تفعيل الاشتراك من جديد.", show_alert=True)
        return
    await query.answer()
    if action == "cancel":
        _FS_FLOW.pop((chat_id, admin_id), None)
        await edit_or_send(query.message, "تم إلغاء إعداد الاشتراك الإجباري.")
    elif action in ("more", "reset"):
        if action == "reset":
            flow["channels"] = []
        flow["step"], flow["ts"] = "await_channel", time.time()
        await edit_or_send(query.message, "ابعت يوزر الجروب أو القناة أو الرابط.\n(أو اكتب إلغاء)")
    elif action == "saveon":
        if not flow["channels"]:
            flow["step"] = "await_channel"
            await edit_or_send(query.message, "لازم تضيف قناة واحدة على الأقل. ابعت يوزر القناة أو رابطها.")
            return
        store = await _fs_store()
        cfg = store.get(str(chat_id)) or {}
        cfg["channels"], cfg["enabled"] = flow["channels"], True
        store[str(chat_id)] = cfg
        await _fs_save_store()
        _FS_FLOW.pop((chat_id, admin_id), None)
        await edit_or_send(query.message, f"تم حفظ وتفعيل الاشتراك الإجباري.\n\nالقنوات:\n{_fs_list_text(cfg['channels'])}")


# ---- قسم «الاشتراك الإجباري» في لوحة الإدارة ----
async def fsub_section_open(update, context):
    q = update.callback_query
    await q.answer()
    if not await is_admin(q.from_user.id):
        await q.message.reply_text("الأمر متاح للمشرفين المصرح لهم فقط."); return
    await _fs_section_render(q, context)


async def _fs_section_render(q, context):
    await _fs_cfg_all()
    clear_priv_flows(context)
    buttons = [
        make_button("تعديل كليشة الاشتراك", callback_data="tpl_edit:sub_msg", style="primary"),
        make_button("تعديل كليشة النجاح والتحقق", callback_data="tpl_edit:sub_ok", style="primary"),
        make_button(f"لون زر القناة الأولى: {_fs_color_label('c1')}", callback_data="fsubcol:c1", style="primary"),
        make_button(f"لون زر القناة الثانية: {_fs_color_label('c2')}", callback_data="fsubcol:c2", style="primary"),
        make_button(f"لون زر التحقق: {_fs_color_label('verify')}", callback_data="fsubcol:verify", style="primary"),
        make_button("تعديل اسم زر القنوات", callback_data="fsublbl:join", style="primary"),
        make_button("تعديل اسم زر التحقق", callback_data="fsublbl:verify", style="primary"),
        nav_back("admin_open"),
    ]
    await edit_or_send(q.message, "الاشتراك الإجباري:", reply_markup=InlineKeyboardMarkup(two_column_rows(buttons)))


async def fsub_color_callback(update, context):
    q = update.callback_query
    if not await is_admin(q.from_user.id):
        await q.answer("غير مصرح لك.", show_alert=True); return
    await q.answer()
    kind = q.data.split(":", 1)[1]
    cfg = await _fs_cfg_all()
    order = [c for c, _ in FSUB_COLORS]
    cur = cfg.get(kind, "")
    cfg[kind] = order[(order.index(cur) + 1) % len(order)] if cur in order else ""
    await _fs_save_cfg()
    await _fs_section_render(q, context)


async def fsub_label_start(update, context):
    q = update.callback_query
    if not await is_admin(q.from_user.id):
        await q.answer("غير مصرح لك.", show_alert=True); return
    await q.answer()
    kind = q.data.split(":", 1)[1]
    cfg = await _fs_cfg_all()
    clear_priv_flows(context)
    context.user_data["fsub_flow"] = {"kind": kind}
    if kind == "join":
        await q.message.reply_text(
            f"الحالي: {cfg.get('join_label')}\n\nأرسل اسم زر القنوات. اكتب {{title}} مكان اسم القناة "
            "(مثال: اشترك في {title}).\nاكتب «افتراضي» للرجوع للأصل، أو «إلغاء».")
    else:
        await q.message.reply_text(
            f"الحالي: {cfg.get('verify_label')}\n\nأرسل الاسم الجديد لزر التحقق.\n"
            "اكتب «افتراضي» للرجوع للأصل، أو «إلغاء».")


async def fsub_label_message(update, context):
    flow = context.user_data.get("fsub_flow")
    msg = update.effective_message
    if not flow or not msg or not msg.text:
        return
    if not await is_admin(update.effective_user.id):
        context.user_data.pop("fsub_flow", None); return
    word = gr_n(msg.text)
    if word == "الغاء":
        context.user_data.pop("fsub_flow", None)
        await msg.reply_text("تم الإلغاء."); return
    cfg = await _fs_cfg_all()
    field = "join_label" if flow["kind"] == "join" else "verify_label"
    if word == "افتراضي":
        cfg[field] = _FS_CFG_DEFAULT[field]
    else:
        value = msg.text.strip()
        if not value or len(value) > 40:
            await msg.reply_text("الاسم لازم يكون من 1 إلى 40 حرف. ابعت اسم تاني أو اكتب: إلغاء"); return
        cfg[field] = value
    await _fs_save_cfg()
    context.user_data.pop("fsub_flow", None)
    await msg.reply_text(f"✅ تم الحفظ: {cfg[field]}")


# ---- دليل الأوامر (زر في الرسالة الرئيسية) ----
async def cmd_guide_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg = await get_message_config("cmd_guide")
    await edit_or_send(q.message, cfg["text"], entities=entity_objects(cfg.get("entities", [])),
                       reply_markup=InlineKeyboardMarkup([[back_button()]]))


async def post_init(app):
    global db
    db = RedisREST()
    log.info("Redis ping: %s", await db.cmd("PING"))
    try:
        from telegram import BotCommand
        await app.bot.set_my_commands([BotCommand("start", "بدء البوت وفتح القائمة"), BotCommand("help", "طريقة الاستخدام"), BotCommand("admin", "لوحة الإدارة")])
    except TelegramError as exc:
        log.warning("Could not set bot command menu: %s", exc)
    # Assign permanent references to reports saved before this update.
    ids = await db.cmd("SMEMBERS", "reports:all") or []
    for rid in ids:
        report = await db.getj("report:" + rid)
        if report and not report.get("reference_id"):
            await save_report(report)
        elif report and report.get("reference_id"):
            await db.cmd("SET", "reference:" + normalize_reference(report["reference_id"]), rid)
    try:
        await migrate_report_keys()
    except Exception:
        log.exception("Report key migration failed (non-fatal)")
    try:
        await _fs_load()
    except Exception:
        log.exception("force-sub preload failed (non-fatal)")
    try:
        await bc_bootstrap()
    except Exception:
        log.exception("Broadcast chat registry bootstrap failed (non-fatal)")
    try:
        _cursor, chat_keys = await db.cmd("SCAN", "0", "MATCH", "group_*", "COUNT", "1000")
        log.info("Restored from Redis: %d reports, %d chat data keys", await db.cmd("SCARD", "reports:all") or 0, len(chat_keys or []))
    except Exception:
        log.info("Could not count persisted chat data", exc_info=True)

async def post_shutdown(app):
    if db: await db.close()

async def error_handler(update, context):
    log.exception("Bot error", exc_info=context.error)

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_start, pattern=r"^(search|help|admin_open|scam_open|back_home)$"), CallbackQueryHandler(choose_search_type, pattern=r"^search_(cash|pubg|tg|tgid|ref)$")],
        states={SEARCH:[MessageHandler(filters.TEXT & ~filters.COMMAND, search_handler)],
                REPORT_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_text)],
                REPORT_REASON:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_reason)],
                REPORT_URL:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_url), CallbackQueryHandler(skip_report_url, pattern=r"^report_url_skip$")],
                ADMIN_ID:[MessageHandler(filters.TEXT & ~filters.COMMAND, admin_id_input)]},
        fallbacks=[CommandHandler("cancel", cancel)], allow_reentry=True,
    )
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_button, pattern=r"^(add_report|count|add_admin|del_admin|list_admins|delete_report_menu|delete_report:[a-f0-9]+|editmsg:(welcome|help|group_warning|search_guide|cmd_guide))$")],
        states={REPORT_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_text)],
                REPORT_USERNAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_username)],
                REPORT_PUBG:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_pubg)],
                REPORT_REASON:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_reason)],
                REPORT_URL:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_report_url), CallbackQueryHandler(skip_report_url, pattern=r"^report_url_skip$")],
                ADMIN_ID:[MessageHandler(filters.TEXT & ~filters.COMMAND, admin_id_input)],
                EDIT_MESSAGE:[MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, edit_message_input)],
                DELETE_REPORTS:[MessageHandler(filters.TEXT & ~filters.COMMAND, delete_report_by_ref)]},
        fallbacks=[CommandHandler("cancel", cancel)], allow_reentry=True,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(search_conv)
    app.add_handler(admin_conv)
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST | filters.UpdateType.EDITED_CHANNEL_POST, channel_post))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE & ~filters.StatusUpdate.ALL, group_check, block=False))
    # Group auto-replies feature (handler group 1: runs alongside, never blocks, existing group-0 handlers)
    app.add_handler(CallbackQueryHandler(gr_callback, pattern=r"^gr:"), group=1)
    app.add_handler(CallbackQueryHandler(tra_start, pattern=r"^tr_add_start$"), group=1)
    app.add_handler(CallbackQueryHandler(moda_start, pattern=r"^(mod|owner)_add_start$"), group=1)
    app.add_handler(CallbackQueryHandler(chatmgmt_open, pattern=r"^chatmgmt_open$"), group=1)
    app.add_handler(CallbackQueryHandler(tpl_edit_start, pattern=r"^tpl_edit:(mod|owner|trader|cmd_\w+|sub_\w+)$"), group=1)
    app.add_handler(CallbackQueryHandler(pc_callback, pattern=r"^pc:"), group=1)
    app.add_handler(CallbackQueryHandler(botcmds_open, pattern=r"^botcmds_open$"), group=1)
    app.add_handler(CallbackQueryHandler(botadmin_open, pattern=r"^botadmin_open$"), group=1)
    app.add_handler(CallbackQueryHandler(pr_callback, pattern=r"^pr:"), group=1)
    app.add_handler(CallbackQueryHandler(bc_callback, pattern=r"^bc:"), group=1)
    app.add_handler(ChatMemberHandler(bc_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER, block=False), group=1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, bc_message), group=10)
    app.add_handler(CallbackQueryHandler(cmdadd_start, pattern=r"^cmd_(add|del)_start$"), group=1)
    app.add_handler(CallbackQueryHandler(cmdact_callback, pattern=r"^cmdact:"), group=1)
    # Separate handler group so it runs independently of tra_message (only one handler per group fires).
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.PHOTO | filters.ANIMATION) & ~filters.COMMAND, moda_message), group=2)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, tpl_message), group=3)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, cmdadd_message), group=4)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, tra_message), group=1)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE & ~filters.StatusUpdate.ALL, gr_message), group=1)
    # Anti-raid (ban rate limit): owner panel callbacks, numeric input, and manual-ban monitoring.
    app.add_handler(CallbackQueryHandler(antiraid_callback, pattern=r"^antiraid_(open|toggle|set_limit|set_minutes)$"), group=1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, ar_message), group=5)
    app.add_handler(ChatMemberHandler(ar_chat_member, ChatMemberHandler.CHAT_MEMBER, block=False), group=1)
    # ---- ميزات منقولة: الروليت / منشن الخاص / AI / التحذير ----
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE & filters.TEXT, roulette_message), group=7)
    app.add_handler(CallbackQueryHandler(roulette_join_safe, pattern=r"^roulette_join:-?\d+$"), group=1)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE & ~filters.StatusUpdate.ALL, mention_notify_message), group=8)
    app.add_handler(CallbackQueryHandler(handle_ai_callback, pattern=r"^ai:(open|toggle|sch|set|names|cmds)$"), group=1)
    app.add_handler(CallbackQueryHandler(forced_sub_noop, pattern=r"^forced_sub$"), group=1)
    # ---- الاشتراك الإجباري + دليل الأوامر ----
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE & ~filters.StatusUpdate.ALL, forcesub_gate), group=-5)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE & ~filters.StatusUpdate.ALL, fsub_group_message), group=-4)
    app.add_handler(CallbackQueryHandler(fsub_verify_callback, pattern=r"^fsub:ok:-?\d+:\d+$"), group=1)
    app.add_handler(CallbackQueryHandler(fsub_admin_callback, pattern=r"^fsubadm:(more|reset|saveon|cancel):-?\d+:\d+$"), group=1)
    app.add_handler(CallbackQueryHandler(fsub_section_open, pattern=r"^fsubsec_open$"), group=1)
    app.add_handler(CallbackQueryHandler(fsub_color_callback, pattern=r"^fsubcol:(c1|c2|verify)$"), group=1)
    app.add_handler(CallbackQueryHandler(fsub_label_start, pattern=r"^fsublbl:(join|verify)$"), group=1)
    app.add_handler(CallbackQueryHandler(cmd_guide_open, pattern=r"^cmd_guide$"), group=1)
    app.add_handler(ChatMemberHandler(fsub_member_update, ChatMemberHandler.CHAT_MEMBER, block=False), group=21)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, fsub_label_message), group=22)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, ai_panel_message), group=9)
    app.add_handler(CallbackQueryHandler(warncfg_callback, pattern=r"^warncfg_(open|limit|dur)$"), group=1)
    app.add_handler(CallbackQueryHandler(warn_unmute_callback, pattern=r"^warnum:-?\d+:\d+$"), group=1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, warncfg_message), group=6)
    app.add_error_handler(error_handler)
    log.info("Starting bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
