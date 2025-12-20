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
]  # add your full list if needed

WARNINGS_FILE = "warnings.json"
MUTED_FILE = "muted.json"

TEHRAN = pytz.timezone("Asia/Tehran")

user_message_times = {}
user_warnings = {}
muted_users = {}

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

def get_user_mention(user_id, username):
    display = f"@{username}" if username else f"user_{user_id}"
    return f"[{display}](tg://user?id={user_id})"

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
async def log_action(text, channel_id, context):
    try:
        await context.bot.send_message(chat_id=channel_id, text=text, parse_mode="Markdown")
    except: pass

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
        await query.edit_message_text(f"Warnings cleared for {get_user_mention(user_id,None)}")

    elif action == "mute":
        muted_users[user_id] = now + value
        save_data(MUTED_FILE,muted_users)
        await query.edit_message_text(f"{get_user_mention(user_id,None)} muted for {value//60} minutes")

    elif action == "increase":
        if user_id in muted_users:
            muted_users[user_id] += value
            save_data(MUTED_FILE,muted_users)
            until_str = datetime.fromtimestamp(muted_users[user_id], tz=TEHRAN).strftime("%Y-%m-%d %H:%M:%S")
            await query.edit_message_text(f"Muted duration increased for {get_user_mention(user_id,None)}. New until: {until_str}")
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
            await query.edit_message_text(f"{get_user_mention(user_id,None)} unmuted")
        else:
            await query.edit_message_text("User is not muted")

# ===== HANDLE MESSAGES =====
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user: return
    uid = msg.from_user.id
    now = int(time.time())

    # ===== DELETE JOIN / LEAVE MESSAGES =====
    if msg.new_chat_members or msg.left_chat_member:
        try:
            await msg.delete()
        except:
            pass
        return
    
    # ===== FORWARD PRIVATE MESSAGES =====
    if msg.chat.type=="private" and msg.text and not msg.text.startswith("/") and not msg.reply_to_message:
        try:
            mention = get_user_mention(uid, msg.from_user.username)
            await context.bot.send_message(MESSAGES_CHANNEL_ID, f'{mention}: "{msg.text}"', parse_mode="Markdown")
        except: pass

    # spam filter
    if msg.chat.type in ("group","supergroup") and msg.text:
        normalized = unicodedata.normalize("NFC", msg.text.lower())
        for word in FILTER_WORDS:
            if word in normalized:
                try: await msg.delete()
                except: pass
                mention = get_user_mention(uid, msg.from_user.username)
                await log_action(f"Deleted spam from {mention} (ID: `{uid}`):\n{msg.text}", SPAM_CHANNEL_ID, context)
                await warn_user(msg, context)
                return

    # flood control
    times = user_message_times.get(uid,[])
    times = [t for t in times if now - t < 60]
    times.append(now)
    user_message_times[uid] = times
    if len(times) > MAX_MESSAGES_PER_MINUTE:
        try: await msg.delete()
        except: pass
        mention = get_user_mention(uid, msg.from_user.username)
        await log_action(f"Flood detected from {mention} (ID: `{uid}`)", SPAM_CHANNEL_ID, context)
        await warn_user(msg, context)

    if len(times) > MAX_MESSAGES_PER_MINUTE:
        try: await msg.delete()
        except: pass
        mention = get_user_mention(uid, msg.from_user.username)
        await log_action(f"Flood detected from {mention} (ID: `{uid}`)", SPAM_CHANNEL_ID, context)
        await warn_user(msg, context)


    # ===== REPLY WITH NUMERIC ID =====
    # Only for non-command text messages in groups/channels
    if msg.chat.type in ("group","supergroup") and msg.text and not msg.text.startswith("/"):
        try:
            await msg.reply_text(f"`[{uid}]`", parse_mode="Markdown")
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
        mention = get_user_mention(uid, msg.from_user.username)
        await log_action(f"User `{uid}` muted for repeated violations.", SPAM_CHANNEL_ID, context)
        user_warnings[uid] = {"count":0,"time":now}
        save_data(WARNINGS_FILE,user_warnings)

# ===== CHAT MEMBER HANDLER =====
async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.type != "channel": return
    if cm.old_chat_member.status in ("left","kicked") and cm.new_chat_member.status=="member":
        user = cm.new_chat_member.user
        mention = get_user_mention(user.id,user.username)
        await log_action(f"New channel subscriber: {mention} | ID: `{user.id}`", LOG_CHANNEL_ID, context)

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
        try:
            user = await context.bot.get_chat(uid)
            mention = get_user_mention(user.id, user.username)
        except:
            mention = f"user_{uid}"
        await update.message.reply_text(f"{mention}: {data['count']}", reply_markup=build_warning_keyboard(uid))

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
        await update.message.reply_text(f"{get_user_mention(uid,None)} until {until_str}", reply_markup=build_muted_keyboard(uid))

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

# ===== APP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(CommandHandler("warnings", list_warnings))
app.add_handler(CommandHandler("muted", list_muted))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("myid", cmd_myid))

print("Punisher bot is running...")
app.run_polling()







