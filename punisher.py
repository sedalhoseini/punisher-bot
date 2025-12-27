import os
import sqlite3
from datetime import datetime
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = {527164608}
DB_PATH = "/opt/punisher-bot/db/daily_words.db"

client = Groq(api_key=GROQ_API_KEY)

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
            daily_time TEXT,
            username TEXT
        );
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT,
            level TEXT,
            source TEXT
        );
        CREATE TABLE IF NOT EXISTS personal_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT,
            level TEXT,
            source TEXT
        );
        CREATE TABLE IF NOT EXISTS sent_words (
            user_id INTEGER,
            word_id INTEGER,
            PRIMARY KEY (user_id, word_id)
        );
        """)

# ================= AI =================
def ai_generate_full_word(word: str):
    prompt = f"""
You are an English linguist.

If the word has multiple parts of speech (noun, verb, adjective, etc),
OUTPUT EACH AS A SEPARATE BLOCK.

STRICT FORMAT — REPEAT BLOCKS IF NEEDED:

WORD:
PART_OF_SPEECH:
LEVEL:
TOPIC:
DEFINITION:
EXAMPLE:
PRONUNCIATION:
SOURCE:
---
"""
    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return r.choices[0].message.content.strip()

# ================= KEYBOARDS =================
def main_keyboard_bottom(is_admin=False):
    kb = [
        ["🎯 Get Word", "➕ Add Word"],
        ["📚 List Words", "⏰ Daily Words"]
    ]
    if text == "⏰ Daily Words":
    await update.message.reply_text(
        "Send format:\ncount | time(HH:MM) | level(optional) | pos(optional)\nExample:\n3 | 08:30 | B2 | noun"
    )
    return 30
    if is_admin:
        kb.append(["📦 Bulk Add"])
        kb.append(["📣 Broadcast", "🗑 Clear Words"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def add_word_choice_keyboard():
    return ReplyKeyboardMarkup(
        [["Manual", "🤖 AI"], ["🏠 Cancel"]],
        resize_keyboard=True
    )

def list_keyboard_bottom(is_admin=False):
    if is_admin:
        return ReplyKeyboardMarkup(
            [["Public Words", "Personal Words"], ["🏠 Cancel"]],
            resize_keyboard=True
        )
    else:
        return ReplyKeyboardMarkup(
            [["Words", "My Words", "Clear My Words"], ["🏠 Cancel"]],
            resize_keyboard=True
        )

# ================= HELPERS =================
async def send_word(chat, row):
    if not row:
        await chat.reply_text("No word found.")
        return
    text = (
        f"*Word:* {row['word']}\n"
        f"*Level:* {row['level']}\n"
        f"*Definition:* {row['definition']}\n"
        f"*Example:* {row['example']}\n"
        f"*Pronunciation:* {row['pronunciation']}\n"
        f"*Source:* {row['source']}"
    )
    await chat.reply_text(text, parse_mode="Markdown")

def pick_word_for_user(user_id):
    with db() as c:
        row = c.execute("""
            SELECT * FROM words
            WHERE id NOT IN (
                SELECT word_id FROM sent_words WHERE user_id=?
            )
            ORDER BY RANDOM()
            LIMIT 1
        """, (user_id,)).fetchone()

        if not row:
            c.execute("DELETE FROM sent_words WHERE user_id=?", (user_id,))
            return pick_word_for_user(user_id)

        c.execute(
            "INSERT OR IGNORE INTO sent_words (user_id, word_id) VALUES (?,?)",
            (user_id, row["id"])
        )
        return row

# ================= MAIN MENU =================
async def main_menu_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id

    if text == "🎯 Get Word":
        await send_word(update.message, pick_word_for_user(uid))
        return ConversationHandler.END

    if text == "➕ Add Word":
        context.user_data.clear()
        await update.message.reply_text(
            "Choose how to add the word:",
            reply_markup=add_word_choice_keyboard()
        )
        return 6

    if text == "⏰ Daily Words":
    await update.message.reply_text(
        "Send in this format:\n"
        "count | time(HH:MM) | level(optional) | part-of-speech(optional)\n\n"
        "Example:\n3 | 08:30 | B2 | noun"
    )
    return 30
    if text == "📚 List Words":
        await update.message.reply_text(
            "Choose list type:",
            reply_markup=list_keyboard_bottom(uid in ADMIN_IDS)
        )
        return 20

    if text == "📦 Bulk Add" and uid in ADMIN_IDS:
        await update.message.reply_text(
            "Choose bulk add type:",
            reply_markup=add_word_choice_keyboard()
        )
        return 10

    if text == "📣 Broadcast" and uid in ADMIN_IDS:
        await update.message.reply_text("Send message to broadcast:")
        return 9

    if text == "🗑 Clear Words" and uid in ADMIN_IDS:
        with db() as c:
            c.execute("DELETE FROM words")
        await update.message.reply_text(
            "All words cleared.",
            reply_markup=main_keyboard_bottom(True)
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Main Menu:",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ================= ADD WORD =================
async def add_word_choice_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id

    if text == "🏠 Cancel":
        context.user_data.clear()
        await update.message.reply_text(
            "Main Menu:",
            reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
        )
        return ConversationHandler.END

    if text == "Manual":
        await update.message.reply_text("Send topic:")
        return 0

    if text == "🤖 AI":
        await update.message.reply_text("Send the word:")
        return 7

    return 6

async def manual_add(update, context):
    fields = ["topic", "level", "word", "definition", "example"]
    text = update.message.text.strip()
    for f in fields:
        if f not in context.user_data:
            context.user_data[f] = text
            prompts = {
                "topic": "Level?",
                "level": "Word?",
                "word": "Definition?",
                "definition": "Example?",
                "example": "Pronunciation?"
            }
            await update.message.reply_text(prompts[f])
            return fields.index(f) + 1
    return ConversationHandler.END

async def save_pron(update, context):
    d = context.user_data
    uid = update.effective_user.id
    pron = update.message.text

    with db() as c:
        if uid in ADMIN_IDS:
            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (d["topic"], d["word"], d["definition"], d["example"], pron, d["level"], "Manual")
            )
        else:
            c.execute(
                "INSERT INTO personal_words (user_id, topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?,?)",
                (uid, d["topic"], d["word"], d["definition"], d["example"], pron, d["level"], "Manual")
            )

    context.user_data.clear()
    await update.message.reply_text(
        "Word saved.",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

async def ai_add(update, context):
    uid = update.effective_user.id
    text = ai_generate_full_word(update.message.text.strip())

    blocks = text.split("---")
    inserted = 0

    with db() as c:
        for block in blocks:
            lines = {}
            for line in block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    lines[k.strip()] = v.strip()

            if "WORD" not in lines:
                continue

            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (
                    lines.get("TOPIC", "General"),
                    f"{lines.get('WORD')} ({lines.get('PART_OF_SPEECH','')})",
                    lines.get("DEFINITION", ""),
                    lines.get("EXAMPLE", ""),
                    lines.get("PRONUNCIATION", ""),
                    lines.get("LEVEL", ""),
                    "AI",
                )
            )
            inserted += 1

    await update.message.reply_text(
        f"{inserted} word entries added.",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ================= BULK ADD =================
async def bulk_add_choice(update, context):
    text = update.message.text

    if text == "🏠 Cancel":
        await update.message.reply_text(
            "Main Menu:",
            reply_markup=main_keyboard_bottom(True)
        )
        return ConversationHandler.END

    if text == "Manual":
        await update.message.reply_text(
            "Send lines:\ntopic | level | word | definition | example | pronunciation"
        )
        return 11

    if text == "🤖 AI":
        await update.message.reply_text("Send words (one per line):")
        return 12

    return 10

async def bulk_add_manual(update, context):
    lines = update.message.text.splitlines()
    with db() as c:
        for l in lines:
            p = [x.strip() for x in l.split("|")]
            if len(p) == 6:
                c.execute(
                    "INSERT INTO words (topic, level, word, definition, example, pronunciation, source) VALUES (?,?,?,?,?,?,?)",
                    (*p, "Bulk")
                )
    await update.message.reply_text(
        "Bulk manual add done.",
        reply_markup=main_keyboard_bottom(True)
    )
    return ConversationHandler.END

async def bulk_add_ai(update, context):
    words = [w.strip() for w in update.message.text.splitlines() if w.strip()]

    with db() as c:
        for word in words:
            ai_text = ai_generate_full_word(word)
            lines = {}
            for line in ai_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    lines[k.strip()] = v.strip()

            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (
                    lines.get("TOPIC", "General"),
                    lines.get("WORD", word),
                    lines.get("DEFINITION", ""),
                    lines.get("EXAMPLE", ""),
                    lines.get("PRONUNCIATION", ""),
                    lines.get("LEVEL", ""),
                    lines.get("SOURCE", "AI"),
                )
            )

    await update.message.reply_text(
        "Bulk AI add done.",
        reply_markup=main_keyboard_bottom(True)
    )
    return ConversationHandler.END

# ================= LIST =================
async def list_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id
    username = update.effective_user.username
    is_admin = uid in ADMIN_IDS

    if text == "🏠 Cancel":
        await update.message.reply_text(
            "Main Menu:",
            reply_markup=main_keyboard_bottom(is_admin)
        )
        return ConversationHandler.END

    with db() as c:
        if not is_admin:
            # USER menu
            if text == "Words":
                rows = c.execute(
                    "SELECT topic, level, word FROM words ORDER BY topic, level LIMIT 30"
                ).fetchall()
                msg = "\n".join(f"{r['topic']} | {r['level']} | {r['word']}" for r in rows)

            elif text == "My Words":
                rows = c.execute(
                    "SELECT word FROM personal_words WHERE user_id=? LIMIT 30",
                    (uid,)
                ).fetchall()
                # User words only, no @username
                msg = "\n".join(r["word"] for r in rows)
            elif text == "Clear My Words":
                c.execute("DELETE FROM personal_words WHERE user_id=?", (uid,))
                msg = "Your personal words have been cleared."
            else:
                msg = "No data."
        else:
            # ADMIN menu
            if text == "Public Words":
                rows = c.execute(
                    "SELECT * FROM words ORDER BY topic, level, id LIMIT 50"
                ).fetchall()
                msg = "\n".join(
                    f"{r['topic']} | {r['level']} | {r['word']}" for r in rows
                )
            elif text == "Personal Words":
                rows = c.execute(
                    "SELECT pw.word, u.username FROM personal_words pw "
                    "JOIN users u ON pw.user_id=u.user_id "
                    "ORDER BY u.username, pw.id LIMIT 50"
                ).fetchall()
                msg = "\n".join(f"@{r['username']}: {r['word']}" for r in rows)
            else:
                msg = "No data."

    await update.message.reply_text(
        msg or "No words found.",
        reply_markup=main_keyboard_bottom(is_admin)
    )
    return ConversationHandler.END

# ================= BROADCAST =================
async def broadcast(update, context):
    msg = update.message.text
    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], msg)
        except:
            pass
    await update.message.reply_text(
        "Broadcast sent.",
        reply_markup=main_keyboard_bottom(True)
    )
    return ConversationHandler.END

# ================= START =================
async def start(update, context):
    uid = update.effective_user.id
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (uid,)
        )
    await update.message.reply_text(
        "Main Menu:",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ============== Daily Config ==============
async def daily_config(update, context):
    uid = update.effective_user.id
    text = update.message.text

    try:
        parts = [p.strip() for p in text.split("|")]
        count = int(parts[0])
        time = parts[1]

        level = parts[2] if len(parts) > 2 else None
        pos = parts[3] if len(parts) > 3 else None
    except:
        await update.message.reply_text(
            "Invalid format.\nExample:\n3 | 08:30 | B2 | noun"
        )
        return 30

    with db() as c:
        c.execute("""
            UPDATE users SET
                daily_enabled = 1,
                daily_count = ?,
                daily_time = ?,
                daily_level = ?,
                daily_pos = ?
            WHERE user_id = ?
        """, (count, time, level, pos, uid))

    await update.message.reply_text(
        "Daily words activated.",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ============== Daily Words ==============
async def send_daily_words(context):
    now = datetime.now().strftime("%H:%M")

    with db() as c:
        users = c.execute("""
            SELECT * FROM users
            WHERE daily_enabled = 1
              AND daily_time = ?
        """, (now,)).fetchall()

    for u in users:
        for _ in range(u["daily_count"]):
            word = pick_word_for_user(u["user_id"])
            if not word:
                continue

            text = (
                f"*{word['word']}*\n"
                f"{word['definition']}\n"
                f"_Level: {word['level']}_"
            )

            try:
                await context.bot.send_message(
                    chat_id=u["user_id"],
                    text=text,
                    parse_mode="Markdown"
                )
            except:
                pass

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.job_queue.run_repeating(send_daily_words, interval=60, first=10)
    
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
        ],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            4: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            5: [MessageHandler(filters.ALL, save_pron)],
            6: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_choice_handler)],
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add)],
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast)],
            10: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_choice)],
            11: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_manual)],
            12: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_ai)],
            20: [MessageHandler(filters.TEXT & ~filters.COMMAND, list_handler)],
            30: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_config)],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()




