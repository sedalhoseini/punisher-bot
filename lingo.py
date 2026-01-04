import os
import re
import sqlite3
from datetime import datetime, time
import pytz
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup
import requests
from bs4 import BeautifulSoup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# ================= VERSION INFO =================
BOT_VERSION = "0.1.0"
VERSION_DATE = "2026-01-04"
CHANGELOG = """
• Initial Beta Release for Students
• Added Daily Words & AI Dictionary
"""
# ================= DAILY STATES =================
DAILY_COUNT = 31
DAILY_TIME = 32
DAILY_LEVEL = 33
DAILY_POS = 34

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = {527164608}
DB_PATH = "daily_words.db"

client = Groq(api_key=GROQ_API_KEY)
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ================= FALLBACK / CANCEL =================
async def cancel(update, context):
    context.user_data.clear()
    uid = update.effective_user.id
    await update.message.reply_text(
        "Operation cancelled.",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

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
            username TEXT,
            daily_enabled INTEGER DEFAULT 0,
            daily_count INTEGER,
            daily_time TEXT,
            daily_level TEXT,
            daily_pos TEXT
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

# ============= Above AI =============
def empty_word_data(word):
    return {
        "word": word,
        "parts": None,
        "level": None,
        "definition": None,
        "example": None,
        "pronunciation": None,
        "source": None,
    }


def scrape_cambridge(word):
    url = f"https://dictionary.cambridge.org/dictionary/english/{word}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    try:
        data = empty_word_data(word)

        pos = soup.select_one(".pos.dpos")
        if pos:
            data["parts"] = pos.text.strip()

        level = soup.select_one(".epp-xref")
        if level:
            data["level"] = level.text.strip()

        definition = soup.select_one(".def.ddef_d")
        if definition:
            data["definition"] = definition.text.strip()

        example = soup.select_one(".examp.dexamp")
        if example:
            data["example"] = example.text.strip()

        pron = soup.select_one(".ipa")
        if pron:
            data["pronunciation"] = pron.text.strip()

        data["source"] = "Cambridge"
        return data

    except:
        return None


def scrape_webster(word):
    url = f"https://www.merriam-webster.com/dictionary/{word}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    try:
        data = empty_word_data(word)

        pos = soup.select_one(".important-blue-link")
        if pos:
            data["parts"] = pos.text.strip()

        definition = soup.select_one(".sense.has-sn")
        if definition:
            data["definition"] = definition.text.strip()

        example = soup.select_one(".ex-sent")
        if example:
            data["example"] = example.text.strip()

        pron = soup.select_one(".pr")
        if pron:
            data["pronunciation"] = pron.text.strip()

        data["source"] = "Merriam-Webster"
        return data

    except:
        return None


def scrape_oxford(word):
    return None


def scrape_collins(word):
    return None


def scrape_longman(word):
    return None


SCRAPERS = [
    scrape_cambridge,
    scrape_oxford,
    scrape_webster,
    scrape_collins,
    scrape_longman,
]


def get_word_from_web(word):
    for scraper in SCRAPERS:
        data = scraper(word)
        if data and any(data.values()):
            return data
    return empty_word_data(word)

# ================= AI =================
def ai_generate_full_word(word: str):
    prompt = f"""
You are an English linguist.

Generate full dictionary-style data for the word: "{word}"

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

# ============= AI fill missing =============
def ai_fill_missing(data):
    missing = [k for k, v in data.items() if v is None]

    if not missing:
        return data

    prompt = f"""
Fill ONLY missing fields for this word.
Do not change existing data.

Word: {data['word']}
Current data: {data}

Return only key:value lines.
"""

    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    for line in r.choices[0].message.content.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            if k in data and data[k] is None:
                data[k] = v.strip()

    return data

# ================= KEYBOARDS =================
def main_keyboard_bottom(is_admin=False):
    kb = [
        ["🎯 Get Word", "➕ Add Word"],
        ["📚 List Words", "⏰ Daily Words"]
    ]
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
async def version_command(update, context):
    text = (
        f"🤖 *Lingo Bot v{BOT_VERSION}*\n"
        f"📅 _Last Updated: {VERSION_DATE}_\n\n"
        f"📝 *What's New:*\n{CHANGELOG}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def send_word(chat, row):
    if not row:
        await chat.reply_text("No word found.")
        return
    
    # Check if the word contains brackets like "word (noun)"
    word_text = row['word']
    if '(' in word_text and ')' in word_text:
        part_of_speech = word_text.split('(')[-1].replace(')', '')
        display_word = word_text.split('(')[0].strip()
    else:
        part_of_speech = "Not specified"
        display_word = word_text

    text = (
        f"Word: {display_word}\n"
        f"Part of Speech: {part_of_speech}\n"
        f"Level: {row['level']}\n"
        f"Definition: {row['definition']}\n"
        f"Example: {row['example']}\n"
        f"Pronunciation: {row['pronunciation']}\n"
        f"Source: {row['source']}"
    )
    await chat.reply_text(text, parse_mode="Markdown")

def pick_word_for_user(user_id):
    with db() as c:
        row = c.execute("""
            SELECT w.*
            FROM words w
            LEFT JOIN sent_words s
              ON w.id = s.word_id AND s.user_id = ?
            WHERE s.word_id IS NULL
            ORDER BY RANDOM()
            LIMIT 1
        """, (user_id,)).fetchone()

        if not row:
            # Reset sent words if all words were already sent
            c.execute("DELETE FROM sent_words WHERE user_id=?", (user_id,))
            row = c.execute("""
                SELECT w.*
                FROM words w
                ORDER BY RANDOM()
                LIMIT 1
            """).fetchone()
            if not row:
                return None

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
        context.user_data.clear()
        await update.message.reply_text("How many words per day?")
        return DAILY_COUNT

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

# Step 1 — How many words
async def daily_count_handler(update, context):
    try:
        count = int(update.message.text)
        if count < 1 or count > 50:
            raise ValueError
        context.user_data["daily_count"] = count
    except:
        await update.message.reply_text("Please enter a valid number between 1 and 50.")
        return DAILY_COUNT

    await update.message.reply_text("What time should I send the words? (HH:MM)")
    return DAILY_TIME

# Step 2 — Time
async def daily_time_handler(update, context):
    time_text = update.message.text.strip()
    if not re.match(r"^\d{2}:\d{2}$", time_text):
        await update.message.reply_text("Please enter time in HH:MM format (e.g., 09:30).")
        return DAILY_TIME

    context.user_data["daily_time"] = time_text
    keyboard = ReplyKeyboardMarkup(
        [["A1","A2","B1"],["B2","C1"],["Skip"]],
        resize_keyboard=True
    )
    await update.message.reply_text("Choose level (optional):", reply_markup=keyboard)
    return DAILY_LEVEL

# Step 3 — Level
async def daily_level_handler(update, context):
    level = update.message.text
    if level != "Skip":
        context.user_data["daily_level"] = level
    else:
        context.user_data["daily_level"] = None
    keyboard = ReplyKeyboardMarkup(
        [["noun","verb"],["adjective","adverb"],["Skip"]],
        resize_keyboard=True
    )
    await update.message.reply_text("Choose part of speech (optional):", reply_markup=keyboard)
    return DAILY_POS

# Step 4 — Part of speech + save
async def daily_pos_handler(update, context):
    pos = update.message.text
    if pos != "Skip":
        context.user_data["daily_pos"] = pos
    else:
        context.user_data["daily_pos"] = None

    uid = update.effective_user.id
    daily_count = context.user_data.get("daily_count")
    daily_time = context.user_data.get("daily_time")
    daily_level = context.user_data.get("daily_level")
    daily_pos = context.user_data.get("daily_pos")
    
    with db() as c:
        c.execute("""
            INSERT INTO users (user_id, daily_enabled, daily_count, daily_time, daily_level, daily_pos)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                daily_enabled=excluded.daily_enabled,
                daily_count=excluded.daily_count,
                daily_time=excluded.daily_time,
                daily_level=excluded.daily_level,
                daily_pos=excluded.daily_pos
        """, (uid, 1, daily_count, daily_time, daily_level, daily_pos))


    context.user_data.clear()
    await update.message.reply_text(
        "Daily words activated.",
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
    word = update.message.text.strip()

    # Step 1: Scrape websites first
    data = get_word_from_web(word)

    # Step 2: Fill only missing fields with AI
    data = ai_fill_missing(data)

    # Step 3: Save to DB
    with db() as c:
        if uid in ADMIN_IDS:
            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (
                    "General",
                    f"{data['word']} ({data['parts']})",
                    data["definition"],
                    data["example"],
                    data["pronunciation"],
                    data["level"],
                    data["source"],
                )
            )
        else:
            c.execute(
                "INSERT INTO personal_words (user_id, topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?,?)",
                (
                    uid,
                    "General",
                    f"{data['word']} ({data['parts']})",
                    data["definition"],
                    data["example"],
                    data["pronunciation"],
                    data["level"],
                    data["source"],
                )
            )

    await update.message.reply_text(
        "Word added (Dictionary + AI).",
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
    uid = update.effective_user.id
    words = [w.strip() for w in update.message.text.splitlines() if w.strip()]

    with db() as c:
        for word in words:
            data = get_word_from_web(word)
            data = ai_fill_missing(data)

            if uid in ADMIN_IDS:
                c.execute(
                    "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                    (
                        "General",
                        f"{data['word']} ({data['parts']})",
                        data["definition"],
                        data["example"],
                        data["pronunciation"],
                        data["level"],
                        data["source"],
                    )
                )
            else:
                c.execute(
                    "INSERT INTO personal_words (user_id, topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        uid,
                        "General",
                        f"{data['word']} ({data['parts']})",
                        data["definition"],
                        data["example"],
                        data["pronunciation"],
                        data["level"],
                        data["source"],
                    )
                )

    await update.message.reply_text(
        "Bulk AI add done (Dictionary + AI).",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
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

# ============== Auto Backup ==============
async def auto_backup(context):
    now = datetime.now()
    # 1. Format for Filename (Uses _ which is safe for files)
    ts_file = now.strftime("%Y-%m-%d_%H-%M")
    # 2. Format for Chat Caption (Uses space to avoid crashing Markdown)
    ts_text = now.strftime("%Y-%m-%d %H:%M")
    
    filename = f"backup_auto_{ts_file}.db"

    # Send backup to ALL Admins
    for admin_id in ADMIN_IDS:
        try:
            with open(DB_PATH, 'rb') as f:
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=f,
                    filename=filename,
                    # We use single * for bold in standard Markdown, and ts_text (no underscores)
                    caption=f"🌙 *Nightly Backup*\n📅 {ts_text}\n🛡 System Auto-Save",
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"❌ Auto-backup failed for {admin_id}: {e}")

# ================= MANUAL BACKUP COMMAND =================
async def backup_command(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return  # Ignore non-admins

    now = datetime.now()
    ts_file = now.strftime("%Y-%m-%d_%H-%M")
    ts_text = now.strftime("%Y-%m-%d %H:%M")
    
    filename = f"backup_manual_{ts_file}.db"

    try:
        with open(DB_PATH, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=f"📦 *Manual Backup*\n📅 {ts_text}\n🛡 Safe and sound!",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Backup failed: {e}")

# ============== Daily Words ==============
async def send_daily_words(context):
    tehran = pytz.timezone("Asia/Tehran")
    now = datetime.now(tehran).strftime("%H:%M")

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

            # Safer formatting for daily words
            word_text = word['word']
            if '(' in word_text and ')' in word_text:
                display_word = word_text.split('(')[0].strip()
            else:
                display_word = word_text

            text = (
                f"*{display_word}*\n"
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

    # Define your timezone (Tehran is what you used before)
    tehran_tz = pytz.timezone("Asia/Tehran")
    
    # Set time to 00:00 (Midnight)
    midnight_time = time(hour=0, minute=0, second=0, tzinfo=tehran_tz)

    # Schedule the job
    app.job_queue.run_daily(auto_backup, time=midnight_time)
    
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("version", version_command),
            CommandHandler("backup", backup_command),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
        ],
        states={
            # MANUAL ADD (step 0-5)
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            4: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            5: [MessageHandler(filters.ALL, save_pron)],
    
            # ADD WORD CHOICE (manual / AI)
            6: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_choice_handler)],
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add)],
    
            # BROADCAST (admin)
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast)],
    
            # BULK ADD
            10: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_choice)],
            11: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_manual)],
            12: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_ai)],
    
            # LIST WORDS
            20: [MessageHandler(filters.TEXT & ~filters.COMMAND, list_handler)],
    
            # DAILY WORDS CONFIG
            DAILY_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_count_handler)],
            DAILY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_time_handler)],
            DAILY_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_level_handler)],
            DAILY_POS: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_pos_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()

