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
    return f'<a href="tg://user?id={user.id}">{user.full_name or "User"}</a>'

def get_user_mention(user):
    return f"@{user.username}" if user.username else user_link(user)


async def log_action(text, context, channel_id=LOG_CHANNEL_ID):
    try:
        await context.bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"Logging failed: {e}")


# ===== MEDIA FORWARDING =====
async def forward_media(msg, channel_id, context):
    """Forward any type of media with mention and caption."""
    try:
        # Build mention
        user_mention = f"@{msg.from_user.username}" if msg.from_user.username else f'<a href="tg://user?id={msg.from_user.id}">{msg.from_user.full_name}</a>'
        caption = f"{user_mention}: {msg.caption}" if getattr(msg, "caption", None) else user_mention

        # ----- PHOTO -----
        if msg.photo:
            # Take largest size
            file_id = msg.photo[-1].file_id
            await context.bot.send_photo(chat_id=channel_id, photo=file_id, caption=caption, parse_mode="HTML")
            return
        # ----- VIDEO -----
        if msg.video:
            await context.bot.send_video(chat_id=channel_id, video=msg.video.file_id, caption=caption, parse_mode="HTML")
            return
        # ----- ANIMATION (GIF) -----
        if msg.animation:
            await context.bot.send_animation(chat_id=channel_id, animation=msg.animation.file_id, caption=caption, parse_mode="HTML")
            return
        # ----- DOCUMENT (PDF, etc.) -----
        if msg.document:
            await context.bot.send_document(chat_id=channel_id, document=msg.document.file_id, caption=caption, parse_mode="HTML")
            return
        # ----- AUDIO -----
        if msg.audio:
            await context.bot.send_audio(chat_id=channel_id, audio=msg.audio.file_id, caption=caption, parse_mode="HTML")
            return
        # ----- VOICE -----
        if msg.voice:
            await context.bot.send_voice(chat_id=channel_id, voice=msg.voice.file_id, caption=caption, parse_mode="HTML")
            return
        # ----- STICKER -----
        if msg.sticker:
            await context.bot.send_sticker(chat_id=channel_id, sticker=msg.sticker.file_id)
            # Send mention separately
            await context.bot.send_message(chat_id=channel_id, text=user_mention, parse_mode="HTML")
            return

    except Exception as e:
        print(f"Media forwarding failed: {e}")


# ===== HANDLE MESSAGES =====
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    # ----- PRIVATE MESSAGE FORWARDING -----
    if msg.photo or msg.video or msg.animation or msg.document or msg.audio or msg.voice or msg.sticker:
        await forward_media(msg, MESSAGES_CHANNEL_ID, context)

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

        # Keyword / link spam
        if FILTER_PATTERNS.search(normalized):
            try:
                await msg.delete()
            except:
                pass
            return

        # Repeated messages
        last_msg, last_time = last_user_messages.get(user_id, ("", 0))
        if normalized == last_msg and now - last_time < 10:  # 10s threshold
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
    await update.message.reply_text("@SedAl_Hoseini")

async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = None

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
async def resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resolve user from reply, username, or numeric ID."""
    msg = update.message
    user = None

    # 1️⃣ Reply
    if msg.reply_to_message and msg.reply_to_message.from_user:
        user = msg.reply_to_message.from_user

    # 2️⃣ Username or ID in args
    elif context.args:
        arg = context.args[0]
        if arg.startswith("@"):
            arg = arg[1:]
        try:
            user = await context.bot.get_chat(arg)
        except:
            try:
                user_id = int(arg)
                user = await context.bot.get_chat(user_id)
            except:
                await msg.reply_text("Cannot find user.")
                return None
    else:
        await msg.reply_text("You must reply to a user or provide username/ID.")
        return None

    return user

@admin_only
async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = await resolve_user(update, context)
    if not user:
        return

    duration = 3600  # default 1 hour
    if len(context.args) > 1:
        try:
            duration = int(context.args[1])
        except:
            pass

    try:
        await context.bot.restrict_chat_member(
            chat_id=msg.chat_id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.utcnow() + timedelta(seconds=duration)
        )
        await msg.reply_text(f"{user_link(user)} muted for {duration} seconds.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to mute: {e}")

@admin_only
async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = await resolve_user(update, context)
    if not user:
        return

    try:
        # Only use supported fields for ChatPermissions
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True
        )
        await context.bot.restrict_chat_member(chat_id=msg.chat_id, user_id=user.id, permissions=permissions)
        await msg.reply_text(f"{user_link(user)} has been unmuted.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to unmute: {e}")

@admin_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = await resolve_user(update, context)
    if not user:
        return
    try:
        await context.bot.ban_chat_member(chat_id=msg.chat_id, user_id=user.id)
        await msg.reply_text(f"{user_link(user)} has been banned.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to ban: {e}")

@admin_only
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not context.args:
        await msg.reply_text("Provide user ID to unban.")
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

print("Punisher bot with full moderation is running...")
app.run_polling()




