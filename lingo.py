import os
import re
import sqlite3
import json
from datetime import datetime, time
import pytz
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
import requests
from bs4 import BeautifulSoup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# ================= VERSION INFO =================
BOT_VERSION = "0.7.0"
VERSION_DATE = "2026-01-07"
CHANGELOG = """
• Daily Words got updated
"""

# ================= STATES =================
(
    MANUAL_ADD_TOPIC, MANUAL_ADD_LEVEL, MANUAL_ADD_WORD, 
    MANUAL_ADD_DEF, MANUAL_ADD_EX, MANUAL_ADD_PRON, 
    ADD_CHOICE, AI_ADD_INPUT, 
    BROADCAST_MSG, 
    BULK_CHOICE, BULK_MANUAL, BULK_AI,
    LIST_CHOICE, LIST_TOPIC, # <--- Updated
    DAILY_COUNT, DAILY_TIME, DAILY_LEVEL, DAILY_POS, DAILY_TOPIC,
    SEARCH_CHOICE, SEARCH_QUERY,
    SETTINGS_CHOICE, SETTINGS_PRIORITY,
    REPORT_MSG,
    EDIT_CHOOSE, EDIT_VALUE # <--- New for editing
) = range(26)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = {527164608}
DB_PATH = "daily_words.db"

client = Groq(api_key=GROQ_API_KEY)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/"
}

# Replaced Webster with Collins
DEFAULT_SOURCES = ["Cambridge", "Longman", "Collins"]

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
        c.execute("CREATE INDEX IF NOT EXISTS idx_topic ON words (topic)")
        try: c.execute("SELECT source_prefs FROM users LIMIT 1")
        except: c.execute("ALTER TABLE users ADD COLUMN source_prefs TEXT")
        try: c.execute("ALTER TABLE users ADD COLUMN daily_topic TEXT")
        except: pass

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
    url = f"https://dictionary.cambridge.org/dictionary/english/{word}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=4)
        if r.status_code != 200: return []
        
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        
        entries = soup.select(".pr.entry-body__el")
        
        for entry in entries:
            try:
                data = empty_word_data(word)
                data["source"] = "Cambridge"
                
                pos_tag = entry.select_one(".pos.dpos")
                if pos_tag: data["parts"] = pos_tag.text.strip()
                
                level_tag = entry.select_one(".epp-xref")
                if level_tag: data["level"] = normalize_level(level_tag.text.strip())
                
                def_tag = entry.select_one(".def.ddef_d")
                if def_tag: data["definition"] = def_tag.text.strip()
                
                ex_tag = entry.select_one(".examp.dexamp")
                if ex_tag: data["example"] = ex_tag.text.strip()
                
                pron_tag = entry.select_one(".ipa")
                if pron_tag: data["pronunciation"] = pron_tag.text.strip()
                
                if data["definition"]: 
                    results.append(data)
                    # 🛑 LIMIT REMOVED
            except: pass
        return results
    except: return []
    
def scrape_collins(word):
    clean_word = word.strip().replace(" ", "-")
    url = f"https://www.collinsdictionary.com/dictionary/english/{clean_word}"
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=4)
        if r.status_code != 200: return []
        
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        
        entries = soup.select(".dict-entry")
        for entry in entries:
            try:
                data = empty_word_data(word)
                data["source"] = "Collins"
                
                pos_tag = entry.select_one(".pos")
                if pos_tag: data["parts"] = pos_tag.text.strip()
                
                level_tag = entry.select_one(".coa_label")
                if level_tag: data["level"] = normalize_level(level_tag.text.strip())
                
                def_tag = entry.select_one(".def")
                if def_tag: data["definition"] = def_tag.text.strip()
                
                ex_tag = entry.select_one(".quote")
                if ex_tag: data["example"] = ex_tag.text.strip()
                
                pron_tag = entry.select_one(".pron")
                if pron_tag: data["pronunciation"] = pron_tag.text.strip()
                
                if data["definition"]:
                    results.append(data)
                    # 🛑 LIMIT REMOVED
            except: pass
        return results
    except: return []

def scrape_longman(word):
    clean_word = word.strip().replace(" ", "-")
    url = f"https://www.ldoceonline.com/dictionary/{clean_word}"
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=4)
        if r.status_code != 200: return []
        
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        
        entries = soup.select(".ldoceEntry, .Entry")
        
        for entry in entries:
            try:
                data = empty_word_data(word)
                data["source"] = "Longman"
                
                pos_tag = entry.select_one(".POS")
                if pos_tag: data["parts"] = pos_tag.text.strip()
                
                level_tag = entry.select_one(".LEVEL_HEADER, .lozenge, .tooltip")
                if level_tag: data["level"] = normalize_level(level_tag.text.strip())
                
                def_tag = entry.select_one(".DEF")
                if def_tag: data["definition"] = def_tag.text.strip()
                
                ex_tag = entry.select_one(".EXAMPLE")
                if ex_tag: data["example"] = ex_tag.text.strip()
                
                pron_tag = entry.select_one(".PRON")
                if pron_tag: data["pronunciation"] = pron_tag.text.strip()
                
                if data["definition"]:
                    results.append(data)
                    # 🛑 LIMIT REMOVED: Loop continues to find Verb/Noun etc.
            except: pass
        return results
    except: return []
    

