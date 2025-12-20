from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ChatMemberHandler
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
import time
import unicodedata
import os
import json

# ==================== PERSONALIZE THESE ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_USER_IDS = {527164608}  # Add your personal ID here
ADMIN_CHAT_IDS = {1087968824}  # IDs of groups/channels the bot should recognize as admin

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

# ===== ADMIN CHECK DECORATOR =====
def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        if not is_admin(update):
            try:
                await update.message.reply_text("You are not allowed to use this command.")
            except Exception:
                pass
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ===== HELPERS =====

def build_warning_keyboard(user_id):
    """Create inline keyboard for warnings actions"""
    buttons = [
        [InlineKeyboardButton("Mute 10 min", callback_data=f"mute:{user_id}:600")],
        [InlineKeyboardButton("Mute 30 min", callback_data=f"mute:{user_id}:1800")],
        [InlineKeyboardButton("Clear warnings", callback_data=f"clearwarn:{user_id}")],
    ]
    return InlineKeyboardMarkup(buttons)


def build_muted_keyboard(user_id):
    """Create inline keyboard for muted actions"""
    buttons = [
        [InlineKeyboardButton("Increase 10 min", callback_data=f"increase:{user_id}:600")],
        [InlineKeyboardButton("Increase 30 min", callback_data=f"increase:{user_id}:1800")],
        [InlineKeyboardButton("Unmute", callback_data=f"unmute:{user_id}")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_user_mention(user_id, username):
    display = f"@{username}" if username else f"user_{user_id}"
    return f"[{display}](tg://user?id={user_id})"

def is_admin(update: Update) -> bool:
    msg = update.message
    if not msg:
        return False

    # Case 1: personal account
    if msg.from_user and msg.from_user.id in ADMIN_USER_IDS:
        return True

    # Case 2: message sent as group/channel
    if msg.sender_chat and msg.sender_chat.id in ADMIN_CHAT_IDS:
        return True

    return False

# ===== PERSISTENCE HELPERS =====
WARNINGS_FILE = "warnings.json"
MUTED_FILE = "muted.json"

def load_data(file, default):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        return default

def save_data(file, data):
    try:
        with open(file, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

# Load data at startup
user_warnings = load_data(WARNINGS_FILE, {})
muted_users = load_data(MUTED_FILE, {})

# ===== MESSAGE HANDLER =====

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    action = data[0]
    user_id = int(data[1])
    value = int(data[2]) if len(data) > 2 else None
    
    if action == "clearwarn":
        user_warnings[user_id] = 0
        save_data(WARNINGS_FILE, user_warnings)
        await query.edit_message_text(f"Warnings cleared for user {user_id}")
    
    elif action == "mute":
        until = int(time.time()) + value
        muted_users[user_id] = until
        save_data(MUTED_FILE, muted_users)
        await query.edit_message_text(f"User {user_id} muted for {value//60} minutes")
    
    elif action == "increase":
        if user_id in muted_users:
            muted_users[user_id] += value
            save_data(MUTED_FILE, muted_users)
            await query.edit_message_text(f"Muted duration increased by {value//60} minutes for user {user_id}")
        else:
            await query.edit_message_text("User is not muted")
    
    elif action == "unmute":
        if user_id in muted_users:
            del muted_users[user_id]
            save_data(MUTED_FILE, muted_users)
            await query.edit_message_text(f"User {user_id} unmuted")
        else:
            await query.edit_message_text("User is not muted")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id
        # ===== FORWARD PRIVATE MESSAGES TO CHANNEL =====
    if (
        msg.chat.type == "private"
        and msg.text
        and not msg.text.startswith("/")
        and not msg.reply_to_message
    ):
        try:
            mention = get_user_mention(user_id, msg.from_user.username)
            await context.bot.send_message(
                chat_id=MESSAGES_CHANNEL_ID,
                text=f'{mention}: "{msg.text}"',
                parse_mode="Markdown"
            )
        except Exception:
            pass



    if is_admin(update):
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
    now = int(time.time())
    
    # store warning count + timestamp
    user_warnings[uid] = {
        'count': user_warnings.get(uid, {'count':0})['count'] + 1,
        'time': now
    }
    save_data(WARNINGS_FILE, user_warnings)
    
    if user_warnings[uid]['count'] < WARNING_LIMIT:
        try:
            await msg.reply_text(
                f"Warning {user_warnings[uid]['count']}/{WARNING_LIMIT}. Follow the rules."
            )
        except Exception:
            pass
    else:
        until = now + 600  # mute duration
        muted_users[uid] = until
        save_data(MUTED_FILE, muted_users)
        
        try:
            await msg.chat.restrict_member(
                user_id=uid,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
        except Exception:
            pass

        try:
            mention = get_user_mention(uid, msg.from_user.username)
            await log_action(
                f"User `{uid}` muted for repeated violations.",
                SPAM_CHANNEL_ID,
                context
            )
        except Exception:
            pass

        # reset warning count
        user_warnings[uid] = {'count': 0, 'time': now}
        save_data(WARNINGS_FILE, user_warnings)

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
@admin_only
async def list_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = int(time.time())
    EXPIRE_SECONDS = 24*3600  # 24 hours expiry
    
    # Remove expired warnings
    expired = [uid for uid, data in user_warnings.items() if now - data['time'] > EXPIRE_SECONDS]
    for uid in expired:
        del user_warnings[uid]
    if expired:
        save_data(WARNINGS_FILE, user_warnings)
    
    if not user_warnings:
        await update.message.reply_text("No warnings.")
        return
    
    for uid, data in user_warnings.items():
        try:
            user = await context.bot.get_chat(uid)
            mention = get_user_mention(user.id, user.username)
        except:
            mention = f"user_{uid}"
        
        await update.message.reply_text(
            f"{mention}: {data['count']}",
            reply_markup=build_warning_keyboard(uid)
        )

@admin_only
async def list_muted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = int(time.time())
    to_remove = []

    for uid, until_ts in muted_users.items():
        try:
            chat_member = await context.bot.get_chat_member(update.effective_chat.id, uid)
            # If user is not restricted or restriction expired, remove from memory
            if chat_member.can_send_messages or until_ts <= now:
                to_remove.append(uid)
        except Exception:
            # If we can't fetch member (left the chat), remove too
            to_remove.append(uid)

    for uid in to_remove:
        del muted_users[uid]
    if to_remove:
        save_data(MUTED_FILE, muted_users)

    if not muted_users:
        await update.message.reply_text("No muted users.")
        return

    for uid, until_ts in muted_users.items():
        try:
            user = await context.bot.get_chat(uid)
            mention = get_user_mention(user.id, user.username)
        except:
            mention = f"user_{uid}"
        await update.message.reply_text(
            f"{mention} until {time.ctime(until_ts)}",
            reply_markup=build_muted_keyboard(uid)
        )

async def cmd_start(update: Update, context):
    try:
        await update.message.reply_text("درود به چنل خودتون خوش اومدین")
    except Exception:
        pass

async def cmd_myid(update: Update, context):
    try:
        await update.message.reply_text("@SedAl_Hoseini")
    except Exception:
        pass


# ===== APP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("myid", cmd_myid))
app.add_handler(CommandHandler("warnings", list_warnings))
app.add_handler(CommandHandler("muted", list_muted))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))
app.add_handler(CallbackQueryHandler(button_handler))

print("Punisher bot is running...")
app.run_polling()







