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
def main_keyboard_bottom(is_admin=False):
    kb = [
        ["🎯 Get Word", "➕ Add Word"],
        ["📚 List Words"]
    ]
    if is_admin:
        kb.append(["📦 Bulk Add", "📋 List"])
        kb.append(["📣 Broadcast", "🗑 Clear Words"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def add_word_choice_keyboard():
    kb = [
        ["Manual", "🤖 AI"],
        ["🏠 Cancel"]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def list_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("By Topic", callback_data="list_topic")],
        [InlineKeyboardButton("By Level", callback_data="list_level")],
        [InlineKeyboardButton("Just Words", callback_data="list_words")],
        [InlineKeyboardButton("User Words", callback_data="list_user_words")],
        [InlineKeyboardButton("🏠 Close List", callback_data="close_list")]
    ])

def paginate_keyboard(page, total_pages, prefix):
    kb = []
    if page > 0:
        kb.append(InlineKeyboardButton("⬅ Previous", callback_data=f"{prefix}_{page-1}"))
    if page < total_pages - 1:
        kb.append(InlineKeyboardButton("Next ➡", callback_data=f"{prefix}_{page+1}"))
    kb.append(InlineKeyboardButton("🏠 Close", callback_data="close_list"))
    return InlineKeyboardMarkup([kb])

# ================= HELPERS =================
async def send_word(chat, row, is_admin=False):
    if not row:
        await chat.reply_text("No word found.")
        return

    source_display = row["source"]  # No links

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

    if text == "🎯 Get Word":
        row = pick_word_from_db()
        await send_word(update.message, row, uid in ADMIN_IDS)
        return ConversationHandler.END

    if text == "➕ Add Word":
        await update.message.reply_text("Choose how to add the word:", reply_markup=add_word_choice_keyboard())
        context.user_data.clear()
        return 6  # AI/Manual choice

    if text == "📚 List Words":
        await update.message.reply_text("Choose list type:", reply_markup=list_keyboard())
        return ConversationHandler.END

    if text == "📦 Bulk Add" and uid in ADMIN_IDS:
        kb = [["Manual", "🤖 AI"], ["🏠 Cancel"]]
        await update.message.reply_text("Choose bulk add type:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return 10

    if text == "📋 List" and uid in ADMIN_IDS:
        await update.message.reply_text("Choose list type:", reply_markup=list_keyboard())
        return ConversationHandler.END

    if text == "📣 Broadcast" and uid in ADMIN_IDS:
        await update.message.reply_text("Send message to broadcast:")
        return 9

    if text == "🗑 Clear Words" and uid in ADMIN_IDS:
        with db() as c:
            c.execute("DELETE FROM words")
        await update.message.reply_text("All words cleared.", reply_markup=main_keyboard_bottom(True))
        return ConversationHandler.END

    await update.message.reply_text("Unknown action.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
    return ConversationHandler.END

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "close_list":
        await q.message.delete()
        return ConversationHandler.END

    # Pagination for user words list
    if d.startswith("my_words"):
        page = int(d.split("_")[2]) if len(d.split("_")) > 2 else 0
        with db() as c:
            words = c.execute("SELECT pw.*, u.username FROM personal_words pw LEFT JOIN users u ON pw.user_id=u.user_id ORDER BY id").fetchall()
        if not words:
            await q.message.edit_text("No personal words found.")
            return ConversationHandler.END

        page_size = 10
        total_pages = (len(words) + page_size - 1) // page_size
        start = page * page_size
        end = start + page_size
        page_words = words[start:end]

        text = ""
        for row in page_words:
            text += (
                f"*Word:* {row['word']}\n"
                f"*Level:* {row['level']}\n"
                f"*Definition:* {row['definition']}\n"
                f"*Example:* {row['example']}\n"
                f"*Pronunciation:* {row['pronunciation']}\n"
                f"*Added by:* @{row['username']}\n\n"
            )
        await q.message.edit_text(text.strip(), parse_mode="Markdown", reply_markup=paginate_keyboard(page, total_pages, "my_words"))
        return ConversationHandler.END

    return ConversationHandler.END

# ================= ADD WORD HANDLER =================
async def add_word_choice_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id

    if text == "🏠 Cancel":
        context.user_data.clear()
        await update.message.reply_text("Main Menu:", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
        return ConversationHandler.END
    elif text == "Manual":
        await update.message.reply_text("Send topic first:")
        return 0  # Manual add states
    elif text == "🤖 AI":
        await update.message.reply_text("Send the word to generate via AI:")
        return 7
    else:
        await update.message.reply_text("Unknown option. Cancel to return.")
        return 6

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
    uid = update.effective_user.id

    if not d:
        await update.message.reply_text("No word data found, returning to menu.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
        return ConversationHandler.END

    if uid in ADMIN_IDS:
        with db() as c:
            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (d["topic"], d["word"], d["definition"], d["example"], pron, d["level"], "Manual")
            )
    else:
        with db() as c:
            c.execute(
                "INSERT INTO personal_words (user_id, topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?,?)",
                (uid, d["topic"], d["word"], d["definition"], d["example"], pron, d["level"], "Manual")
            )

    await update.message.reply_text("Word saved.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
    context.user_data.clear()
    return ConversationHandler.END

# ================= AI ADD =================
async def ai_add(update, context):
    word = update.message.text.strip()
    uid = update.effective_user.id
    added_count = 0
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

    if uid in ADMIN_IDS:
        with db() as c:
            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (topic_val, word_val, definition_val, example_val, pronunciation_val, level_val, source_val)
            )
            added_count += 1
    else:
        with db() as c:
            c.execute(
                "INSERT INTO personal_words (user_id, topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?,?)",
                (uid, topic_val, word_val, definition_val, example_val, pronunciation_val, level_val, source_val)
            )
            added_count += 1

    await update.message.reply_text(f"AI word added successfully. Total added: {added_count}", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
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
            6: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_choice_handler)],
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add)],
            8: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_pron)],
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast)],
            10: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: bulk_add_ai(u,c) if u.message.text=="🤖 AI" else bulk_add_manual(u,c) if u.message.text=="Manual" else ConversationHandler.END)],
        },
        fallbacks=[]
    )
    
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
