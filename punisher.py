import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {527164608}  # add more admin IDs if needed
DB_PATH = "/opt/punisher-bot/db/daily_words.db"

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            row = c.execute(
                "SELECT * FROM words WHERE topic=? ORDER BY RANDOM() LIMIT 1",
                (topic,)
            ).fetchone()
        else:
            row = c.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1").fetchone()
        return row

async def send_word(update_or_query, word_row):
    if not word_row:
        await update_or_query.message.reply_text("No word found.")
        return
    text = f"*Word:* {word_row['word']}\n" \
           f"*Definition:* {word_row['definition']}\n" \
           f"*Example:* {word_row['example']}"
    if hasattr(update_or_query, "callback_query"):
        await update_or_query.callback_query.message.reply_text(text, parse_mode="Markdown")
        if word_row["pronunciation"]:
            await update_or_query.callback_query.message.reply_audio(word_row["pronunciation"])
    else:
        await update_or_query.message.reply_text(text, parse_mode="Markdown")
        if word_row["pronunciation"]:
            await update_or_query.message.reply_audio(word_row["pronunciation"])

# ================= INLINE KEYBOARDS =================
def admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("Add Word", callback_data="admin_add")],
        [InlineKeyboardButton("Bulk Add", callback_data="admin_bulk")],
        [InlineKeyboardButton("Pick Word", callback_data="pick_word")],
        [InlineKeyboardButton("Broadcast", callback_data="admin_broadcast")]
    ]
    return InlineKeyboardMarkup(keyboard)

def student_keyboard():
    keyboard = [
        [InlineKeyboardButton("Get Random Word", callback_data="pick_word")],
        [InlineKeyboardButton("Add Personal Word", callback_data="personal_add")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= STATES =================
ADD_TOPIC, ADD_WORD, ADD_DEFINITION, ADD_EXAMPLE, ADD_PRON, BULK_ADD, BROADCAST = range(7)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # register user for broadcast
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    if user_id in ADMIN_IDS:
        await update.message.reply_text(
            "Welcome Admin! Choose an option:", reply_markup=admin_keyboard()
        )
    else:
        await update.message.reply_text(
            "Welcome! Choose an option:", reply_markup=student_keyboard()
        )
    return ConversationHandler.END  # /start doesn't start a conversation directly

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # ================= ADMIN =================
    if user_id in ADMIN_IDS:
        if data == "admin_add":
            context.user_data["add_mode"] = "single"
            await query.message.reply_text("Send topic for the new word:")
            return ADD_TOPIC
        elif data == "admin_bulk":
            context.user_data["add_mode"] = "bulk"
            await query.message.reply_text("Send words in bulk format (topic|word|definition|example|pronunciation_url per line):")
            return BULK_ADD
        elif data == "admin_broadcast":
            await query.message.reply_text("Send broadcast message:")
            return BROADCAST
        elif data == "pick_word":
            word = pick_word()
            await send_word(query, word)
            return ConversationHandler.END

    # ================= STUDENT =================
    else:
        if data == "pick_word":
            word = pick_word()
            await send_word(query, word)
            return ConversationHandler.END
        elif data == "personal_add":
            context.user_data["add_mode"] = "personal"
            await query.message.reply_text("Send topic for your personal word:")
            return ADD_TOPIC

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
                    if len(parts) < 5:
                        failed += 1
                        continue
                    c.execute(
                        "INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
                        tuple(parts[:5])
                    )
                    success += 1
                except:
                    failed += 1
        await update.message.reply_text(f"Bulk add finished. Success: {success}, Failed: {failed}")
        context.user_data.clear()
        return ConversationHandler.END

# ================= ADD PRON =================
async def add_pron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pron = update.message.text.strip()
    if pron.lower() == "skip":
        pron = None

    topic = context.user_data["topic"]
    word = context.user_data["word"]
    definition = context.user_data["definition"]
    example = context.user_data["example"]

    with db() as c:
        c.execute(
            "INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
            (topic, word, definition, example, pron)
        )

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
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))  # handle non-conversation button clicks

    app.run_polling()

if __name__ == "__main__":
    main()
