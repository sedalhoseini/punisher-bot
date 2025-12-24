import os
import sqlite3
from datetime import datetime
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
            daily_time TEXT
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
SOURCE: <website>
Separate each block with '---'.
"""
    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return r.choices[0].message.content.strip()

# ================= KEYBOARDS =================
def main_keyboard(is_admin=False):
    kb = [
        [InlineKeyboardButton("🎯 Get Word", callback_data="pick_word")],
        [InlineKeyboardButton("➕ Add Word (Manual)", callback_data="add_manual")],
        [InlineKeyboardButton("🤖 Add Word (AI)", callback_data="add_ai")],
        [InlineKeyboardButton("📚 My Words", callback_data="my_words")],
    ]
    if is_admin:
        kb += [
            [InlineKeyboardButton("📦 Bulk Add", callback_data="bulk_add")],
            [InlineKeyboardButton("📋 List", callback_data="admin_list")],
            [InlineKeyboardButton("📣 Broadcast", callback_data="broadcast")],
            [InlineKeyboardButton("🗑 Clear Words", callback_data="clear_words")],
        ]
    return InlineKeyboardMarkup(kb)

def list_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("By Topic", callback_data="list_topic")],
        [InlineKeyboardButton("By Level", callback_data="list_level")],
        [InlineKeyboardButton("Just Words", callback_data="list_words")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])

# ================= HELPERS =================
async def send_word(chat, row, is_admin=False):
    if not row:
        await chat.reply_text("No word found.", reply_markup=main_keyboard(is_admin))
        return

    source_text = row["source"]
    if source_text.startswith("http"):  # full URL
        source_display = f"[Source]({source_text})"
    else:  # just show as name
        source_display = f"[{source_text}](https://{source_text.replace('https://','')})"

    text = (
        f"*Word:* {row['word']}\n"
        f"*Level:* {row['level']}\n"
        f"*Definition:* {row['definition']}\n"
        f"*Example:* {row['example']}\n"
        f"*Pronunciation:* {row['pronunciation']}\n"
        f"*Source:* {source_display}"
    )
    await chat.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(is_admin))

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

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "main_menu":
        await q.message.reply_text("Main Menu:", reply_markup=main_keyboard(uid in ADMIN_IDS))
        return ConversationHandler.END

    # ================= USER WORDS =================
    if d.startswith("my_words"):
        page = int(d.split("_")[2]) if len(d.split("_")) > 2 else 0
        with db() as c:
            words = c.execute("SELECT * FROM personal_words WHERE user_id=? ORDER BY id", (uid,)).fetchall()
        if not words:
            await q.message.reply_text("You have no personal words.", reply_markup=main_keyboard(uid in ADMIN_IDS))
            return ConversationHandler.END

        page_size = 10
        start = page * page_size
        end = start + page_size
        page_words = words[start:end]

        text = ""
        for row in page_words:
            source_display = f"[{row['source']}](https://{row['source'].replace('https://','')})"
            text += (
                f"*Word:* {row['word']}\n"
                f"*Level:* {row['level']}\n"
                f"*Definition:* {row['definition']}\n"
                f"*Example:* {row['example']}\n"
                f"*Pronunciation:* {row['pronunciation']}\n"
                f"*Source:* {source_display}\n\n"
            )

        kb = []
        if start > 0:
            kb.append(InlineKeyboardButton("⬅ Previous", callback_data=f"my_words_{page-1}"))
        if end < len(words):
            kb.append(InlineKeyboardButton("Next ➡", callback_data=f"my_words_{page+1}"))
        kb.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))
        reply_markup = InlineKeyboardMarkup([kb])
        await q.message.reply_text(text.strip(), parse_mode="Markdown", reply_markup=reply_markup)
        return ConversationHandler.END

    # ================= PICK WORD =================
    if d == "pick_word":
        row = pick_word_from_db()
        await send_word(q.message, row, uid in ADMIN_IDS)
        return ConversationHandler.END

    # ================= MANUAL / AI / BULK =================
    if d == "add_manual":
        context.user_data.clear()
        await q.message.reply_text("Topic?")
        return 0
    if d == "add_ai":
        await q.message.reply_text("Send the word only:")
        return 7
    if d == "bulk_add":
        await q.message.reply_text("Send bulk lines: topic|level|word|definition|example")
        return 8

    # ================= ADMIN ONLY =================
    if d == "clear_words" and uid in ADMIN_IDS:
        with db() as c:
            c.execute("DELETE FROM words")
        await q.message.reply_text("All words cleared.")
        return ConversationHandler.END

    if d == "broadcast" and uid in ADMIN_IDS:
        await q.message.reply_text("Send broadcast message:")
        return 9

    # ================= LIST BUTTONS =================
    if d == "admin_list" and uid in ADMIN_IDS:
        await q.message.reply_text("Choose list type:", reply_markup=list_keyboard())
        return ConversationHandler.END
    if d == "list_topic":
        with db() as c:
            topics = c.execute("SELECT DISTINCT topic FROM words").fetchall()
        await q.message.reply_text("\n".join([t["topic"] for t in topics]) or "Empty", reply_markup=main_keyboard(uid in ADMIN_IDS))
        return ConversationHandler.END
    if d == "list_level":
        with db() as c:
            levels = c.execute("SELECT DISTINCT level FROM words").fetchall()
        await q.message.reply_text("\n".join([l["level"] for l in levels]) or "Empty", reply_markup=main_keyboard(uid in ADMIN_IDS))
        return ConversationHandler.END
    if d == "list_words":
        with db() as c:
            words = c.execute("SELECT word FROM words").fetchall()
        await q.message.reply_text("\n".join([w["word"] for w in words]) or "Empty", reply_markup=main_keyboard(uid in ADMIN_IDS))
        return ConversationHandler.END

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
    return ConversationHandler.END

async def save_pron(update, context):
    pron = update.message.text or "Audio received"
    d = context.user_data
    with db() as c:
        c.execute(
            "INSERT INTO words VALUES (NULL,?,?,?,?,?,?,?)",
            (d["topic"], d["word"], d["definition"], d["example"], pron, d["level"], "Manual")
        )
    await update.message.reply_text("Word saved.", reply_markup=main_keyboard(True))
    context.user_data.clear()
    return ConversationHandler.END

# ================= AI ADD =================
async def ai_add(update, context):
    word = update.message.text.strip()
    added_count = 0
    try:
        ai_text = ai_generate_full_word(word)
    except Exception:
        await update.message.reply_text("Failed to generate AI word.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    blocks = [b.strip() for b in ai_text.split("---") if b.strip()]
    if not blocks:
        await update.message.reply_text("No word generated.", reply_markup=main_keyboard(True))
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
            "INSERT INTO words VALUES (NULL,?,?,?,?,?,?,?)",
            (topic_val, word_val, definition_val, example_val, pronunciation_val, level_val, source_val)
        )
        added_count += 1

    await update.message.reply_text(f"AI word added successfully. Total added: {added_count}", reply_markup=main_keyboard(True))
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
    await update.message.reply_text(f"Added {ok} words.", reply_markup=main_keyboard(True))
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
    await update.message.reply_text("Broadcast sent.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    await update.message.reply_text("Main Menu:", reply_markup=main_keyboard(uid in ADMIN_IDS))
    return ConversationHandler.END

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler), CommandHandler("start", start)],
        states={
            0: [MessageHandler(filters.TEXT, manual_add)],
            1: [MessageHandler(filters.TEXT, manual_add)],
            2: [MessageHandler(filters.TEXT, manual_add)],
            3: [MessageHandler(filters.TEXT, manual_add)],
            4: [MessageHandler(filters.TEXT, manual_add)],
            5: [MessageHandler(filters.ALL, save_pron)],
            7: [MessageHandler(filters.TEXT, ai_add)],
            8: [MessageHandler(filters.TEXT, bulk_add)],
            9: [MessageHandler(filters.TEXT, broadcast)],
        },
        fallbacks=[]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
