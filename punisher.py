import os
import sqlite3
from datetime import datetime
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
        """)

# ================= AI GENERATION =================
def ai_generate_full_word(word: str):
    prompt = f"""
You are an English linguist. Provide accurate info for '{word}'.
STRICT FORMAT:
WORD: <word>
LEVEL: <A1/A2/B1/B2/C1/C2>
TOPIC: <topic>
DEFINITION: <definition>
EXAMPLE: <example>
PRONUNCIATION: <IPA or text>
SOURCE: <text>
Separate each block with '---'.
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
        ["🎯 Get Word", "➕ Add Word (Manual)"],
        ["🤖 Add Word (AI)", "📚 My Words"]
    ]
    if is_admin:
        kb.append(["📦 Bulk Add", "📋 List", "📣 Broadcast", "🗑 Clear Words"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ================= HELPERS =================
async def send_word(chat, row, is_admin=False):
    if not row:
        await chat.reply_text("No word found.")
        return

    source_display = row["source"]

    text = (
        f"*Word:* {row['word']}\n"
        f"*Level:* {row['level']}\n"
        f"*Definition:* {row['definition']}\n"
        f"*Example:* {row['example']}\n"
        f"*Pronunciation:* {row['pronunciation']}\n"
        f"*Source:* {source_display}"
    )
    await chat.reply_text(text, parse_mode="Markdown")

def pick_word_from_db(topic=None, level=None):
    with db() as c:
        q = "SELECT * FROM words"
        params = []
        if topic:
            q += " WHERE topic=?"
            params.append(topic)
            if level:
                q += " AND level=?"
                params.append(level)
        elif level:
            q += " WHERE level=?"
            params.append(level)
        q += " ORDER BY RANDOM() LIMIT 1"
        return c.execute(q, params).fetchone()

# ================= MAIN MENU HANDLER =================
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    username = update.effective_user.username

    # 🎯 Get Word
    if text == "🎯 Get Word":
        row = pick_word_from_db()
        await send_word(update.message, row, uid in ADMIN_IDS)
        return ConversationHandler.END

    # ➕ Add Word (Manual)
    if text == "➕ Add Word (Manual)":
        await update.message.reply_text("Send topic first:")
        context.user_data.clear()
        return 0

    # 🤖 Add Word (AI)
    if text == "🤖 Add Word (AI)":
        await update.message.reply_text("Send the word to generate via AI:")
        context.user_data.clear()
        return 7

    # 📚 My Words
    if text == "📚 My Words":
        with db() as c:
            words = c.execute("SELECT * FROM personal_words WHERE user_id=?", (uid,)).fetchall()
        if not words:
            await update.message.reply_text("You have no personal words.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
            return ConversationHandler.END

        text_msg = ""
        for row in words:
            text_msg += (
                f"*Word:* {row['word']}\n"
                f"*Level:* {row['level']}\n"
                f"*Definition:* {row['definition']}\n"
                f"*Example:* {row['example']}\n"
                f"*Pronunciation:* {row['pronunciation']}\n"
                f"*Source:* {row['source']}\n\n"
            )
        await update.message.reply_text(text_msg.strip(), parse_mode="Markdown", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
        return ConversationHandler.END

    # Admin only commands
    if uid in ADMIN_IDS:
        if text == "📦 Bulk Add":
            await update.message.reply_text("Send words in format: topic|level|word|definition|example")
            return 8
        if text == "📋 List":
            # Show words grouped by level/topic for admin
            with db() as c:
                words = c.execute("SELECT * FROM personal_words").fetchall()
            if not words:
                await update.message.reply_text("No personal words yet.", reply_markup=main_keyboard_bottom(True))
                return ConversationHandler.END
            text_msg = ""
            for row in words:
                try:
                    user_row = update.effective_chat.get_member(row["user_id"])
                    uname = "@" + (user_row.user.username or str(row["user_id"]))
                except:
                    uname = str(row["user_id"])
                text_msg += (
                    f"{uname}: *{row['word']}* ({row['level']}) - {row['topic']}\n"
                )
            await update.message.reply_text(text_msg.strip(), parse_mode="Markdown", reply_markup=main_keyboard_bottom(True))
            return ConversationHandler.END
        if text == "📣 Broadcast":
            await update.message.reply_text("Send message to broadcast:")
            return 9
        if text == "🗑 Clear Words":
            with db() as c:
                c.execute("DELETE FROM words")
            await update.message.reply_text("All words cleared.", reply_markup=main_keyboard_bottom(True))
            return ConversationHandler.END

    # fallback
    await update.message.reply_text("Unknown action.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
    return ConversationHandler.END

# ================= MANUAL ADD =================
async def manual_add(update, context):
    text = update.message.text.strip()
    fields = ["topic", "level", "word", "definition", "example"]
    for f in fields:
        if f not in context.user_data:
            context.user_data[f] = text
            next_prompt = {
                "topic": "Level?",
                "level": "Word?",
                "word": "Definition?",
                "definition": "Example?",
                "example": "Send pronunciation text or audio:"
            }[f]
            await update.message.reply_text(next_prompt)
            return fields.index(f)+1
    return 5  # go to pronunciation step

async def save_pron(update, context):
    pron = update.message.text or "Audio received"
    d = context.user_data
    uid = update.effective_user.id
    with db() as c:
        c.execute(
            "INSERT INTO personal_words VALUES (NULL,?,?,?,?,?,?,?,?)",
            (uid, d["topic"], d["word"], d["definition"], d["example"], pron, d["level"], "Manual")
        )
    await update.message.reply_text("Word saved.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
    context.user_data.clear()
    return ConversationHandler.END

# ================= AI ADD =================
async def ai_add(update, context):
    word = update.message.text.strip()
    added_count = 0
    uid = update.effective_user.id
    try:
        ai_text = ai_generate_full_word(word)
    except Exception:
        await update.message.reply_text("Failed to generate AI word.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
        return ConversationHandler.END

    blocks = [b.strip() for b in ai_text.split("---") if b.strip()]
    if not blocks:
        await update.message.reply_text("No word generated.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
        return ConversationHandler.END

    b = blocks[0]
    lines = {}
    for line in b.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            lines[key.strip().upper()] = value.strip()

    topic_val = lines.get("TOPIC", "General")
    level_val = lines.get("LEVEL", "N/A")
    word_val = lines.get("WORD", word)
    definition_val = lines.get("DEFINITION", "")
    example_val = lines.get("EXAMPLE", "")
    pronunciation_val = lines.get("PRONUNCIATION", "")
    source_val = lines.get("SOURCE", "AI")

    with db() as c:
        c.execute(
            "INSERT INTO personal_words VALUES (NULL,?,?,?,?,?,?,?,?)",
            (uid, topic_val, word_val, definition_val, example_val, pronunciation_val, level_val, source_val)
        )
        added_count += 1

    await update.message.reply_text(f"AI word added successfully. Total added: {added_count}", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
    return ConversationHandler.END

# ================= BULK ADD =================
async def bulk_add(update, context):
    ok = 0
    with db() as c:
        for l in update.message.text.splitlines():
            try:
                t, lv, w, d, e = l.split("|")
                c.execute(
                    "INSERT INTO words VALUES (NULL,?,?,?,?,?,?,?)",
                    (t, w, d, e, "", lv, "Bulk")
                )
                ok += 1
            except:
                continue
    await update.message.reply_text(f"Added {ok} words.", reply_markup=main_keyboard_bottom(True))
    return ConversationHandler.END

# ================= BROADCAST =================
async def broadcast(update, context):
    msg = update.message.text
    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    for u in users:
        if u["user_id"] not in ADMIN_IDS:
            try:
                await context.bot.send_message(u["user_id"], msg)
            except:
                continue
    await update.message.reply_text("Broadcast sent.", reply_markup=main_keyboard_bottom(True))
    return ConversationHandler.END

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, username))
    await update.message.reply_text(
        "Main Menu:",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

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
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add)],
            8: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add)],
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast)],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(lambda u, c: None))  # kept placeholder if needed

    app.run_polling()

if __name__ == "__main__":
    main()
