from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ChatMemberHandler
)
import time
import unicodedata
import os
from flask import Flask
from threading import Thread

# ==================== PERSONALIZE THESE ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_USER_ID = 527164608
WHITELIST_IDS = [527164608]

MAX_MESSAGES_PER_MINUTE = 5
WARNING_LIMIT = 3

LOG_CHANNEL_ID = -1003672042124      # logs (channel joins only)
SPAM_CHANNEL_ID = -1003614311942     # Spams
MESSAGES_CHANNEL_ID = -1003299270448 # messages (group + private)

FILTER_WORDS = [
    # ======= English =======
    "spam", "advertisement", "ad", "promo", "buy now", "free", "click here",
    "subscribe", "follow me", "visit", "discount", "offer", "sale", "cheap",
    "link", "giveaway", "lottery", "win", "winner", "prize", "bitcoin", "crypto",
    "scam", "fraud", "hack", "cheat", "porn", "sex", "xxx", "nude", "adult",
    "erotic", "gamble", "casino", "loan", "credit card", "debt", "work from home",
    "earn money", "money back", "investment", "rich", "money", "fast cash",
    "online earning", "free gift", "clickbait", "viral", "tiktok", "instagram",
    "followers", "likes", "subscribe now", "join now", "limited offer", "urgent",
    "sale now", "hot deal", "win big", "prize money", "gift card", "free trial",
    "claim prize", "get rich", "make money", "shortcut", "secret", "exclusive",
    "password", "account", "login", "earnings", "crypto scam", "investment scam",
    "fake", "fraudulent", "hacked", "hack account", "illegal", "torrent", "warez",
    "keygen", "crack", "cheating", "exploit", "malware", "virus", "phishing",
    "nsfw", "18+", "erotic content", "sex content", "gambling", "casino online",
    "adult site", "dating site", "escort", "prostitute", "hookup", "drug", "cocaine",
    "marijuana", "heroin", "illegal drug", "alcohol", "gamble online", "pornography",

    # ======= Persian / Farsi =======
    "اسپم", "تبلیغ", "خرید", "رایگان", "کلیک کنید", "هدیه", "برنده", "جایزه",
    "فالو", "دنبال کردن", "لینک", "فروش", "ارزان", "تخفیف", "آفر", "بیت کوین",
    "کریپتو", "کلاهبرداری", "هک", "تقلب", "پورن", "سکس", "عکس نیمه برهنه", "xxx",
    "محتوای بزرگسال", "عکسی نامناسب", "قمار", "کازینو", "وام", "کارت اعتباری",
    "بدهی", "کار در خانه", "کسب درآمد", "پول رایگان", "سرمایه گذاری", "ثروتمند",
    "پول", "نقد سریع", "کسب آنلاین", "هدیه رایگان", "ویروسی", "اینستاگرام", "فالوور",
    "لایک", "همین حالا عضو شو", "پیشنهاد محدود", "فوری", "فروش ویژه", "جایزه بزرگ",
    "کارت هدیه", "تجربه رایگان", "دریافت جایزه", "ثروتمند شدن", "پول درآوردن", 
    "راز", "انحصاری", "رمز عبور", "حساب کاربری", "ورود", "کسب درآمد آنلاین", 
    "اسکم کریپتو", "سرمایه گذاری جعلی", "فیک", "هک شده", "غیرقانونی", "تورنت", 
    "کراک", "کیجن", "بد افزار", "ویروس", "فیشینگ", "محتوای غیر اخلاقی", "18+", 
    "محتوای سکسی", "محتوای بزرگسالان", "کازینو آنلاین", "دیتینگ", "آسانسور", 
    "مواد مخدر", "کوکائین", "ماریجوانا", "هروئین", "مواد غیرقانونی", "الکل"
]
# ============================================================

user_message_times = {}
user_warnings = {}
muted_users = {}

# ===== HELPERS =====
def get_user_mention(user_id, username):
    display = f"@{username}" if username else f"user_{user_id}"
    return f"[{display}](tg://user?id={user_id})"

# ===== MESSAGE HANDLER =====
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id

