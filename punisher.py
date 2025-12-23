import os
import random
import sqlite3
import pytz
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {527164608}
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
            timezone TEXT,
            send_time TEXT,
            last_sent TEXT
        );

        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT,
            user_added INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_words (
            user_id INTEGER,
            word_id INTEGER,
            seen INTEGER DEFAULT 0,
            learned INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, word_id)
        );
        """)

# ================= HELPERS =================
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("Admin only.")
            return
        return await func(update, context)
    return wrapper

def pick_word(user_id=None, topic=None):
    with db() as c:
        query = "SELECT * FROM words"
        params = []
        if topic:
            query += " WHERE topic=?"
            params.append(topic)
        query += " ORDER BY RANDOM() LIMIT 1"
        word = c.execute(query, params).fetchone()

        if word and user_id:
            # track seen word
            c.execute(
                "INSERT OR IGNORE INTO user_words (user_id, word_id, seen) VALUES (?, ?, 1)",
                (user_id, word["id"])
            )
        return word

async def send_word(update: Update, context: ContextTypes.DEFAULT_TYPE, word_row):
    if not word_row:
        await update.message.reply_text("No words available.")
        return

    text = (
        f"📘 *{word_row['word']}*\n"
        f"{word_row['definition']}\n\n"
        f"_Example:_ {word_row['example']}"
    )
    if word_row['pronunciation']:
        text += f"\n\n🔊 Pronunciation: {word_row['pronunciation']}"

    keyboard = [
        [InlineKeyboardButton("✅ Learned", callback_data=f"learned_{word_row['id']}")],
        [InlineKeyboardButton("➡️ Next Word", callback_data=f"next_{word_row['id']}")]
    ]
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ================= DAILY JOB =================
async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        users = c.execute("SELECT * FROM users").fetchall()

    for u in users:
        tz = pytz.timezone(u["timezone"])
        now = datetime.now(tz)
        hour, minute = map(int, u["send_time"].split(":"))

        if now.hour != hour or now.minute != minute:
            continue

        today = now.strftime("%Y-%m-%d")
        if u["last_sent"] == today:
            continue

        word = pick_word(u["user_id"])
        if not word:
            continue

        text = (
            f"📘 *Word of the Day*\n\n"
            f"*{word['word']}*\n"
            f"{word['definition']}\n\n"
            f"_Example:_ {word['example']}"
        )

        await context.bot.send_message(
            chat_id=u["user_id"],
            text=text,
            parse_mode="Markdown"
        )

        with db() as c:
            c.execute(
                "UPDATE users SET last_sent=? WHERE user_id=?",
                (today, u["user_id"])
            )

# ================= ADMIN COMMANDS =================
@admin_only
async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage:\n/addword <topic> <word> <definition> <example> [pronunciation]"
        )
        return
    topic, word, definition = context.args[0], context.args[1], context.args[2]
    example = context.args[3]
    pronunciation = " ".join(context.args[4:]) if len(context.args) > 4 else None

    with db() as c:
        c.execute(
            "INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
            (topic, word, definition, example, pronunciation)
        )
    await update.message.reply_text("Word added.")

@admin_only
async def bulk_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send words in this format:\n`topic|word|definition|example|pronunciation`\nOne word per line.",
        parse_mode="Markdown"
    )

async def process_bulk_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().split("\n")
    with db() as c:
        for line in lines:
            parts = line.split("|")
            if len(parts) < 4:
                continue
            topic, word, definition, example = parts[:4]
            pronunciation = parts[4] if len(parts) > 4 else None
            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
                (topic, word, definition, example, pronunciation)
            )
    await update.message.reply_text("Bulk words added.")

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = " ".join(context.args).strip()
    if not msg:
        await update.message.reply_text("Cannot broadcast empty message!")
        return
    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    for u in users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=msg)
        except Exception as e:
            print(f"Failed to send to {u['user_id']}: {e}")
    await update.message.reply_text("Broadcast sent.")

# ================= STUDENT COMMANDS =================
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    send_time = "09:00"
    tz = DEFAULT_TZ

    for arg in context.args:
        if arg.startswith("time="):
            send_time = arg.split("=", 1)[1]
        elif arg.startswith("tz="):
            tz = arg.split("=", 1)[1]

    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO users VALUES (?, ?, ?, NULL)",
            (user_id, tz, send_time)
        )

    await update.message.reply_text(f"Subscribed.\nTime: {send_time}\nTimezone: {tz}")

async def get_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    word = pick_word(user_id)
    await send_word(update, context, word)

async def review_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with db() as c:
        rows = c.execute(
            "SELECT w.word, w.definition, w.example FROM words w "
            "JOIN user_words uw ON w.id = uw.word_id "
            "WHERE uw.user_id=? AND uw.learned=1",
            (user_id,)
        ).fetchall()
    if not rows:
        await update.message.reply_text("No learned words to review.")
        return
    text = "📚 *Your Learned Words:*\n\n"
    for r in rows:
        text += f"*{r['word']}* - {r['definition']}\n_Example:_ {r['example']}\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_personal_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage:\n/addpersonal <topic> <word> <definition> <example> [pronunciation]"
        )
        return
    topic, word, definition = context.args[0], context.args[1], context.args[2]
    example = context.args[3]
    pronunciation = " ".join(context.args[4:]) if len(context.args) > 4 else None

    with db() as c:
        c.execute(
            "INSERT INTO words (topic, word, definition, example, pronunciation, user_added) VALUES (?, ?, ?, ?, ?, 1)",
            (topic, word, definition, example, pronunciation)
        )
    await update.message.reply_text("Personal word added successfully!")

async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        rows = c.execute("SELECT DISTINCT topic FROM words").fetchall()
    topics = [r['topic'] for r in rows]
    await update.message.reply_text("Available topics:\n" + "\n".join(topics))

# ================= CALLBACK HANDLERS =================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("learned_"):
        word_id = int(data.split("_")[1])
        with db() as c:
            c.execute(
                "INSERT OR REPLACE INTO user_words (user_id, word_id, seen, learned) VALUES (?, ?, 1, 1)",
                (user_id, word_id)
            )
        await query.edit_message_text("Marked as learned ✅")
    elif data.startswith("next_"):
        word = pick_word(user_id)
        await send_word(update, context, word)

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Admin
    app.add_handler(CommandHandler("addword", addword))
    app.add_handler(CommandHandler("bulk_add", bulk_add))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_bulk_text))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Student
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("get_word", get_word))
    app.add_handler(CommandHandler("review_words", review_words))
    app.add_handler(CommandHandler("addpersonal", add_personal_word))
    app.add_handler(CommandHandler("list_topics", list_topics))

    # Callback for buttons
    app.add_handler(CallbackQueryHandler(button_callback))

    # Daily job
    app.job_queue.run_repeating(daily_job, interval=60, first=10)

    app.run_polling()

if __name__ == "__main__":
    main()
