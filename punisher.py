from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ChatMemberHandler,
    CallbackQueryHandler
)
import time, os, json
from datetime import datetime
import pytz
import unicodedata

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = {527164608}  
ADMIN_CHAT_IDS = {1087968824}  

MAX_MESSAGES_PER_MINUTE = 5
WARNING_LIMIT = 3

LOG_CHANNEL_ID = -1003672042124
SPAM_CHANNEL_ID = -1003614311942
MESSAGES_CHANNEL_ID = -1003299270448

FILTER_WORDS = [
    "spam","advertisement","ad","promo","buy now","free","click here"
]

WARNINGS_FILE = "warnings.json"
MUTED_FILE = "muted.json"

TEHRAN = pytz.timezone("Asia/Tehran")

user_message_times = {}
user_warnings = {}
muted_users = {}
WAITING_FOR_NUMERIC = set()

# ===== HELPERS =====
def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        user = None
        if update.message:
            user = update.message.from_user
        elif update.callback_query:
            user = update.callback_query.from_user
        if not user or (user.id not in ADMIN_USER_IDS and (update.message and not update.message.sender_chat or update.callback_query and not update.callback_query.message.sender_chat)):
            if update.message:
                await update.message.reply_text("You are not allowed to use this command.")
            elif update.callback_query:
                await update.callback_query.answer("Not allowed", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# CLICKABLE USER (HTML)
def user_link(user):
    name = user.full_name or "User"
    return f'<a href="tg://user?id={user.id}">{name}</a>'

def get_user_mention(uid, username=None):
    if username:
        return f"@{username}"
    return f"`{uid}`"  # Send numeric ID in backticks for plain text

def build_warning_keyboard(user_id):
    buttons = [
        [InlineKeyboardButton("Mute 10 min", callback_data=f"mute:{user_id}:600")],
        [InlineKeyboardButton("Mute 30 min", callback_data=f"mute:{user_id}:1800")],
        [InlineKeyboardButton("Clear warnings", callback_data=f"clearwarn:{user_id}")]
    ]
    return InlineKeyboardMarkup(buttons)

def build_muted_keyboard(user_id):
    buttons = [
        [InlineKeyboardButton("Increase 10 min", callback_data=f"increase:{user_id}:600")],
        [InlineKeyboardButton("Increase 30 min", callback_data=f"increase:{user_id}:1800")],
        [InlineKeyboardButton("Unmute", callback_data=f"unmute:{user_id}")]
    ]
    return InlineKeyboardMarkup(buttons)

def load_data(file, default):
    try:
        with open(file,"r") as f: return json.load(f)
    except: return default

def save_data(file, data):
    try:
        with open(file,"w") as f: json.dump(data,f)
    except: pass

# ===== LOAD DATA =====
user_warnings = load_data(WARNINGS_FILE, {})
muted_users = load_data(MUTED_FILE, {})

# ===== LOGGING =====
async def log_action(text, channel_id, context, html=True):
    try:
        await context.bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode="HTML" if html else None,
            disable_web_page_preview=True
        )
    except:
        pass