# ===== FORWARD PRIVATE MESSAGES TO CHANNEL =====
if msg.chat.type == "private" and not msg.text.startswith("/") and not msg.reply_to_message:
    try:
        mention = get_user_mention(user_id, msg.from_user.username)
        await context.bot.send_message(
            chat_id=MESSAGES_CHANNEL_ID,
            text=f"{mention}: \"{msg.text}\"",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    
    if user_id in WHITELIST_IDS:
        return

    # ===== DELETE JOIN / LEAVE MESSAGES =====
    if msg.new_chat_members or msg.left_chat_member:
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # ===== SPAM FILTER (GROUP ONLY) =====
    if msg.chat.type in ("group", "supergroup") and msg.text:
        normalized = unicodedata.normalize("NFC", msg.text.lower())
        for word in FILTER_WORDS:
            if word in normalized:
                try:
                    await msg.delete()
                except Exception:
                    pass

                mention = get_user_mention(user_id, msg.from_user.username)
                await log_action(
                    f"Deleted spam from {mention} (ID: `{user_id}`):\n{msg.text}",
                    SPAM_CHANNEL_ID,
                    context
                )
                await warn_user(msg, context)
                return

    # ===== FLOOD CONTROL =====
    timestamps = user_message_times.get(user_id, [])
    now = time.time()
    timestamps = [t for t in timestamps if now - t < 60]
    timestamps.append(now)
    user_message_times[user_id] = timestamps

    if len(timestamps) > MAX_MESSAGES_PER_MINUTE:
        try:
            await msg.delete()
        except Exception:
            pass

        mention = get_user_mention(user_id, msg.from_user.username)
        await log_action(
            f"Flood detected from {mention} (ID: `{user_id}`)",
            SPAM_CHANNEL_ID,
            context
        )
        await warn_user(msg, context)

# ===== WARN & MUTE =====
async def warn_user(msg, context):
    uid = msg.from_user.id
    user_warnings[uid] = user_warnings.get(uid, 0) + 1

    if user_warnings[uid] < WARNING_LIMIT:
        await msg.reply_text(
            f"Warning {user_warnings[uid]}/{WARNING_LIMIT}. Follow the rules."
        )
    else:
        until = int(time.time()) + 600
        muted_users[uid] = until
        await msg.chat.restrict_member(
            user_id=uid,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await log_action(
            f"User `{uid}` muted for repeated violations.",
            SPAM_CHANNEL_ID,
            context
        )
        user_warnings[uid] = 0

# ===== LOGGING =====
async def log_action(text, channel_id, context):
    try:
        await context.bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode="Markdown"
        )
    except Exception:
        pass

# ===== CHAT MEMBER HANDLER =====
async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.type != "channel":
        return

    if cm.old_chat_member.status in ("left", "kicked") and cm.new_chat_member.status == "member":
        user = cm.new_chat_member.user
        mention = get_user_mention(user.id, user.username)
        await log_action(
            f"New channel subscriber: {mention} | ID: `{user.id}`",
            LOG_CHANNEL_ID,
            context
        )

# ===== COMMANDS =====
async def list_warnings(update: Update, context):
    if not user_warnings:
        await update.message.reply_text("No warnings.")
        return
    text = "\n".join([f"{uid}: {cnt}" for uid, cnt in user_warnings.items()])
    await update.message.reply_text(text)

async def list_muted(update: Update, context):
    if not muted_users:
        await update.message.reply_text("No muted users.")
        return
    text = "\n".join([f"{uid} until {time.ctime(t)}" for uid, t in muted_users.items()])
    await update.message.reply_text(text)

async def cmd_start(update: Update, context):
    await update.message.reply_text("درود به چنل خودتون خوش اومدین")

async def cmd_myid(update: Update, context):
    await update.message.reply_text("@SedAl_Hoseini")

# ===== APP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("myid", cmd_myid))
app.add_handler(CommandHandler("warnings", list_warnings))
app.add_handler(CommandHandler("muted", list_muted))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

print("Punisher bot is running...")
app.run_polling()