SCRAPER_MAP = {
    "Cambridge": scrape_cambridge, 
    "Longman": scrape_longman,
    "Collins": scrape_collins
}

def normalize_pos_key(text):
    """Helper to unify POS names (e.g., 'n' vs 'noun') for comparison."""
    if not text: return "unknown"
    t = text.lower().strip().replace(".", "") # Remove dots
    
    # 1. Adverb (Priority)
    if "adv" in t: return "adverb"
    
    # 2. Verb Variants (The Fix for 'Drunk')
    # Maps 'past participle', 'v', 'verb' all to 'verb'
    if "verb" in t or t == "v" or "participle" in t: return "verb"

    # 3. Adjective Variants
    if "adj" in t: return "adjective"

    # 4. Noun Variants
    if "noun" in t or t == "n": return "noun"
    
    # 5. Others
    if "prep" in t: return "preposition"
    if "conj" in t: return "conjunction"
    if "interj" in t: return "interjection"
    if "pron" in t: return "pronoun"
    
    return t

def get_words_from_web(word, user_id):
    with db() as c: 
        row = c.execute("SELECT source_prefs FROM users WHERE user_id=?", (user_id,)).fetchone()
    
    pref_list = json.loads(row["source_prefs"]) if row and row["source_prefs"] else DEFAULT_SOURCES
    
    combined_results = []
    seen_pos = set()
    
    for source_name in pref_list:
        scraper = SCRAPER_MAP.get(source_name)
        if scraper:
            results = scraper(word)
            
            for item in results:
                raw_pos = item.get("parts", "Unknown")
                
                # 🛠 FIX: If POS is missing but def says "past participle", treat as VERB
                def_lower = item.get("definition", "").lower()
                if raw_pos == "Unknown" and "past participle" in def_lower:
                    raw_pos = "verb"

                pos_key = normalize_pos_key(raw_pos)
                
                if pos_key not in seen_pos:
                    combined_results.append(item)
                    if pos_key != "unknown":
                        seen_pos.add(pos_key)
                        
    return combined_results
    
# ================= AI =================
def ai_generate_full_words_list(word: str):
    prompt = f"""
    Task: Analyze the input "{word}".
    
    STEP 1: VALIDATION
    Is this a real, valid English word? 
    If it is gibberish, random letters (e.g., "asdf"), or a typo that cannot be understood, output STRICTLY: INVALID
    
    STEP 2: DEFINITION (Only if valid)
    If valid, provide the details in this format:
    Item 1
    Word: {word}
    POS: [Noun/Verb]
    Level: [A1-C2]
    Def: [Short definition]
    Ex: [Short example]
    Pron: [IPA]
    ---
    """
    # Lower temperature to 0.1 to make it strict/serious
    r = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt}], temperature=0.1)
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
    
    # 1. SMART PRE-FILL: Check if ANY item has pronunciation/audio
    # If "Big (Adj)" has audio, copy it to "Big (Noun)" so we don't say "None"
    shared_pron = None
    for data in data_list:
        if data.get("pronunciation") and data["pronunciation"] != "Unknown":
            shared_pron = data["pronunciation"]
            break
    
    for data in data_list:
        # Check levels first
        data["level"] = normalize_level(data.get("level"))
        
        # Apply shared pronunciation if missing
        if (not data.get("pronunciation") or data["pronunciation"] == "Unknown") and shared_pron:
            data["pronunciation"] = shared_pron

        # Now check what is still missing
        missing = [k for k, v in data.items() if v is None or v == "Unknown"]
        
        if not missing:
            filled_list.append(data)
            continue
            
        prompt = f"""
        Fill missing fields.
        Crucial: Estimate CEFR Level (A1-C2) if Unknown.
        
        Word: {data['word']}
        Current Data: {data}
        
        Return STRICTLY:
        Level: [Value]
        Def: [Value]
        Ex: [Value]
        Pron: [Value]
        """
        try:
            r = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt}], temperature=0.2)
            for line in r.choices[0].message.content.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if "level" in k and data["level"] == "Unknown": data["level"] = normalize_level(v)
                    if "def" in k and not data["definition"]: data["definition"] = v
                    if "ex" in k and not data["example"]: data["example"] = v
                    if "pron" in k and (not data["pronunciation"] or data["pronunciation"] == "Unknown"): data["pronunciation"] = v
                    if "pos" in k and (not data["parts"] or data["parts"]=="Unknown"): data["parts"] = v
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

            # 🛑 NEW DUPLICATE CHECK 🛑
            # Check ID matching BOTH Word AND Topic
            exists = c.execute(
                "SELECT id FROM words WHERE lower(word) = ? AND topic = ?", 
                (title.lower(), topic)
            ).fetchone()
            
            if exists:
                duplicates += 1
                continue # Skip this word

            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (topic, title, w.get("definition", ""), w.get("example", ""), w.get("pronunciation", ""), w.get("level", "Unknown"), w.get("source", "Manual"))
            )
            count += 1
    return count, duplicates

