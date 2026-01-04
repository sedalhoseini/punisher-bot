import os
import re
import sqlite3
import json
from datetime import datetime, time
import pytz
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
import requests
from bs4 import BeautifulSoup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# ================= VERSION INFO =================
BOT_VERSION = "0.4.0"
VERSION_DATE = "2026-01-05"
CHANGELOG = """
• Restored 5 Source options
• Fixed Level tags (CEFR only)
• Duplicate detection (prevents double adds)
• Search now shows Full Cards or "Add Word" option
• "Analyzing" messages auto-delete
• Added Report/Feedback feature
"""

# ================= STATES =================
(
    MANUAL_ADD_TOPIC, MANUAL_ADD_LEVEL, MANUAL_ADD_WORD, 
    MANUAL_ADD_DEF, MANUAL_ADD_EX, MANUAL_ADD_PRON, 
    ADD_CHOICE, AI_ADD_INPUT, 
    BROADCAST_MSG, 
    BULK_CHOICE, BULK_MANUAL, BULK_AI,
    LIST_CHOICE,
    DAILY_COUNT, DAILY_TIME, DAILY_LEVEL, DAILY_POS,
    SEARCH_CHOICE, SEARCH_QUERY,
    SETTINGS_CHOICE, SETTINGS_PRIORITY,
    REPORT_MSG  # <--- NEW STATE
) = range(22)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = {527164608}
DB_PATH = "daily_words.db"

client = Groq(api_key=GROQ_API_KEY)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