# ===== BUTTON HANDLER =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    action = data[0]
    user_id = int(data[1])
    value = int(data[2]) if len(data)>2 else None
    now = int(time.time())

    if action == "clearwarn":
        user_warnings[user_id] = {"count":0,"time":now}
        save_data(WARNINGS_FILE,user_warnings)
        await query.edit_message_text(f"Warnings cleared for `{user_id}`")

    elif action == "mute":
        muted_users[user_id] = now + value
        save_data(MUTED_FILE,muted_users)
        await query.edit_message_text(f"`{user_id}` muted for {value//60} minutes")

    elif action == "increase":
        if user_id in muted_users:
            muted_users[user_id] += value
            save_data(MUTED_FILE,muted_users)
            until_str = datetime.fromtimestamp(muted_users[user_id], tz=TEHRAN).strftime("%Y-%m-%d %H:%M:%S")
            await query.edit_message_text(f"`{user_id}` muted until {until_str}")
        else:
            await query.edit_message_text("User is not muted")

    elif action == "unmute":
        if user_id in muted_users:
            del muted_users[user_id]
            save_data(MUTED_FILE, muted_users)
            try:
                await context.bot.restrict_chat_member(
                    chat_id=update.effective_chat.id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
            except:
                pass
            await query.edit_message_text(f"`{user_id}` unmuted")
        else:
            await query.edit_message_text("User is not muted")

# ===== HANDLE MESSAGES =====
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user: 
        return

    user_id = msg.from_user.id
    uid = user_id
    now = int(time.time())

    # --- NUMERIC MODE ACTIVE ---
    if user_id in WAITING_FOR_NUMERIC:
        try:
            numeric_id = None
            if msg.text and msg.text.startswith("@"):
                try:
                    chat = await context.bot.get_chat(msg.text)
                    numeric_id = chat.id
                except:
                    numeric_id = msg.from_user.id
            elif msg.forward_from_chat:
                numeric_id = msg.forward_from_chat.id
            else:
                numeric_id = msg.from_user.id

            # Reply with numeric ID
            await msg.reply_text(f"`{numeric_id}`", parse_mode="Markdown")

            # Forward message to MESSAGES_CHANNEL_ID
            text_to_send = msg.text if msg.text else ""
            await context.bot.send_message(
                MESSAGES_CHANNEL_ID,
                f"`{numeric_id}`: {text_to_send}",
                parse_mode=None  # Send as plain text, no clickable links
            )
            # Forward media
            if msg.photo: await context.bot.send_photo(MESSAGES_CHANNEL_ID, msg.photo[-1].file_id)
            if msg.audio: await context.bot.send_audio(MESSAGES_CHANNEL_ID, msg.audio.file_id)
            if msg.document: await context.bot.send_document(MESSAGES_CHANNEL_ID, msg.document.file_id)
            if msg.video: await context.bot.send_video(MESSAGES_CHANNEL_ID, msg.video.file_id)
            if msg.voice: await context.bot.send_voice(MESSAGES_CHANNEL_ID, msg.voice.file_id)
            if msg.sticker: await context.bot.send_sticker(MESSAGES_CHANNEL_ID, msg.sticker.file_id)

        except Exception as e:
            print(f"Numeric mode error: {e}")

        WAITING_FOR_NUMERIC.discard(user_id)
        return

    # ----- PRIVATE MESSAGE FORWARDING -----
    if msg.chat.type == "private" and msg.from_user:
        try:
            numeric_id = uid
            text_to_send = msg.text if msg.text else ""
            await context.bot.send_message(
                MESSAGES_CHANNEL_ID,
                f"`{numeric_id}`: {text_to_send}",
                parse_mode=None  # Plain text
            )
            if msg.photo: await context.bot.send_photo(MESSAGES_CHANNEL_ID, msg.photo[-1].file_id)
            if msg.audio: await context.bot.send_audio(MESSAGES_CHANNEL_ID, msg.audio.file_id)
            if msg.document: await context.bot.send_document(MESSAGES_CHANNEL_ID, msg.document.file_id)
            if msg.video: await context.bot.send_video(MESSAGES_CHANNEL_ID, msg.video.file_id)
            if msg.voice: await context.bot.send_voice(MESSAGES_CHANNEL_ID, msg.voice.file_id)
            if msg.sticker: await context.bot.send_sticker(MESSAGES_CHANNEL_ID, msg.sticker.file_id)

        except Exception as e:
            print(f"Forwarding error: {e}")

    # ===== DELETE JOIN / LEAVE MESSAGES =====
    if msg.new_chat_members or msg.left_chat_member:
        try: await msg.delete()
        except: pass
        return

    # ===== SPAM FILTER =====
    if msg.chat.type in ("group", "supergroup") and msg.text:
        normalized = unicodedata.normalize("NFC", msg.text.lower())
        for word in FILTER_WORDS:
            if word in normalized:
                try: await msg.delete()
                except: pass
                await log_action(f"`{uid}`: Spam deleted.", SPAM_CHANNEL_ID, context, html=False)
                await warn_user(msg, context)
                return

    # ===== FLOOD CONTROL =====
    times = user_message_times.get(uid, [])
    times = [t for t in times if now - t < 60]
    times.append(now)
    user_message_times[uid] = times
    if len(times) > MAX_MESSAGES_PER_MINUTE:
        try: await msg.delete()
        except: pass
        await log_action(f"`{uid}`: Flood detected.", SPAM_CHANNEL_ID, context, html=False)
        await warn_user(msg, context)

    # NUMERIC ID REPLY (for groups, normal operation)
    if msg.chat.type in ("group","supergroup") and msg.text and not msg.text.startswith("/"):
        try:
            await msg.reply_text(f"`{uid}`", parse_mode="Markdown")
        except:
            pass

# ===== WARN & MUTE =====
async def warn_user(msg, context):
    uid = msg.from_user.id
    now = int(time.time())
    user_warnings[uid] = {"count": user_warnings.get(uid,{"count":0})["count"] +1, "time": now}
    save_data(WARNINGS_FILE,user_warnings)
    if user_warnings[uid]["count"] >= WARNING_LIMIT:
        muted_users[uid] = now + 600
        save_data(MUTED_FILE,muted_users)
        try: await msg.chat.restrict_member(uid,permissions=ChatPermissions(can_send_messages=False),until_date=now+600)
        except: pass
        await log_action(f"`{uid}`: Got muted.", SPAM_CHANNEL_ID, context, html=False)
        user_warnings[uid] = {"count":0,"time":now}
        save_data(WARNINGS_FILE,user_warnings)

# ===== CHAT MEMBER HANDLER =====
async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.type != "channel": return
    if cm.old_chat_member.status in ("left","kicked") and cm.new_chat_member.status=="member":
        user = cm.new_chat_member.user
        await log_action(f"`{user.id}` joined.", LOG_CHANNEL_ID, context, html=False)

# ===== COMMANDS =====
@admin_only
async def list_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = int(time.time())
    EXPIRE_SECONDS = 24*3600
    expired = [uid for uid, data in user_warnings.items() if now - data['time'] > EXPIRE_SECONDS or data['count']==0]
    for uid in expired: del user_warnings[uid]
    if expired: save_data(WARNINGS_FILE, user_warnings)
    if not user_warnings:
        await update.message.reply_text("No warnings.")
        return
    for uid, data in user_warnings.items():
        await update.message.reply_text(f"`{uid}`: {data['count']}", reply_markup=build_warning_keyboard(uid))

@admin_only
async def list_muted(update: Update, context):
    now = int(time.time())
    expired = [uid for uid,until in muted_users.items() if until <= now]
    for uid in expired: del muted_users[uid]
    if expired: save_data(MUTED_FILE, muted_users)
    if not muted_users:
        await update.message.reply_text("No muted users.")
        return
    for uid,until in muted_users.items():
        until_str = datetime.fromtimestamp(until, tz=TEHRAN).strftime("%Y-%m-%d %H:%M:%S")
        await update.message.reply_text(f"`{uid}` until {until_str}", reply_markup=build_muted_keyboard(uid))

# ===== NORMAL USER COMMANDS =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("درود! به چنل خودتون خوش اومدید.")
    except:
        pass

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("@SedAl_Hoseini")
    except:
        pass

# ===== GET NUMERIC COMMAND =====
async def get_numeric(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        WAITING_FOR_NUMERIC.add(user_id)
        await update.message.reply_text(
            "لطفا یکی از موارد زیر را ارسال کنید:\n"
            "@username\n"
            "یا یک پیام فوروارد شده از کانال\n"
            "یا یک پیام معمولی\n"
            "یا استیکر / مدیا"
        )
    except:
        pass

# ===== APP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(CommandHandler("warnings", list_warnings))
app.add_handler(CommandHandler("muted", list_muted))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("myid", cmd_myid))
app.add_handler(CommandHandler("get_numeric", get_numeric))

print("Punisher bot is running...")
app.run_polling()