def pick_word_for_user(user_id):
    with db() as c:
        # 1. Get User Preferences
        u = c.execute("SELECT daily_level, daily_pos, daily_topic FROM users WHERE user_id=?", (user_id,)).fetchone()
        
        # 2. Build Query
        query = """
            SELECT w.* FROM words w
            LEFT JOIN sent_words s ON w.id = s.word_id AND s.user_id = ?
            WHERE s.word_id IS NULL
        """
        params = [user_id]

        # FILTER: LEVEL (Multi-Select Support)
        if u and u["daily_level"] and u["daily_level"] != "Any":
            levels = u["daily_level"].split(",") # Split "A1,A2" into ['A1', 'A2']
            placeholders = ",".join("?" * len(levels))
            query += f" AND w.level IN ({placeholders})"
            params.extend(levels)

        # FILTER: POS (Multi-Select Support)
        if u and u["daily_pos"] and u["daily_pos"] != "Any":
            pos_list = u["daily_pos"].split(",")
            # POS logic is trickier because of "verb" vs "verbs". We use LIKE OR logic.
            # (w.word LIKE '%(noun)%' OR w.word LIKE '%(verb)%')
            or_clauses = []
            for p in pos_list:
                or_clauses.append("lower(w.word) LIKE ?")
                params.append(f"%({p})%")
            
            if or_clauses:
                query += f" AND ({' OR '.join(or_clauses)})"

        # FILTER: TOPIC (Multi-Select Support)
        if u and u["daily_topic"] and u["daily_topic"] != "🌍 All Sources" and u["daily_topic"] != "Any":
            topics = u["daily_topic"].split(",")
            placeholders = ",".join("?" * len(topics))
            query += f" AND w.topic IN ({placeholders})"
            params.extend(topics)

        query += " ORDER BY RANDOM() LIMIT 1"

        # 3. Execute & Reset Logic
        row = c.execute(query, params).fetchone()
        if not row:
            # Reset sent words if all words were already sent
            c.execute("DELETE FROM sent_words WHERE user_id=?", (user_id,))
            row = c.execute(query, params).fetchone()
            if not row: return None

        c.execute("INSERT OR IGNORE INTO sent_words (user_id, word_id) VALUES (?,?)", (user_id, row["id"]))
        return row

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
    context.user_data["is_admin_flag"] = is_admin

    if text == "🎯 Get Word":
        # We use pick_word_for_user so it checks sent_words table (No Repeats)
        word = pick_word_for_user(uid)
        if not word:
            await update.message.reply_text("🎉 You have seen all available words! (Resetting cycle...)")
            # Optional: You could auto-clear sent_words here if you want an endless loop
        else:
            await send_word(update.message, word, is_admin)
        return ConversationHandler.END
    if text == "➕ Add Word":
        await update.message.reply_text("Add Method:", reply_markup=add_word_choice_keyboard())
        return ADD_CHOICE
    if text == "⏰ Daily Words":
        with db() as c: u = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        status_msg = "❌ *Disabled*"
        kb_opts = [["🏠 Cancel"]]
        
        if u and u["daily_enabled"]: 
            # Get topic, default to "All Sources" if None
            topic_display = u['daily_topic'] if u['daily_topic'] else "🌍 All Sources"
            
            status_msg = (
                f"✅ *Active*\n"
                f"📅 {u['daily_count']} words at {u['daily_time']}\n"
                f"📚 Book: {topic_display}"
            )
            kb_opts = [["🔕 Deactivate"], ["🏠 Cancel"]]

        await update.message.reply_text(
            f"{status_msg}\n\nTo change, enter count (1-50):", 
            reply_markup=ReplyKeyboardMarkup(kb_opts, resize_keyboard=True), 
            parse_mode="Markdown"
        )
        return DAILY_COUNT
    if text == "📚 List Words":
        # 1. Fetch Topics
        with db() as c: rows = c.execute("SELECT DISTINCT topic FROM words").fetchall()
        topics = [r["topic"] for r in rows] if rows else ["General"]
        
        # 2. Add "All" option
        buttons = [["🌍 All Words"]] + [topics[i:i + 2] for i in range(0, len(topics), 2)] + [["🏠 Cancel"]]
        
        await update.message.reply_text("📂 Choose a List to view:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return LIST_CHOICE
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
    
    if text == "By Word":
        # 1. NEW: Fetch available Topics (Books)
        with db() as c: rows = c.execute("SELECT DISTINCT topic FROM words").fetchall()
        topics = [r["topic"] for r in rows] if rows else ["General"]
        
        # 2. Create Dynamic Buttons: [All Sources] + [Book 1] + [Book 2]...
        buttons = [["🌍 All Sources"]] + [topics[i:i + 2] for i in range(0, len(topics), 2)] + [["🏠 Cancel"]]
        
        await update.message.reply_text("📚 Select Search Scope:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
    
    elif text == "By Level":
        await update.message.reply_text("Choose Level:", reply_markup=ReplyKeyboardMarkup([["A1", "A2"], ["B1", "B2"], ["C1", "C2"], ["🏠 Cancel"]], resize_keyboard=True))
    
    elif text == "By Topic":
        with db() as c: rows = c.execute("SELECT DISTINCT topic FROM words LIMIT 6").fetchall()
        topics = [r["topic"] for r in rows] if rows else ["General"]
        kb = [topics[i:i + 2] for i in range(0, len(topics), 2)]
        kb.append(["🏠 Cancel"])
        await update.message.reply_text("Choose Topic:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        
    return SEARCH_QUERY

async def search_perform(update, context):
    text = update.message.text.strip()
    stype = context.user_data.get("search_type")
    
    if text == "🏠 Cancel": return await common_cancel(update, context)
    if not stype:
        await update.message.reply_text("⚠️ Session expired. Please select search type again.")
        return await common_cancel(update, context)

    # --- HANDLE "BY WORD" (2 Steps: Scope -> Query) ---
    if stype == "By Word":
        # Step A: User just picked the Scope (e.g., "504 Words" or "All Sources")
        if "search_scope" not in context.user_data:
            context.user_data["search_scope"] = text
            await update.message.reply_text(f"🔍 Scope: {text}\nNow enter the **Word**:", parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup([["🏠 Cancel"]], resize_keyboard=True))
            return SEARCH_QUERY # Stay in loop to wait for the word
            
        # Step B: User entered the actual Word
        scope = context.user_data["search_scope"]
        
        # Search SQL
        sql = "SELECT * FROM words WHERE (lower(word) = ? OR lower(word) LIKE ?)"
        q_lower = text.lower()
        params = [q_lower, f"{q_lower} (%"]
        
        # Apply Book Filter (unless searching everything)
        if scope != "🌍 All Sources":
            sql += " AND topic = ?"
            params.append(scope)
            
        with db() as c: rows = c.execute(sql, params).fetchall()
        
        if not rows:
            # Not found logic
            if scope in ["🌍 All Sources", "General"]:
                context.user_data["add_preload"] = text
                await update.message.reply_text(
                    f"❌ '{text}' not found in {scope}.\nDo you want to add it?",
                    reply_markup=ReplyKeyboardMarkup([["Yes, AI Add"], ["Yes, Manual Add"], ["🏠 Cancel"]], resize_keyboard=True)
                )
                return SEARCH_QUERY
            else:
                await update.message.reply_text(f"❌ '{text}' not found in **{scope}**.", parse_mode="Markdown")
                return await common_cancel(update, context)
            
        for row in rows[:5]: await send_word(update.message, row, context.user_data.get("is_admin_flag", False))
        return await common_cancel(update, context)

    # --- HANDLE OTHER SEARCH TYPES ---
    elif stype == "By Level": 
        sql = "SELECT * FROM words WHERE level = ?"
        params = (text,)
    elif stype == "By Topic": 
        sql = "SELECT * FROM words WHERE topic = ?"
        params = (text,)
    
    with db() as c: rows = c.execute(sql, params).fetchall()
    
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
        return await ai_add_process(update, context)
        
    elif text == "Yes, Manual Add":
        context.user_data["manual_step"] = 0
        context.user_data["topic"] = "General"
        await update.message.reply_text(f"Adding '{word}'.\nWhat is the **Level**? (A1-C2)")
        return MANUAL_ADD_LEVEL
        
    else:
        return await common_cancel(update, context)

# --- Settings ---
async def settings_choice(update, context):
    if update.message.text == "🔄 Source Priority":
        uid = update.effective_user.id
        with db() as c:
            row = c.execute("SELECT source_prefs FROM users WHERE user_id=?", (uid,)).fetchone()
        
        if row and row["source_prefs"]:
            current_str = ", ".join(json.loads(row["source_prefs"]))
        else:
            current_str = "Default"

        msg = (
            f"🔢 **Set Source Priority**\n\n"
            f"**Current:** {current_str}\n\n"
            "**Key:**\n"
            "1. Cambridge\n2. Longman\n3. Collins\n\n"
            "**Send order (e.g., `213` for Longman first).**"
        )
        await update.message.reply_text(msg, reply_markup=priority_keyboard(), parse_mode="Markdown")
        return SETTINGS_PRIORITY
    return await common_cancel(update, context)

async def set_priority(update, context):
    text = update.message.text.strip()
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    if not re.fullmatch(r"[1-3]{3}", text) or len(set(text)) != 3:
        await update.message.reply_text("❌ Invalid. Send 3 unique numbers (e.g., `213`).")
        return SETTINGS_PRIORITY

    # Updated Map with Collins
    mapping = {
        "1": "Cambridge",
        "2": "Longman",
        "3": "Collins"
    }
    
    new_order = [mapping[char] for char in text]
    
    uid = update.effective_user.id
    with db() as c:
        c.execute("UPDATE users SET source_prefs=? WHERE user_id=?", (json.dumps(new_order), uid))
        
    await update.message.reply_text(f"✅ Saved Priority:\n1. {new_order[0]}\n2. {new_order[1]}...")
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

def build_multi_select_keyboard(options, selected, callback_prefix, cols=3):
    """
    Generates an inline keyboard with checkmarks.
    options: List of strings (e.g., ['A1', 'A2'])
    selected: List of currently selected strings
    callback_prefix: Prefix for button data (e.g., "lvl_")
    """
    buttons = []
    row = []
    for opt in options:
        is_selected = opt in selected
        text = f"✅ {opt}" if is_selected else opt
        data = f"{callback_prefix}toggle_{opt}"
        row.append(InlineKeyboardButton(text, callback_data=data))
        
        if len(row) == cols:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    
    # Control Buttons
    buttons.append([
        InlineKeyboardButton("🗑 Clear / Any", callback_data=f"{callback_prefix}any"),
        InlineKeyboardButton("Done ➡️", callback_data=f"{callback_prefix}done")
    ])
    return InlineKeyboardMarkup(buttons)

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

# Step 2 — Time -> Triggers Level Selection
async def daily_time_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    
    time_text = update.message.text.strip()
    try:
        datetime.strptime(time_text, "%H:%M")
    except:
        await update.message.reply_text("Invalid Time. Use HH:MM format.")
        return DAILY_TIME

    context.user_data["daily_time"] = time_text
    context.user_data["temp_levels"] = [] # Init empty selection

    # Options available
    opts = ["A1", "A2", "B1", "B2", "C1", "C2"]
    kb = build_multi_select_keyboard(opts, [], "lvl_")
    
    await update.message.reply_text(
        "📊 **Select Level(s):**\nChoose one or more. Click 'Done' when finished.",
        reply_markup=kb, parse_mode="Markdown"
    )
    return DAILY_LEVEL

# Step 3 — Level (Callback Handler)
async def daily_level_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    current_selected = context.user_data.get("temp_levels", [])
    opts = ["A1", "A2", "B1", "B2", "C1", "C2"]

    if "toggle_" in data:
        val = data.split("toggle_")[1]
        if val in current_selected:
            current_selected.remove(val)
        else:
            current_selected.append(val)
        context.user_data["temp_levels"] = current_selected
        
        # Refresh Keyboard
        kb = build_multi_select_keyboard(opts, current_selected, "lvl_")
        await query.edit_message_reply_markup(kb)
        return DAILY_LEVEL

    elif "any" in data:
        context.user_data["temp_levels"] = []
        kb = build_multi_select_keyboard(opts, [], "lvl_")
        await query.edit_message_reply_markup(kb)
        return DAILY_LEVEL

    elif "done" in data:
        # Save Final Selection
        final_list = context.user_data.get("temp_levels", [])
        context.user_data["daily_level"] = ",".join(final_list) if final_list else "Any"

        # MOVE TO POS SELECTION
        context.user_data["temp_pos"] = []
        pos_opts = ["noun", "verb", "adjective", "adverb", "idiom", "phrasal verb"]
        kb = build_multi_select_keyboard(pos_opts, [], "pos_")
        
        await query.edit_message_text(
            f"✅ Level: {context.user_data['daily_level']}\n\n🏷 **Select Part(s) of Speech:**",
            reply_markup=kb, parse_mode="Markdown"
        )
        return DAILY_POS

# Step 4 — POS (Callback Handler)
async def daily_pos_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    current_selected = context.user_data.get("temp_pos", [])
    opts = ["noun", "verb", "adjective", "adverb", "idiom", "phrasal verb"]

    if "toggle_" in data:
        val = data.split("toggle_")[1]
        if val in current_selected:
            current_selected.remove(val)
        else:
            current_selected.append(val)
        context.user_data["temp_pos"] = current_selected
        
        kb = build_multi_select_keyboard(opts, current_selected, "pos_")
        await query.edit_message_reply_markup(kb)
        return DAILY_POS

    elif "any" in data:
        context.user_data["temp_pos"] = []
        kb = build_multi_select_keyboard(opts, [], "pos_")
        await query.edit_message_reply_markup(kb)
        return DAILY_POS

    elif "done" in data:
        # Save Final Selection
        final_list = context.user_data.get("temp_pos", [])
        context.user_data["daily_pos"] = ",".join(final_list) if final_list else "Any"
        
        # TRANSITION TO TOPIC (Smooth: Edit the existing message)
        return await daily_topic_entry(update, context, edit_mode=True)

# Helper to enter topic state
async def daily_topic_entry(update, context, edit_mode=False):
    # 1. Fetch Topics ONCE and Cache them
    with db() as c: rows = c.execute("SELECT DISTINCT topic FROM words").fetchall()
    topics = [r["topic"] for r in rows] if rows else ["General"]
    
    # SAVE TO CACHE
    context.user_data["cached_topics"] = topics 

    # Initialize empty selection
    context.user_data["temp_topics"] = []
    
    # Build Checkbox Keyboard
    kb = build_multi_select_keyboard(topics, [], "topic_", cols=2)
    
    text = (
        f"✅ POS: {context.user_data.get('daily_pos', 'Any')}\n\n"
        f"📚 **Select Book(s)/Topic(s):**\n"
        f"Choose one or more, then click 'Done'."
    )
    
    if edit_mode and update.callback_query:
        # Smooth transition: Edit the previous message
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        # Fallback: Send new message
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")
        
    return DAILY_TOPIC
    
# Step 5 — Topic (Callback Handler) + SAVE
async def daily_topic_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    # 1. Use Cached Topics
    all_topics = context.user_data.get("cached_topics", ["General"])
    # Fallback if cache empty
    if not all_topics:
         with db() as c: rows = c.execute("SELECT DISTINCT topic FROM words").fetchall()
         all_topics = [r["topic"] for r in rows] if rows else ["General"]
         context.user_data["cached_topics"] = all_topics

    current_selected = context.user_data.get("temp_topics", [])

    # === TOGGLE LOGIC ===
    if "toggle_" in data:
        val = data.split("toggle_")[1]
        
        # Toggle selection
        if val in current_selected:
            current_selected.remove(val)
        else:
            current_selected.append(val)
            
        context.user_data["temp_topics"] = current_selected
        
        # Rebuild keyboard with new checkmarks
        kb = build_multi_select_keyboard(all_topics, current_selected, "topic_", cols=2)
        
        # Smooth update (Try/Except handles "Message not modified" error if user spams click)
        try: await query.edit_message_reply_markup(kb)
        except: pass
        return DAILY_TOPIC

    # === CLEAR / ANY LOGIC ===
    elif "any" in data:
        context.user_data["temp_topics"] = []
        kb = build_multi_select_keyboard(all_topics, [], "topic_", cols=2)
        try: await query.edit_message_reply_markup(kb)
        except: pass
        return DAILY_TOPIC

    # === DONE LOGIC ===
    elif "done" in data:
        # Save Final Selection
        final_list = context.user_data.get("temp_topics", [])
        final_topic_str = ",".join(final_list) if final_list else "Any"
        
        # DB SAVE
        uid = update.effective_user.id
        d = context.user_data
        
        with db() as c:
            c.execute("""
                INSERT INTO users (user_id, daily_enabled, daily_count, daily_time, daily_level, daily_pos, daily_topic)
                VALUES (?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                daily_enabled=1, daily_count=excluded.daily_count, daily_time=excluded.daily_time, 
                daily_level=excluded.daily_level, daily_pos=excluded.daily_pos, daily_topic=excluded.daily_topic
            """, (uid, d.get("daily_count"), d.get("daily_time"), d.get("daily_level"), d.get("daily_pos"), final_topic_str))

        # 1. Edit the inline message to show "Saved" state
        summary_text = (
            f"✅ **Daily Words Activated!**\n"
            f"________________________\n"
            f"📅 Count: `{d.get('daily_count')}`\n"
            f"⏰ Time: `{d.get('daily_time')}`\n"
            f"📊 Level: `{d.get('daily_level')}`\n"
            f"🏷 POS: `{d.get('daily_pos')}`\n"
            f"📚 Topic: `{final_topic_str}`"
        )
        try: await query.edit_message_text(summary_text, parse_mode="Markdown")
        except: pass

        # 2. SEND NEW MESSAGE with Main Menu (Auto-Exit)
        is_admin = uid in ADMIN_IDS
        await context.bot.send_message(
            chat_id=uid,
            text="🏠 Returning to Main Menu...",
            reply_markup=main_keyboard_bottom(is_admin)
        )
        return ConversationHandler.END

# --- Add Word ---
async def add_choice(update, context):
    text = update.message.text
    if text == "🤖 AI": await update.message.reply_text("Word?"); return AI_ADD_INPUT
    if text == "Manual": await update.message.reply_text("Topic?"); return MANUAL_ADD_TOPIC
    return await common_cancel(update, context)

async def ai_add_process(update, context):
    # 1. Get the word
    if "add_preload" in context.user_data:
        word = context.user_data["add_preload"]
        del context.user_data["add_preload"]
    else:
        word = update.message.text.strip()
    
    # 2. Check for Cancel
    if word == "🏠 Cancel":
        return await common_cancel(update, context)

    status_msg = await update.message.reply_text("🔍 Analyzing...")
    
    # 3. Try Web First
    scraped = get_words_from_web(word, update.effective_user.id)
    
    if not scraped:
        # 4. Ask AI (with validation check)
        ai_text = ai_generate_full_words_list(word)
        
        # 🛑 SECURITY CHECK: Did AI say it's nonsense?
        if "INVALID" in ai_text:
            try: await status_msg.delete()
            except: pass
            await update.message.reply_text(f"❌ '{word}' does not appear to be a valid English word.\n\nPlease type a real word (or /cancel):")
            return AI_ADD_INPUT # <--- Keeps user in the loop to try again
            
        scraped = parse_ai_response(ai_text, word)
    else:
        # Web found it, fill gaps
        scraped = ai_fill_missing(scraped)
    
    # 5. Save if we have data
    if not scraped:
        try: await status_msg.delete()
        except: pass
        await update.message.reply_text("❌ Could not find definition. Try another word:")
        return AI_ADD_INPUT

    count, dups = await save_word_list_to_db(scraped)
    
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
async def send_word(update_obj, row, is_admin=False):
    # Support both Message and CallbackQuery updates
    if hasattr(update_obj, 'reply_text'):
        message_func = update_obj.reply_text
    else:
        message_func = update_obj.message.reply_text

    if not row:
        await message_func("No word found.")
        return

    text = (
        f"📖 *{row['word']}*\n"
        f"🏷 {row['level']} | {row['topic']}\n"
        f"💡 {row['definition']}\n"
        f"📝 _Ex: {row['example']}_\n"
        f"🗣 {row['pronunciation']}\n"
        f"📚 _Source: {row['source']}_"
    )
    
    # ADMIN BUTTONS
    kb = None
    if is_admin:
        wid = row['id']
        buttons = [
            [InlineKeyboardButton("✏️ Edit", callback_data=f"edit_start_{wid}"), 
             InlineKeyboardButton("🗑 Delete", callback_data=f"del_conf_{wid}")]
        ]
        kb = InlineKeyboardMarkup(buttons)

    await message_func(text, parse_mode="Markdown", reply_markup=kb)

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
    
    # 1. Get users scheduled for NOW
    with db() as c: 
        users = c.execute("SELECT * FROM users WHERE daily_enabled=1 AND daily_time=?", (now_str,)).fetchall()
    
    for u in users:
        user_id = u["user_id"]
        
        for _ in range(u["daily_count"]):
            # 2. Use the Smart Picker (Avoids Repeats)
            word_row = pick_word_for_user(user_id)
            
            if word_row:
                # 3. Format the text manually (since we can't use the reply helper)
                text = (
                    f"📖 *{word_row['word']}*\n"
                    f"🏷 {word_row['level']} | {word_row['topic']}\n"
                    f"💡 {word_row['definition']}\n"
                    f"📝 _Ex: {word_row['example']}_\n"
                    f"🗣 {word_row['pronunciation']}\n"
                    f"📚 _Source: {word_row['source']}_"
                )
                try:
                    # 4. Send directly to the User ID
                    await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
                except: 
                    pass

# --- PAGINATION SYSTEM ---
ITEMS_PER_PAGE = 20

async def list_choice_handler(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    # Store topic and reset page
    context.user_data["list_topic"] = text
    context.user_data["list_page"] = 0
    
    await send_list_page(update, context)
    return LIST_TOPIC

async def send_list_page(update, context, edit_msg=False):
    topic = context.user_data.get("list_topic", "🌍 All Words")
    page = context.user_data.get("list_page", 0)
    offset = page * ITEMS_PER_PAGE
    
    # Build Query
    query = "SELECT word, level, id FROM words"
    params = []
    if topic != "🌍 All Words":
        query += " WHERE topic = ?"
        params.append(topic)
    
    query += f" ORDER BY word LIMIT {ITEMS_PER_PAGE} OFFSET {offset}"
    
    with db() as c: rows = c.execute(query, params).fetchall()
    
    if not rows:
        text = "End of list."
        buttons = [[InlineKeyboardButton("🔙 Back to Start", callback_data="page_0")]]
    else:
        text = f"📂 *List: {topic}* (Page {page + 1})\n\n"
        for r in rows:
            text += f"▫️ {r['word']} ({r['level']})\n"
            
        # Navigation Buttons
        nav_row = []
        if page > 0: nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
        buttons = [nav_row]

    kb = InlineKeyboardMarkup(buttons)
    
    if edit_msg:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def list_callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("page_"):
        new_page = int(data.split("_")[1])
        context.user_data["list_page"] = new_page
        await send_list_page(update, context, edit_msg=True)
    return LIST_TOPIC

# --- ADMIN ACTIONS ---

async def admin_callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    # DELETE FLOW
    if data.startswith("del_conf_"):
        wid = data.split("_")[2]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"del_do_{wid}"),
            InlineKeyboardButton("❌ No", callback_data="del_cancel")
        ]])
        await query.edit_message_text("⚠️ Are you sure you want to delete this word?", reply_markup=kb)
        return ConversationHandler.END

    if data == "del_cancel":
        await query.delete_message()
        return ConversationHandler.END

    if data.startswith("del_do_"):
        wid = data.split("_")[2]
        with db() as c: c.execute("DELETE FROM words WHERE id=?", (wid,))
        await query.edit_message_text("🗑 Word deleted.")
        return ConversationHandler.END

    # EDIT FLOW
    if data.startswith("edit_start_"):
        wid = data.split("_")[2]
        context.user_data["edit_id"] = wid
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Word", callback_data="edit_f_word"), InlineKeyboardButton("Def", callback_data="edit_f_definition")],
            [InlineKeyboardButton("Ex", callback_data="edit_f_example"), InlineKeyboardButton("Level", callback_data="edit_f_level")],
            [InlineKeyboardButton("Topic", callback_data="edit_f_topic")]
        ])
        await query.edit_message_text("Select field to edit:", reply_markup=kb)
        return EDIT_CHOOSE

    if data.startswith("edit_f_"):
        field = data.split("_")[2]
        context.user_data["edit_field"] = field
        await query.edit_message_text(f"📝 Enter new value for **{field}**:", parse_mode="Markdown")
        return EDIT_VALUE

    return ConversationHandler.END