# Restored 5 Sources
DEFAULT_SOURCES = ["Cambridge", "Merriam-Webster", "Oxford", "Collins", "Longman"]

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("DROP TABLE IF EXISTS personal_words")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            daily_enabled INTEGER DEFAULT 0,
            daily_count INTEGER,
            daily_time TEXT,
            daily_level TEXT,
            daily_pos TEXT,
            source_prefs TEXT
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
        CREATE TABLE IF NOT EXISTS sent_words (
            user_id INTEGER,
            word_id INTEGER,
            PRIMARY KEY (user_id, word_id)
        );
        """)
        try: c.execute("SELECT source_prefs FROM users LIMIT 1")
        except: c.execute("ALTER TABLE users ADD COLUMN source_prefs TEXT")

# ================= LEVEL NORMALIZER =================
def normalize_level(text):
    """Converts strange levels like 'Beginner' to 'A1'."""
    if not text: return "Unknown"
    text = text.lower().strip()
    
    # Direct Matches
    if "a1" in text: return "A1"
    if "a2" in text: return "A2"
    if "b1" in text: return "B1"
    if "b2" in text: return "B2"
    if "c1" in text: return "C1"
    if "c2" in text: return "C2"
    
    # Keyword Matches
    if "beginner" in text or "basic" in text: return "A1"
    if "elementary" in text: return "A2"
    if "intermediate" in text and "upper" not in text: return "B1"
    if "upper-intermediate" in text or "upper intermediate" in text: return "B2"
    if "advanced" in text: return "C1"
    if "proficiency" in text: return "C2"
    
    return "Unknown" # fallback

# ================= SCRAPERS =================
def empty_word_data(word):
    return {"word": word, "parts": "Unknown", "level": "Unknown", "definition": None, "example": None, "pronunciation": None, "source": None}

def scrape_cambridge(word):
    # (Same as before)
    url = f"https://dictionary.cambridge.org/dictionary/english/{word}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200: return []
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    try:
        data = empty_word_data(word)
        data["source"] = "Cambridge"
        pos = soup.select_one(".pos.dpos")
        if pos: data["parts"] = pos.text.strip()
        level = soup.select_one(".epp-xref")
        if level: data["level"] = normalize_level(level.text.strip()) # NORMALIZED
        definition = soup.select_one(".def.ddef_d")
        if definition: data["definition"] = definition.text.strip()
        example = soup.select_one(".examp.dexamp")
        if example: data["example"] = example.text.strip()
        pron = soup.select_one(".ipa")
        if pron: data["pronunciation"] = pron.text.strip()
        if data["definition"]: results.append(data)
    except: pass
    return results

def scrape_webster(word):
    url = f"https://www.merriam-webster.com/dictionary/{word}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200: return []
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    try:
        data = empty_word_data(word)
        data["source"] = "Merriam-Webster"
        pos = soup.select_one(".important-blue-link")
        if pos: data["parts"] = pos.text.strip()
        
        # Webster doesn't usually show CEFR, so we default to Unknown or use AI later
        data["level"] = "Unknown" 

        definition = soup.select_one(".sense.has-sn")
        if definition: data["definition"] = definition.text.strip()
        example = soup.select_one(".ex-sent")
        if example: data["example"] = example.text.strip()
        pron = soup.select_one(".pr")
        if pron: data["pronunciation"] = pron.text.strip()
        if data["definition"]: results.append(data)
    except: pass
    return results

# Placeholders for others
def scrape_oxford(word): return []
def scrape_collins(word): return []
def scrape_longman(word): return []

SCRAPER_MAP = {
    "Cambridge": scrape_cambridge, 
    "Merriam-Webster": scrape_webster,
    "Oxford": scrape_oxford,
    "Collins": scrape_collins,
    "Longman": scrape_longman
}

def get_words_from_web(word, user_id):
    with db() as c: row = c.execute("SELECT source_prefs FROM users WHERE user_id=?", (user_id,)).fetchone()
    pref_list = json.loads(row["source_prefs"]) if row and row["source_prefs"] else DEFAULT_SOURCES
    for source_name in pref_list:
        scraper = SCRAPER_MAP.get(source_name)
        if scraper:
            results = scraper(word)
            if results: return results
    return []

# ================= AI =================
def ai_generate_full_words_list(word: str):
    prompt = f"""
    Analyze: "{word}".
    If it has multiple POS (noun vs verb), split them.
    STRICT FORMAT:
    Item 1
    Word: {word}
    POS: [Noun/Verb]
    Level: [A1-C2]
    Def: [Short definition]
    Ex: [Short example]
    Pron: [IPA]
    ---
    """
    r = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt}], temperature=0.3)
    return r.choices[0].message.content.strip()

def parse_ai_response(text, original_word):
    items = []
    current = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("Item"):
            if current and "definition" in current: items.append(current)
            current = {"word": original_word, "source": "AI-Enhanced"}
            continue
        if line.startswith("POS:"): current["parts"] = line.replace("POS:", "").strip()
        elif line.startswith("Level:"): current["level"] = normalize_level(line.replace("Level:", "").strip()) # NORMALIZED
        elif line.startswith("Def:"): current["definition"] = line.replace("Def:", "").strip()
        elif line.startswith("Ex:"): current["example"] = line.replace("Ex:", "").strip()
        elif line.startswith("Pron:"): current["pronunciation"] = line.replace("Pron:", "").strip()
    if current and "definition" in current: items.append(current)
    return items

def ai_fill_missing(data_list):
    if not data_list: return []
    filled_list = []
    for data in data_list:
        # Check levels while we are here
        data["level"] = normalize_level(data.get("level"))
        
        missing = [k for k, v in data.items() if v is None or v == "Unknown"]
        if not missing:
            filled_list.append(data)
            continue
            
        prompt = f"Fill missing (Def, Ex, Pron, Level[A1-C2], Pos). key:value.\nWord: {data['word']}\nData: {data}"
        try:
            r = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt}], temperature=0.2)
            for line in r.choices[0].message.content.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    key_map = {"def": "definition", "ex": "example", "pron": "pronunciation", "level": "level", "pos": "parts"}
                    for mk, real_k in key_map.items():
                        if mk in k and (data.get(real_k) is None or data.get(real_k) == "Unknown"):
                            val = v.strip()
                            if real_k == "level": val = normalize_level(val)
                            data[real_k] = val
        except: pass
        filled_list.append(data)
    return filled_list

# ================= KEYBOARDS =================
def main_keyboard_bottom(is_admin=False):
    kb = [["🎯 Get Word", "➕ Add Word"], ["📚 List Words", "⏰ Daily Words"], ["🔍 Search", "⚙️ Settings", "🐞 Report"]]
    if is_admin: kb.append(["📦 Bulk Add", "📣 Broadcast"]); kb.append(["🗑 Clear Words", "🛡 Backup"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def add_word_choice_keyboard(): return ReplyKeyboardMarkup([["Manual", "🤖 AI"], ["🏠 Cancel"]], resize_keyboard=True)
def settings_keyboard(): return ReplyKeyboardMarkup([["🔄 Source Priority", "🏠 Cancel"]], resize_keyboard=True)
def priority_keyboard(): return ReplyKeyboardMarkup([["🏠 Cancel"]], resize_keyboard=True)

# ================= HANDLERS =================
async def common_cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("🏠 Main Menu", reply_markup=main_keyboard_bottom(update.effective_user.id in ADMIN_IDS))
    return ConversationHandler.END

async def save_word_list_to_db(word_list, topic="General"):
    count = 0
    duplicates = 0
    with db() as c:
        for w in word_list:
            if not w.get("definition"): continue
            parts = w.get("parts", "")
            title = w["word"]
            
            # Smart Title Formatting
            if parts and parts.lower() != "unknown" and "(" not in title:
                title = f"{title} ({parts})"

            # 🛑 DUPLICATE CHECK 🛑
            exists = c.execute("SELECT id FROM words WHERE lower(word) = ?", (title.lower(),)).fetchone()
            if exists:
                duplicates += 1
                continue # Skip this word

            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (topic, title, w.get("definition", ""), w.get("example", ""), w.get("pronunciation", ""), w.get("level", "Unknown"), w.get("source", "Manual"))
            )
            count += 1
    return count, duplicates

async def version_command(update, context):
    await update.message.reply_text(f"🤖 *Lingo Bot v{BOT_VERSION}*\n📅 _Updated: {VERSION_DATE}_\n\n📝 *What's New:*\n{CHANGELOG}", parse_mode="Markdown")

async def start(update, context):
    uid = update.effective_user.id
    with db() as c: c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    await update.message.reply_text("👋 *Welcome to Lingo Bot!*", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS), parse_mode="Markdown")
    return ConversationHandler.END

async def main_menu_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS

    if text == "🎯 Get Word":
        # We use pick_word_for_user so it checks sent_words table (No Repeats)
        word = pick_word_for_user(uid)
        if not word:
            await update.message.reply_text("🎉 You have seen all available words! (Resetting cycle...)")
            # Optional: You could auto-clear sent_words here if you want an endless loop
        else:
            await send_word(update.message, word)
        return ConversationHandler.END
    if text == "➕ Add Word":
        await update.message.reply_text("Add Method:", reply_markup=add_word_choice_keyboard())
        return ADD_CHOICE
    if text == "⏰ Daily Words":
        with db() as c: u = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        status_msg = "❌ *Disabled*"
        kb_opts = [["🏠 Cancel"]]
        if u and u["daily_enabled"]: 
            status_msg = f"✅ *Active*\n📅 {u['daily_count']} words at {u['daily_time']}"
            kb_opts = [["🔕 Deactivate"], ["🏠 Cancel"]] # Add Deactivate button
        await update.message.reply_text(f"{status_msg}\n\nTo change, enter count (1-50):", reply_markup=ReplyKeyboardMarkup(kb_opts, resize_keyboard=True), parse_mode="Markdown")
        return DAILY_COUNT
    if text == "📚 List Words":
        with db() as c: rows = c.execute("SELECT topic, level, word FROM words ORDER BY topic, level LIMIT 50").fetchall()
        msg = "\n".join(f"{r['topic']} | {r['level']} | {r['word']}" for r in rows) if rows else "Empty."
        await update.message.reply_text(f"📚 *Words:*\n{msg}", parse_mode="Markdown")
        return ConversationHandler.END
    if text == "🔍 Search":
        await update.message.reply_text("Search by?", reply_markup=ReplyKeyboardMarkup([["By Word", "By Level"], ["By Topic", "🏠 Cancel"]], resize_keyboard=True))
        return SEARCH_CHOICE
    if text == "⚙️ Settings":
        await update.message.reply_text("Settings:", reply_markup=settings_keyboard())
        return SETTINGS_CHOICE
    if text == "🐞 Report":
        await update.message.reply_text("Please type your message or bug report for the admin:", reply_markup=ReplyKeyboardMarkup([["🏠 Cancel"]], resize_keyboard=True))
        return REPORT_MSG

    if is_admin:
        if text == "📦 Bulk Add": await update.message.reply_text("Bulk Type:", reply_markup=add_word_choice_keyboard()); return BULK_CHOICE
        if text == "📣 Broadcast": await update.message.reply_text("Enter message:"); return BROADCAST_MSG
        if text == "🗑 Clear Words": 
            with db() as c: c.execute("DELETE FROM words")
            await update.message.reply_text("Cleared.")
        if text == "🛡 Backup": await auto_backup(context)

    await update.message.reply_text("Main Menu:", reply_markup=main_keyboard_bottom(is_admin))
    return ConversationHandler.END

# --- Search ---
async def search_choice(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    context.user_data["search_type"] = text
    
    # 9. Smart Keyboards for Search
    if text == "By Level":
        await update.message.reply_text("Choose Level:", reply_markup=ReplyKeyboardMarkup([["A1", "A2"], ["B1", "B2"], ["C1", "C2"], ["🏠 Cancel"]], resize_keyboard=True))
    elif text == "By Topic":
        with db() as c: rows = c.execute("SELECT DISTINCT topic FROM words LIMIT 6").fetchall()
        topics = [r["topic"] for r in rows] if rows else ["General"]
        # Create grid
        kb = [topics[i:i + 2] for i in range(0, len(topics), 2)]
        kb.append(["🏠 Cancel"])
        await update.message.reply_text("Choose Topic:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    else:
        # By Word
        await update.message.reply_text("Enter word:", reply_markup=ReplyKeyboardMarkup([["🏠 Cancel"]], resize_keyboard=True))
        
    return SEARCH_QUERY

async def search_perform(update, context):
    query = update.message.text.strip()
    stype = context.user_data.get("search_type")
    
    if query == "🏠 Cancel": return await common_cancel(update, context)

    sql = ""
    if stype == "By Word": 
        sql = "SELECT * FROM words WHERE word LIKE ?"
        # Try strict match first for "By Word" to show Full Card
        with db() as c: rows = c.execute(sql, (f"%{query}%",)).fetchall()
        
        if not rows:
            # 4. Not Found -> Add Option
            context.user_data["add_preload"] = query
            await update.message.reply_text(
                f"❌ '{query}' not found.\nDo you want to add it?",
                reply_markup=ReplyKeyboardMarkup([["Yes, AI Add"], ["Yes, Manual Add"], ["🏠 Cancel"]], resize_keyboard=True)
            )
            return SEARCH_QUERY # Reuse state to catch Yes/No
            
        # 7. Same Format as Get Word
        for row in rows:
            await send_word(update.message, row)
        return await common_cancel(update, context)

    # By Level / Topic -> Show List
    elif stype == "By Level": sql = "SELECT * FROM words WHERE level LIKE ?"
    elif stype == "By Topic": sql = "SELECT * FROM words WHERE topic LIKE ?"
    
    with db() as c: rows = c.execute(sql, (f"%{query}%",)).fetchall()
    
    if rows:
        msg = "\n".join(f"{r['word']} ({r['level']})" for r in rows[:40])
        await update.message.reply_text(f"🔍 *Results:*\n{msg}", parse_mode="Markdown")
    else:
        await update.message.reply_text("No results.")
        
    return await common_cancel(update, context)

async def search_add_redirect(update, context):
    text = update.message.text
    word = context.user_data.get("add_preload")
    
    if text == "Yes, AI Add":
        await update.message.reply_text(f"🤖 AI is processing '{word}'...")
        # Manually set the text so the AI function sees it
        update.message.text = word 
        # Call the AI process directly
        return await ai_add_process(update, context)
        
    elif text == "Yes, Manual Add":
        context.user_data["manual_step"] = 0
        context.user_data["topic"] = "General"
        # Manually set the Topic to "General" so we skip to Level
        context.user_data["topic"] = "General" 
        await update.message.reply_text(f"Adding '{word}'.\nWhat is the **Level**? (A1-C2)")
        return MANUAL_ADD_LEVEL # Skip topic, go straight to Level
        
    else:
        return await common_cancel(update, context)

# --- Settings ---
async def settings_choice(update, context):
    if update.message.text == "🔄 Source Priority":
        msg = (
            "🔢 **Set Source Priority**\n\n"
            "Current Order:\n"
            "1. Cambridge\n2. Merriam-Webster\n3. Oxford\n4. Collins\n5. Longman\n\n"
            "**Send me the order you want using numbers.**\n"
            "Example: `21345` (puts Webster first, then Cambridge...)\n"
            "Example: `51234` (puts Longman first...)"
        )
        await update.message.reply_text(msg, reply_markup=priority_keyboard(), parse_mode="Markdown")
        return SETTINGS_PRIORITY
    return await common_cancel(update, context)

async def set_priority(update, context):
    text = update.message.text.strip()
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    # Validate input (must contain 5 unique numbers from 1-5)
    if not re.fullmatch(r"[1-5]{5}", text) or len(set(text)) != 5:
        await update.message.reply_text("❌ Invalid format. Please send 5 unique numbers (e.g., `12345` or `21345`).")
        return SETTINGS_PRIORITY

    # Map numbers to names
    mapping = {
        "1": "Cambridge",
        "2": "Merriam-Webster",
        "3": "Oxford",
        "4": "Collins",
        "5": "Longman"
    }
    
    new_order = [mapping[char] for char in text]
    
    uid = update.effective_user.id
    with db() as c:
        c.execute("UPDATE users SET source_prefs=? WHERE user_id=?", (json.dumps(new_order), uid))
        
    await update.message.reply_text(f"✅ Priority Saved:\n1. {new_order[0]}\n2. {new_order[1]}...")
    return await common_cancel(update, context)

# --- Report ---
async def report_handler(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    user = update.effective_user
    report_text = f"🐞 *REPORT from {user.first_name} (@{user.username})*:\n\n{text}"
    
    for admin in ADMIN_IDS:
        try: await context.bot.send_message(admin, report_text, parse_mode="Markdown")
        except: pass
        
    await update.message.reply_text("✅ Report sent to admin.")
    return await common_cancel(update, context)

# --- Daily ---
async def daily_count_handler(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    # 8. Deactivate Button Logic
    if text == "🔕 Deactivate":
        uid = update.effective_user.id
        with db() as c: c.execute("UPDATE users SET daily_enabled=0 WHERE user_id=?", (uid,))
        await update.message.reply_text("✅ Daily words deactivated.")
        return await common_cancel(update, context)

    try:
        count = int(text)
        if not (1 <= count <= 50): raise ValueError
        context.user_data["daily_count"] = count
        await update.message.reply_text("Time (HH:MM)?")
        return DAILY_TIME
    except: await update.message.reply_text("Invalid. 1-50:"); return DAILY_COUNT

async def daily_time_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    try:
        datetime.strptime(update.message.text.strip(), "%H:%M")
        context.user_data["daily_time"] = update.message.text.strip()
        await update.message.reply_text("Level?", reply_markup=ReplyKeyboardMarkup([["A1","A2","B1"],["B2","C1"],["Skip"],["🏠 Cancel"]], resize_keyboard=True))
        return DAILY_LEVEL
    except: await update.message.reply_text("Invalid Time (HH:MM)."); return DAILY_TIME

async def daily_level_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    context.user_data["daily_level"] = None if update.message.text == "Skip" else update.message.text
    await update.message.reply_text("POS?", reply_markup=ReplyKeyboardMarkup([["noun","verb"],["adjective"],["Skip"],["🏠 Cancel"]], resize_keyboard=True))
    return DAILY_POS

async def daily_pos_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    context.user_data["daily_pos"] = None if update.message.text == "Skip" else update.message.text
    uid = update.effective_user.id; d = context.user_data
    with db() as c: c.execute("INSERT INTO users (user_id, daily_enabled, daily_count, daily_time, daily_level, daily_pos) VALUES (?, 1, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET daily_enabled=1, daily_count=excluded.daily_count, daily_time=excluded.daily_time, daily_level=excluded.daily_level, daily_pos=excluded.daily_pos", (uid, d["daily_count"], d["daily_time"], d["daily_level"], d["daily_pos"]))
    await update.message.reply_text("✅ Daily Words Updated!")
    return await common_cancel(update, context)

# --- Add Word ---
async def add_choice(update, context):
    text = update.message.text
    if text == "🤖 AI": await update.message.reply_text("Word?"); return AI_ADD_INPUT
    if text == "Manual": await update.message.reply_text("Topic?"); return MANUAL_ADD_TOPIC
    return await common_cancel(update, context)

async def ai_add_process(update, context):
    word = update.message.text.strip()
    
    # 6. Auto-delete "Analyzing"
    status_msg = await update.message.reply_text("🔍 Analyzing sources & AI...")
    
    scraped = get_words_from_web(word, update.effective_user.id)
    if not scraped:
        ai_text = ai_generate_full_words_list(word)
        scraped = parse_ai_response(ai_text, word)
    else: scraped = ai_fill_missing(scraped)
    
    # 3. Duplicate check inside save
    count, dups = await save_word_list_to_db(scraped)
    
    # Cleanup
    try: await status_msg.delete()
    except: pass
    
    msg = f"✅ Saved {count} entries."
    if dups > 0: msg += f"\n⚠️ Skipped {dups} duplicates."
    
    await update.message.reply_text(msg)
    return await common_cancel(update, context)

async def manual_add_steps(update, context):
    text = update.message.text
    # FIX: Check for cancel BEFORE processing input
    if text == "🏠 Cancel":
        return await common_cancel(update, context)

    current = context.user_data.get("manual_step", 0)
    keys = ["topic", "level", "word", "definition", "example", "pronunciation"]
    
    # Save input
    context.user_data[keys[current]] = text
    
    # Move to next step
    if current < 5:
        next_prompt = ["Level?", "Word?", "Definition?", "Example?", "Pronunciation?"][current]
        await update.message.reply_text(next_prompt)
        context.user_data["manual_step"] = current + 1
        # We must return the specific state for the next step
        return MANUAL_ADD_TOPIC + current + 1
    
    # Final Step: Save
    count, dups = await save_word_list_to_db([context.user_data], topic=context.user_data["topic"])
    msg = "✅ Saved." if count > 0 else "⚠️ Duplicate skipped."
    await update.message.reply_text(msg)
    return await common_cancel(update, context)

# --- Bulk & Broadcast ---
async def bulk_choice(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    if text == "Manual": await update.message.reply_text("Send lines: topic|level|word|def|ex|pron"); return BULK_MANUAL
    if text == "🤖 AI": await update.message.reply_text("Send words (one per line):"); return BULK_AI
    return BULK_CHOICE

async def bulk_manual(update, context):
    lines = update.message.text.splitlines(); count = 0
    with db() as c:
        for l in lines:
            p = [x.strip() for x in l.split("|")]
            if len(p) == 6:
                c.execute("INSERT INTO words (topic, level, word, definition, example, pronunciation, source) VALUES (?,?,?,?,?,?,?)", (*p, "Bulk")); count += 1
    await update.message.reply_text(f"Bulk added {count} words.")
    return await common_cancel(update, context)

async def bulk_ai(update, context):
    words = [w.strip() for w in update.message.text.splitlines() if w.strip()]
    status = await update.message.reply_text(f"Processing {len(words)} words...")
    total = 0; uid = update.effective_user.id
    for word in words:
        scraped = get_words_from_web(word, uid)
        scraped = ai_fill_missing(scraped) if scraped else parse_ai_response(ai_generate_full_words_list(word), word)
        c, _ = await save_word_list_to_db(scraped)
        total += c
    
    try: await status.delete()
    except: pass
    await update.message.reply_text(f"Bulk AI finished. Added {total} entries.")
    return await common_cancel(update, context)

async def broadcast_handler(update, context):
    msg = update.message.text
    with db() as c: users = c.execute("SELECT user_id FROM users").fetchall()
    count = 0
    for u in users:
        try: await context.bot.send_message(u["user_id"], msg); count += 1
        except: pass
    await update.message.reply_text(f"Sent to {count} users.")
    return await common_cancel(update, context)

# --- System ---
# [REPLACE THE OLD send_word FUNCTION WITH THIS]
async def send_word(chat, row):
    if not row:
        await chat.reply_text("No word found.")
        return
    text = (
        f"📖 *{row['word']}*\n"
        f"🏷 {row['level']} | {row['topic']}\n"
        f"💡 {row['definition']}\n"
        f"📝 _Ex: {row['example']}_\n"
        f"🗣 {row['pronunciation']}\n"
        f"📚 _Source: {row['source']}_"
    )
    await chat.reply_text(text, parse_mode="Markdown")

async def auto_backup(context):
    now = datetime.now()
    filename = f"backup_{now.strftime('%Y-%m-%d_%H-%M')}.db"
    for admin_id in ADMIN_IDS:
        try:
            with open(DB_PATH, 'rb') as f: await context.bot.send_document(admin_id, f, filename=filename, caption=f"Backup {now.strftime('%H:%M')}")
        except: pass

async def send_daily_scheduler(context):
    tehran = pytz.timezone("Asia/Tehran")
    now_str = datetime.now(tehran).strftime("%H:%M")
    with db() as c: users = c.execute("SELECT * FROM users WHERE daily_enabled=1 AND daily_time=?", (now_str,)).fetchall()
    for u in users:
        for _ in range(u["daily_count"]):
            with db() as c: w = c.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1").fetchone()
            try: await send_word(context.bot, w)
            except: pass

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    tehran = pytz.timezone("Asia/Tehran")
    app.job_queue.run_daily(auto_backup, time=time(0,0,0, tzinfo=tehran))
    app.job_queue.run_repeating(send_daily_scheduler, interval=60, first=10)

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("version", version_command),
            CommandHandler("backup", auto_backup),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
        ],
        states={
            ADD_CHOICE: [MessageHandler(filters.TEXT, add_choice)],
            AI_ADD_INPUT: [MessageHandler(filters.TEXT, ai_add_process)],
            
            MANUAL_ADD_TOPIC: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_LEVEL: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_WORD: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_DEF: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_EX: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_PRON: [MessageHandler(filters.TEXT, manual_add_steps)],

            DAILY_COUNT: [MessageHandler(filters.TEXT, daily_count_handler)],
            DAILY_TIME: [MessageHandler(filters.TEXT, daily_time_handler)],
            DAILY_LEVEL: [MessageHandler(filters.TEXT, daily_level_handler)],
            DAILY_POS: [MessageHandler(filters.TEXT, daily_pos_handler)],

            SEARCH_CHOICE: [MessageHandler(filters.TEXT, search_choice)],
            
            # Special handler for the search loop (Add/Query)
            SEARCH_QUERY: [MessageHandler(filters.Regex("^(Yes, AI Add|Yes, Manual Add)$"), search_add_redirect), MessageHandler(filters.TEXT, search_perform)],

            SETTINGS_CHOICE: [MessageHandler(filters.TEXT, settings_choice)],
            SETTINGS_PRIORITY: [MessageHandler(filters.TEXT, set_priority)],
            REPORT_MSG: [MessageHandler(filters.TEXT, report_handler)],
            
            BULK_CHOICE: [MessageHandler(filters.TEXT, bulk_choice)],
            BULK_MANUAL: [MessageHandler(filters.TEXT, bulk_manual)],
            BULK_AI: [MessageHandler(filters.TEXT, bulk_ai)],
            BROADCAST_MSG: [MessageHandler(filters.TEXT, broadcast_handler)],
        },
        fallbacks=[CommandHandler("cancel", common_cancel), MessageHandler(filters.Regex("^🏠 Cancel$"), common_cancel)]
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()

