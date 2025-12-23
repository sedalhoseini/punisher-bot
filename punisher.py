import os
import sqlite3
import asyncio
import pytz
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {527164608}  # Add more admins if needed
DB_PATH = "/opt/punisher-bot/db/daily_words.db"
DEFAULT_TZ = "Asia/Tehran"

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            daily_time TEXT
        );

        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT
        );

        CREATE TABLE IF NOT EXISTS personal_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT
        );
        """)

# ================= HELPERS =================
def pick_word(topic=None):
    with db() as c:
        if topic:
            row = c.execute("SELECT * FROM words WHERE topic=? ORDER BY RANDOM() LIMIT 1", (topic,)).fetchone()
        else:
            row = c.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1").fetchone()
        return row

def fetch_pronunciation(word):
    """
    Placeholder: Replace with AI/dictionary API call to get pronunciation audio URL
    """
    return None  # Example: return "https://.../audio.mp3"

async def send_word(chat, word_row):
    if not word_row:
        await chat.send_message("No word found.")
        return
    text = f"*Word:* {word_row['word']}\n*Definition:* {word_row['definition']}\n*Example:* {word_row['example']}"
    await chat.send_message(text, parse_mode="Markdown")
    if word_row.get("pronunciation"):
        await chat.send_audio(word_row["pronunciation"])

# ================= KEYBOARDS =================
def admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("Add Word", callback_data="admin_add")],
        [InlineKeyboardButton("Bulk Add", callback_data="admin_bulk")],
        [InlineKeyboardButton("Pick Word", callback_data="pick_word")],
        [InlineKeyboardButton("Clear Words", callback_data="admin_clear")],
        [InlineKeyboardButton("List Topics", callback_data="admin_topics")],
        [InlineKeyboardButton("List Words", callback_data="admin_words")],
        [InlineKeyboardButton("List Subscribers", callback_data="admin_users")],
        [InlineKeyboardButton("Broadcast", callback_data="admin_broadcast")]
    ]
    return InlineKeyboardMarkup(keyboard)

def student_keyboard():
    keyboard = [
        [InlineKeyboardButton("Get Random Word", callback_data="pick_word")],
        [InlineKeyboardButton("Add Personal Word", callback_data="personal_add")],
        [InlineKeyboardButton("My Words", callback_data="my_words")],
        [InlineKeyboardButton("Set Daily Word Time", callback_data="set_daily_time")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= STATES =================
ADD_TOPIC, ADD_WORD, ADD_DEFINITION, ADD_EXAMPLE, ADD_PRON, BULK_ADD, BROADCAST, DAILY_TIME = range(8)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    if user_id in ADMIN_IDS:
        await update.message.reply_text("Welcome Admin! Choose an option:", reply_markup=admin_keyboard())
    else:
        await update.message.reply_text("Welcome! Choose an option:", reply_markup=student_keyboard())
    return ConversationHandler.END

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # ---------------- ADMIN ----------------
    if user_id in ADMIN_IDS:
        if data == "admin_add":
            context.user_data["add_mode"] = "single"
            await query.message.reply_text("Send topic for the new word:")
            return ADD_TOPIC
        elif data == "admin_bulk":
            context.user_data["add_mode"] = "bulk"
            await query.message.reply_text("Send words in bulk: topic|word|definition|example per line")
            return BULK_ADD
        elif data == "pick_word":
            word = pick_word()
            await send_word(query.message, word)
            return ConversationHandler.END
        elif data == "admin_clear":
            with db() as c:
                c.execute("DELETE FROM words")
            await query.message.reply_text("All words cleared!")
        elif data == "admin_topics":
            with db() as c:
                topics = c.execute("SELECT DISTINCT topic FROM words").fetchall()
            await query.message.reply_text("\n".join([t["topic"] for t in topics]) or "No topics.")
        elif data == "admin_words":
            with db() as c:
                words = c.execute("SELECT word FROM words").fetchall()
            await query.message.reply_text("\n".join([w["word"] for w in words]) or "No words.")
        elif data == "admin_users":
            with db() as c:
                users = c.execute("SELECT user_id FROM users").fetchall()
            await query.message.reply_text("Subscribers:\n" + "\n".join([str(u["user_id"]) for u in users]))
        elif data == "admin_broadcast":
            await query.message.reply_text("Send broadcast message:")
            return BROADCAST
    # ---------------- STUDENT ----------------
    else:
        if data == "pick_word":
            word = pick_word()
            await send_word(query.message, word)
            return ConversationHandler.END
        elif data == "personal_add":
            context.user_data["add_mode"] = "personal"
            await query.message.reply_text("Send topic for your personal word:")
            return ADD_TOPIC
        elif data == "my_words":
            with db() as c:
                words = c.execute("SELECT * FROM personal_words WHERE user_id=?", (user_id,)).fetchall()
            if words:
                msg = "\n".join([f"{w['word']} ({w['topic']})" for w in words])
            else:
                msg = "No personal words added."
            await query.message.reply_text(msg)
        elif data == "set_daily_time":
            await query.message.reply_text("Send the time to receive daily word in HH:MM (24h) format:")
            return DAILY_TIME

    return ConversationHandler.END

# ================= ADD WORD FLOW =================
async def add_word_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("add_mode")
    text = update.message.text.strip()

    if mode in ["single", "personal"]:
        if "topic" not in context.user_data:
            context.user_data["topic"] = text
            await update.message.reply_text("Send the word:")
            return ADD_WORD
        elif "word" not in context.user_data:
            context.user_data["word"] = text
            await update.message.reply_text("Send the definition:")
            return ADD_DEFINITION
        elif "definition" not in context.user_data:
            context.user_data["definition"] = text
            await update.message.reply_text("Send an example sentence:")
            return ADD_EXAMPLE
        elif "example" not in context.user_data:
            context.user_data["example"] = text
            await update.message.reply_text("Send pronunciation audio URL (or type 'skip'):")
            return ADD_PRON
    elif mode == "bulk":
        lines = text.splitlines()
        success, failed = 0, 0
        with db() as c:
            for line in lines:
                try:
                    parts = line.split("|")
                    if len(parts) < 4:
                        failed += 1
                        continue
                    topic, word, definition, example = parts[:4]
                    pron = parts[4] if len(parts) >= 5 else fetch_pronunciation(word)
                    c.execute("INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
                              (topic, word, definition, example, pron))
                    success += 1
                except:
                    failed += 1
        await update.message.reply_text(f"Bulk add finished. Success: {success}, Failed: {failed}")
        context.user_data.clear()
        return ConversationHandler.END
    return ADD_PRON

# ================= ADD PRON =================
async def add_pron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pron = update.message.text.strip()
    if pron.lower() == "skip":
        pron = fetch_pronunciation(context.user_data["word"])

    topic = context.user_data["topic"]
    word = context.user_data["word"]
    definition = context.user_data["definition"]
    example = context.user_data["example"]
    user_id = update.effective_user.id

    with db() as c:
        if context.user_data.get("add_mode") == "personal":
            c.execute("INSERT INTO personal_words (user_id, topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?, ?)",
                      (user_id, topic, word, definition, example, pron))
        else:
            c.execute("INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
                      (topic, word, definition, example, pron))

    await update.message.reply_text(f"Word '{word}' added successfully!")
    context.user_data.clear()
    return ConversationHandler.END

# ================= BROADCAST =================
async def broadcast_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    if not msg:
        await update.message.reply_text("Cannot send empty message.")
        return ConversationHandler.END

    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()

    sent = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=msg)
            sent += 1
        except:
            continue

    await update.message.reply_text(f"Broadcast sent to {sent} users.")
    return ConversationHandler.END

# ================= SET DAILY TIME =================
async def set_daily_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    time_text = update.message.text.strip()
    try:
        datetime.strptime(time_text, "%H:%M")
        with db() as c:
            c.execute("UPDATE users SET daily_time=? WHERE user_id=?", (time_text, user_id))
        await update.message.reply_text(f"Daily word time set to {time_text}")
    except:
        await update.message.reply_text("Invalid format. Use HH:MM (24h).")
    return ConversationHandler.END

# ================= DAILY WORD TASK =================
async def daily_word_task(app):
    while True:
        now_utc = datetime.utcnow()
        with db() as c:
            users = c.execute("SELECT user_id, daily_time FROM users WHERE daily_time IS NOT NULL").fetchall()
        for u in users:
            tz = pytz.timezone(DEFAULT_TZ)
            now_local = now_utc.astimezone(tz)
            if u["daily_time"] == now_local.strftime("%H:%M"):
                word = pick_word()
                if word:
                    chat = await app.bot.get_chat(u["user_id"])
                    await send_word(chat, word)
        await asyncio.sleep(60)

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_handler)],
        states={
            ADD_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_flow)],
            ADD_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_flow)],
            ADD_DEFINITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_flow)],
            ADD_EXAMPLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_flow)],
            ADD_PRON: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_pron)],
            BULK_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_flow)],
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_flow)],
            DAILY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_daily_time)],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))

    # Start daily word scheduler
    loop = asyncio.get_event_loop()
    loop.create_task(daily_word_task(app))

    app.run_polling()

if __name__ == "__main__":
    main()
