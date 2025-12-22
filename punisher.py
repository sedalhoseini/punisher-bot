from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ChatMemberHandler,
)
import re, time, os, unicodedata
from datetime import datetime, timedelta
import pytz

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = {527164608}

LOG_CHANNEL_ID = -1003672042124
MESSAGES_CHANNEL_ID = -1003299270448

# Spam patterns: keywords + links
FILTER_PATTERNS = re.compile(
    r"(spam|advertisement|ad|promo|buy\s*now|free|click\s*here|https?://)", re.IGNORECASE
)

TEHRAN = pytz.timezone("Asia/Tehran")

# For detecting repeated messages
last_user_messages = {}  # {user_id: (text, timestamp)}

# ===== HELPERS =====
def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ADMIN_USER_IDS:
            if update.message:
                await update.message.reply_text("You are not allowed to use this command.")
            elif update.callback_query:
                await update.callback_query.answer("Not allowed", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def user_link(user):
    name = user.full_name or "User"
    return f'<a href="tg://user?id={user.id}">{name}</a>'

def get_user_mention(user):
    return f"@{user.username}" if user.username else user_link(user)


async def log_action(text, context, channel_id=LOG_CHANNEL_ID):
    try:
        await context.bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"Logging failed: {e}")


# ===== MEDIA FORWARDING =====
async def forward_media(msg, channel_id, mention, context):
    try:
        if msg.photo:
            await context.bot.send_photo(channel_id, msg.photo[-1].file_id, caption=mention)
        elif msg.video:
            await context.bot.send_video(channel_id, msg.video.file_id, caption=mention)
        elif msg.audio:
            await context.bot.send_audio(channel_id, msg.audio.file_id, caption=mention)
        elif msg.voice:
            await context.bot.send_voice(channel_id, msg.voice.file_id, caption=mention)
        elif msg.document:
            await context.bot.send_document(channel_id, msg.document.file_id, caption=mention)
        elif msg.sticker:
            await context.bot.send_sticker(channel_id, msg.sticker.file_id)
            await context.bot.send_message(channel_id, mention, parse_mode="HTML")
    except Exception as e:
        await log_action(f"Forwarding error: {e}", context)


# ===== HANDLE MESSAGES =====
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    # ----- PRIVATE MESSAGE FORWARDING -----
    if msg.chat.type == "private" and not msg.text.startswith("/"):
        mention = get_user_mention(msg.from_user)
        if msg.text:
            await context.bot.send_message(MESSAGES_CHANNEL_ID, f'{mention}: "{msg.text}"')
        await forward_media(msg, MESSAGES_CHANNEL_ID, mention, context)

    # ----- DELETE JOIN / LEAVE MESSAGES -----
    if msg.new_chat_members or msg.left_chat_member:
        try:
            await msg.delete()
        except:
            pass
        return

    # ----- ADVANCED SPAM FILTER -----
    if msg.chat.type in ("group", "supergroup"):
        normalized = unicodedata.normalize("NFC", msg.text or "")
        user_id = msg.from_user.id
        now = int(time.time())

        # 1️⃣ Keyword / link spam
        if FILTER_PATTERNS.search(normalized):
            try:
                await msg.delete()
            except:
                pass
            return

        # 2️⃣ Repeated messages
        last_msg, last_time = last_user_messages.get(user_id, ("", 0))
        if normalized == last_msg and now - last_time < 10:  # 10 seconds threshold
            try:
                await msg.delete()
            except:
                pass
            return
        last_user_messages[user_id] = (normalized, now)


# ===== CHAT MEMBER HANDLER =====
async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.type != "channel":
        return
    if cm.old_chat_member.status in ("left", "kicked") and cm.new_chat_member.status == "member":
        user = cm.new_chat_member.user
        await log_action(f"{user_link(user)}, Joined.", context)


# ===== COMMANDS =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("درود! به چنل خودتون خوش اومدید.")
    except:
        pass

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Always return custom username
    await update.message.reply_text("@SedAl_Hoseini")

async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.reply_to_message and msg.reply_to_message.from_user:
        user = msg.reply_to_message.from_user
    elif context.args:
        arg = context.args[0].lstrip("@")
        try:
            user = await context.bot.get_chat(arg)
        except:
            await msg.reply_text("User not found.")
            return
    else:
        user = msg.from_user

    username = f"@{user.username}" if user.username else "None"
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    text = (
        f"<b>Name:</b> {full_name}\n"
        f"<b>Username:</b> {username}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n"
        f"<b>Bot:</b> {'Yes' if user.is_bot else 'No'}"
    )
    await msg.reply_text(text, parse_mode="HTML")


# ===== GROUP MODERATION =====
@admin_only
async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("Reply to the user you want to mute.")
        return

    user = msg.reply_to_message.from_user
    duration = 3600  # default 1 hour
    if context.args:
        try:
            duration = int(context.args[0])  # seconds
        except:
            pass

    try:
        await context.bot.restrict_chat_member(
            chat_id=msg.chat_id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.utcnow() + timedelta(seconds=duration)
        )
        await msg.reply_text(f"{user_link(user)} has been muted for {duration} seconds.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to mute: {e}")

@admin_only
async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("Reply to the user you want to unmute.")
        return
    user = msg.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            chat_id=msg.chat_id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                        can_send_polls=True, can_send_other_messages=True,
                                        can_add_web_page_previews=True, can_change_info=True,
                                        can_invite_users=True, can_pin_messages=True)
        )
        await msg.reply_text(f"{user_link(user)} has been unmuted.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to unmute: {e}")

@admin_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("Reply to the user you want to ban.")
        return
    user = msg.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(chat_id=msg.chat_id, user_id=user.id)
        await msg.reply_text(f"{user_link(user)} has been banned.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to ban: {e}")

@admin_only
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not context.args:
        await msg.reply_text("Provide the user ID to unban.")
        return
    try:
        user_id = int(context.args[0])
        await context.bot.unban_chat_member(chat_id=msg.chat_id, user_id=user_id)
        await msg.reply_text(f"User {user_id} has been unbanned.")
    except Exception as e:
        await msg.reply_text(f"Failed to unban: {e}")


# ===== APPLICATION =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# ---- CHAT MEMBER HANDLER ----
app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))

# ---- COMMAND HANDLERS ----
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("myid", cmd_myid))
app.add_handler(CommandHandler("userinfo", cmd_userinfo))
app.add_handler(CommandHandler("mute", cmd_mute))
app.add_handler(CommandHandler("unmute", cmd_unmute))
app.add_handler(CommandHandler("ban", cmd_ban))
app.add_handler(CommandHandler("unban", cmd_unban))

# ---- MESSAGE HANDLER ----
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

print("Punisher bot with moderation is running...")
app.run_polling()
