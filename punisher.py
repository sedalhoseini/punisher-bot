import os
import random
import sqlite3
import pytz
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
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
            example TEXT
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

def pick_word(topic=None):
    with db() as c:
        if topic:
            rows = c.execute(
                "SELECT * FROM words WHERE topic=? ORDER BY RANDOM() LIMIT 1",
                (topic,)
            ).fetchone()
        else:
            rows = c.execute(
                "SELECT * FROM words ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
        return rows

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

        word = pick_word()
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

# ================= COMMANDS =================
@admin_only
async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage:\n/addword <topic> <word> <definition> <example>"
        )
        return

    topic, word = context.args[0], context.args[1]
    definition = context.args[2]
    example = " ".join(context.args[3:])

    with db() as c:
        c.execute(
            "INSERT INTO words (topic, word, definition, example) VALUES (?, ?, ?, ?)",
            (topic, word, definition, example)
        )

    await update.message.reply_text("Word added.")

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = " ".join(context.args)
    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()

    for u in users:
        await context.bot.send_message(chat_id=u["user_id"], text=msg)

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

    await update.message.reply_text(
        f"Subscribed.\nTime: {send_time}\nTimezone: {tz}"
    )

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("addword", addword))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("subscribe", subscribe))

    app.job_queue.run_repeating(daily_job, interval=60, first=10)
    app.run_polling()

if __name__ == "__main__":
    main()