async def edit_save_handler(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    wid = context.user_data["edit_id"]
    field = context.user_data["edit_field"]
    
    with db() as c:
        c.execute(f"UPDATE words SET {field}=? WHERE id=?", (text, wid))
        # Fetch updated word to show result
        row = c.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
        
    await update.message.reply_text("✅ Updated!")
    await send_word(update.message, row, is_admin=True)
    return ConversationHandler.END

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
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_choice)],
            AI_ADD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add_process)],
            
            MANUAL_ADD_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_EX: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_PRON: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],

            DAILY_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_count_handler)],
            DAILY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_time_handler)],
            DAILY_LEVEL: [CallbackQueryHandler(daily_level_handler)],
            DAILY_POS: [CallbackQueryHandler(daily_pos_handler)],
            DAILY_TOPIC: [CallbackQueryHandler(daily_topic_handler)],

            # LIST LOGIC
            LIST_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, list_choice_handler)],
            LIST_TOPIC: [CallbackQueryHandler(list_callback_handler)],
            
            # EDIT LOGIC
            EDIT_CHOOSE: [CallbackQueryHandler(admin_callback_handler)],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_save_handler)],
            
            SEARCH_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_choice)],
            
            # SEARCH QUERY (Note the change in the second handler below)
            SEARCH_QUERY: [
                MessageHandler(filters.Regex("^(Yes, AI Add|Yes, Manual Add)$"), search_add_redirect), 
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_perform)
            ],

            SETTINGS_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_choice)],
            SETTINGS_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_priority)],
            REPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_handler)],
            
            BULK_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_choice)],
            BULK_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_manual)],
            BULK_AI: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_ai)],
            BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_handler)],
        },
        fallbacks=[
            CommandHandler("cancel", common_cancel), 
            MessageHandler(filters.Regex("^🏠 Cancel$"), common_cancel),
            CommandHandler("start", start)  # <--- THIS LINE FIXES IT
        ]
    )
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(del_|edit_)"))
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()








