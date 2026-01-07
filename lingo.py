import os
import re
import sqlite3
import json
import asyncio
from datetime import datetime, time, timedelta
import pytz
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus # <--- NEW
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)
import requests
from bs4 import BeautifulSoup

# ================= VERSION INFO =================
BOT_VERSION = "0.7.0"
VERSION_DATE = "2026-01-07"
CHANGELOG = "• 📢 Channel Lock\n• 🗓️ Smart Daily (Multi-Source)\n• 🔍 Interactive Search"

# ================= STATES =================
(
    MANUAL_ADD_TOPIC, MANUAL_ADD_LEVEL, MANUAL_ADD_WORD, 
    MANUAL_ADD_DEF, MANUAL_ADD_EX, MANUAL_ADD_PRON, 
    ADD_CHOICE, AI_ADD_INPUT, 
    BROADCAST_MSG, 
    BULK_CHOICE, BULK_MANUAL, BULK_AI,
    
    # NEW UNIFIED STATES
    DAILY_COUNT, DAILY_TIME, 
    MULTI_SELECT_STATE,  # Handles ALL multi-selects (Topics, Levels)
    LIST_VIEW,           # Handles ALL lists (Search results, Browsing)
    SEARCH_QUERY,        # Text input for search
    
    REPORT_MSG,
    EDIT_CHOOSE, EDIT_VALUE,
    SETTINGS_CHOICE, SETTINGS_PRIORITY 
) = range(21)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = {527164608}
DB_PATH = "daily_words.db"
REQUIRED_CHANNELS = ["@Speaking_with_SedAl"]

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
    
# ================= HELPERS & UI ENGINE =================
async def check_channel_join(update, context):
    if not REQUIRED_CHANNELS: return True
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS: return True

    missing = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED, ChatMemberStatus.RESTRICTED]:
                missing.append(channel)
        except: pass
            
    if missing:
        buttons = [[InlineKeyboardButton(f"Join {c}", url=f"https://t.me/{c.replace('@','')}") for c in missing]]
        buttons.append([InlineKeyboardButton("✅ I Joined", callback_data="check_join")])
        msg = "🔒 *Access Restricted*\nPlease join our channels to use the bot:"
        if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return False
    return True

async def join_check_callback(update, context):
    if await check_channel_join(update, context):
        await update.callback_query.answer("✅ Verified!")
        await update.callback_query.edit_message_text("Welcome back! Type /start.")
    else: await update.callback_query.answer("❌ Still not joined.")

# --- MULTI-SELECT ENGINE ---
async def init_multiselect(update, context, key, prompt, next_state, options=None, single_choice=False):
    if not options:
        with db() as c: rows = c.execute("SELECT DISTINCT topic FROM words").fetchall()
        options = [r["topic"] for r in rows] if rows else ["General"]
    
    context.user_data.update({"ms_key": key, "ms_next": next_state, "ms_options": options, "ms_selected": [], "ms_single": single_choice})
    await send_multiselect_kb(update, context, prompt)
    return MULTI_SELECT_STATE

async def send_multiselect_kb(update, context, text):
    opts, sel, single = context.user_data["ms_options"], context.user_data["ms_selected"], context.user_data.get("ms_single", False)
    buttons = [InlineKeyboardButton(f"{'✅ ' if opt in sel else ''}{opt}", callback_data=f"ms_toggle_{i}") for i, opt in enumerate(opts)]
    kb = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    
    if not single:
        kb.append([InlineKeyboardButton("🌍 Select All", callback_data="ms_all"), InlineKeyboardButton("🧹 Clear", callback_data="ms_clear")])
        kb.append([InlineKeyboardButton("✅ Done" if sel else "❌ Cancel", callback_data="ms_done")])
    else: kb.append([InlineKeyboardButton("🏠 Cancel", callback_data="ms_cancel")])

    markup = InlineKeyboardMarkup(kb)
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=markup)
    else: await update.message.reply_text(text, reply_markup=markup)

async def multiselect_callback(update, context):
    query = update.callback_query; await query.answer(); data = query.data
    opts = context.user_data["ms_options"]
    
    if data == "ms_cancel": await query.delete_message(); return await common_cancel(update, context)
    if data == "ms_all": context.user_data["ms_selected"] = list(opts); await send_multiselect_kb(update, context, "Selected All:"); return MULTI_SELECT_STATE
    if data == "ms_clear": context.user_data["ms_selected"] = []; await send_multiselect_kb(update, context, "Cleared:"); return MULTI_SELECT_STATE

    if data.startswith("ms_toggle_"):
        val = opts[int(data.split("_")[2])]
        if context.user_data["ms_single"]:
            context.user_data[context.user_data["ms_key"]] = val
            return await trigger_next_state(update, context)
        else:
            if val in context.user_data["ms_selected"]: context.user_data["ms_selected"].remove(val)
            else: context.user_data["ms_selected"].append(val)
            await send_multiselect_kb(update, context, "Select options:")
            return MULTI_SELECT_STATE

    if data == "ms_done":
        context.user_data[context.user_data["ms_key"]] = context.user_data["ms_selected"] or ["All Sources"]
        return await trigger_next_state(update, context)

async def trigger_next_state(update, context):
    next_s = context.user_data["ms_next"]
    if next_s == LIST_VIEW:
        context.user_data["list_page"] = 0; await send_paginated_list(update, context); return LIST_VIEW
    if next_s == SEARCH_QUERY:
        return await init_multiselect(update, context, "search_level", "📊 Filter by Level:", next_state="SEARCH_INPUT_WAIT", options=["A1","A2","B1","B2","C1","C2"])
    if next_s == "SEARCH_INPUT_WAIT":
        await update.callback_query.edit_message_text("🔍 Enter word to search (or 'all'):"); return SEARCH_QUERY
    if next_s == "DAILY_LEVEL_WAIT":
        return await init_multiselect(update, context, "daily_level", "📊 Select Levels:", next_state="DAILY_FINISH", options=["A1","A2","B1","B2","C1","C2"])
    if next_s == "DAILY_FINISH":
        d = context.user_data
        with db() as c: c.execute("UPDATE users SET daily_enabled=1, daily_count=?, daily_time=?, daily_topic=?, daily_level=? WHERE user_id=?", (d["daily_count"], d["daily_time"], json.dumps(d["daily_topic"]), json.dumps(d.get("daily_level", [])), update.effective_user.id))
        await update.callback_query.edit_message_text("✅ Daily Schedule Saved!"); return ConversationHandler.END
    
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
        u = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u: return None

        query = "SELECT w.* FROM words w LEFT JOIN sent_words s ON w.id = s.word_id AND s.user_id = ? WHERE s.word_id IS NULL"
        params = [user_id]

        if u["daily_level"] and u["daily_level"] != "Skip":
            levels = json.loads(u["daily_level"]) if "[" in u["daily_level"] else [u["daily_level"]]
            if levels: query += f" AND w.level IN ({','.join('?'*len(levels))})"; params.extend(levels)

        if u["daily_topic"] and u["daily_topic"] != "🌍 All Sources":
            topics = json.loads(u["daily_topic"]) if "[" in u["daily_topic"] else [u["daily_topic"]]
            if topics and "All Sources" not in topics:
                query += f" AND w.topic IN ({','.join('?'*len(topics))})"; params.extend(topics)

        query += " ORDER BY RANDOM() LIMIT 1"
        row = c.execute(query, params).fetchone()
        
        if not row:
            # Smart Reset
            reset_sql = "DELETE FROM sent_words WHERE user_id = ? AND word_id IN (SELECT id FROM words WHERE 1=1"
            reset_params = [user_id]
            if u["daily_topic"] and "All Sources" not in topics:
                reset_sql += f" AND topic IN ({','.join('?'*len(topics))})"; reset_params.extend(topics)
            reset_sql += ")"
            c.execute(reset_sql, reset_params)
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
    if not await check_channel_join(update, context): return ConversationHandler.END
    
    text = update.message.text
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS
    context.user_data["is_admin_flag"] = is_admin

    if text == "🎯 Get Word":
        word = pick_word_for_user(uid)
        await send_word(update.message, word, is_admin)
        return ConversationHandler.END

    if text == "📚 List Words":
        return await init_multiselect(update, context, "list_topic", "📂 Choose Topic:", next_state=LIST_VIEW, single_choice=True)

    if text == "🔍 Search":
        return await init_multiselect(update, context, "search_topic", "🔍 Search in which topics?", next_state=SEARCH_QUERY)

    if text == "⏰ Daily Words":
        with db() as c: u = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        status = "❌ *Disabled*"
        if u and u["daily_enabled"]:
            t_list = json.loads(u["daily_topic"]) if u["daily_topic"] and "[" in u["daily_topic"] else [u["daily_topic"] or "All"]
            status = f"✅ *Active*\n📅 {u['daily_count']} words at {u['daily_time']}\n📚 {', '.join(t_list)}"
        await update.message.reply_text(f"{status}\n\nTo configure, enter **Count** (1-50):", parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup([["🔕 Deactivate"], ["🏠 Cancel"]], resize_keyboard=True))
        return DAILY_COUNT

    # KEEPING EXISTING HANDLERS FOR ADD/SETTINGS/ETC
    if text == "➕ Add Word": await update.message.reply_text("Add Method:", reply_markup=add_word_choice_keyboard()); return ADD_CHOICE
    if text == "⚙️ Settings": await update.message.reply_text("Settings:", reply_markup=settings_keyboard()); return SETTINGS_CHOICE
    if text == "🐞 Report": await update.message.reply_text("Type report:", reply_markup=ReplyKeyboardMarkup([["🏠 Cancel"]], resize_keyboard=True)); return REPORT_MSG
    
    if is_admin:
        if text == "📦 Bulk Add": await update.message.reply_text("Bulk Type:", reply_markup=add_word_choice_keyboard()); return BULK_CHOICE
        if text == "📣 Broadcast": await update.message.reply_text("Enter message:"); return BROADCAST_MSG
        if text == "🗑 Clear Words": 
            with db() as c: c.execute("DELETE FROM words")
            await update.message.reply_text("Cleared.")
        if text == "🛡 Backup": await auto_backup(context)

    await update.message.reply_text("Menu:", reply_markup=main_keyboard_bottom(is_admin))
    return ConversationHandler.END


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

async def auto_backup(context):
    now = datetime.now()
    filename = f"backup_{now.strftime('%Y-%m-%d_%H-%M')}.db"
    for admin_id in ADMIN_IDS:
        try:
            with open(DB_PATH, 'rb') as f: await context.bot.send_document(admin_id, f, filename=filename, caption=f"Backup {now.strftime('%H:%M')}")
        except: pass

# ================= NEW UNIFIED LOGIC =================
ITEMS_PER_PAGE = 20

async def send_paginated_list(update, context, edit_msg=True):
    page = context.user_data.get("list_page", 0)
    offset = page * ITEMS_PER_PAGE
    topics = context.user_data.get("list_topic") or context.user_data.get("search_topic")
    levels = context.user_data.get("search_level")
    search_q = context.user_data.get("search_query_text")

    sql = "SELECT id, word, level FROM words WHERE 1=1"
    params = []

    if topics and topics != "🌍 All Words" and topics != ["All Sources"]:
        if isinstance(topics, list):
            placeholders = ",".join("?" * len(topics))
            sql += f" AND topic IN ({placeholders})"
            params.extend(topics)
        else:
            sql += " AND topic = ?"
            params.append(topics)

    if levels:
        placeholders = ",".join("?" * len(levels))
        sql += f" AND level IN ({placeholders})"
        params.extend(levels)

    if search_q and search_q.lower() != "all":
        sql += " AND lower(word) LIKE ?"
        params.append(f"%{search_q.lower()}%")

    sql += f" ORDER BY word LIMIT {ITEMS_PER_PAGE} OFFSET {offset}"
    with db() as c: rows = c.execute(sql, params).fetchall()

    if not rows:
        msg = "📭 No words found."
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu_home")]])
    else:
        msg = f"📂 Page {page+1}"
        buttons = [InlineKeyboardButton(f"{r['word']}", callback_data=f"w_view_{r['id']}") for r in rows]
        kb = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
        
        nav = []
        if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"page_{page-1}"))
        nav.append(InlineKeyboardButton("➡️", callback_data=f"page_{page+1}"))
        kb.append(nav)
        kb.append([InlineKeyboardButton("📂 Switch Topic", callback_data="switch_topic")])
        markup = InlineKeyboardMarkup(kb)
    
    if hasattr(update, 'callback_query') and update.callback_query and edit_msg:
        await update.callback_query.edit_message_text(msg, reply_markup=markup)
    else:
        await update.message.reply_text(msg, reply_markup=markup)

async def list_action_handler(update, context):
    query = update.callback_query; await query.answer(); data = query.data
    if data == "switch_topic": return await init_multiselect(update, context, "list_topic", "📂 Switch to:", next_state=LIST_VIEW, single_choice=True)
    if data == "menu_home": await query.delete_message(); return ConversationHandler.END
    if data.startswith("page_"):
        context.user_data["list_page"] = int(data.split("_")[1])
        await send_paginated_list(update, context)
        return LIST_VIEW
    if data.startswith("w_view_"):
        with db() as c: row = c.execute("SELECT * FROM words WHERE id=?", (data.split("_")[2],)).fetchone()
        await send_word(update, row, context.user_data.get("is_admin_flag", False))
        return LIST_VIEW 
    return LIST_VIEW

async def daily_count_handler(update, context):
    text = update.message.text
    if text == "🔕 Deactivate":
        with db() as c: c.execute("UPDATE users SET daily_enabled=0 WHERE user_id=?", (update.effective_user.id,))
        await update.message.reply_text("✅ Daily disabled.")
        return ConversationHandler.END
    try:
        if not (1 <= int(text) <= 50): raise ValueError
        context.user_data["daily_count"] = int(text)
        await update.message.reply_text("⏰ Time? (HH:MM):")
        return DAILY_TIME
    except: return DAILY_COUNT

async def daily_time_handler(update, context):
    try:
        datetime.strptime(update.message.text.strip(), "%H:%M")
        context.user_data["daily_time"] = update.message.text.strip()
        return await init_multiselect(update, context, "daily_topic", "📚 Select Sources:", next_state="DAILY_LEVEL_WAIT", single_choice=False)
    except: return DAILY_TIME

async def search_perform(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    context.user_data["search_query_text"] = text
    context.user_data["list_page"] = 0
    await send_paginated_list(update, context, edit_msg=False)
    return LIST_VIEW

# --- UPDATED SYSTEM FUNCTIONS ---
async def send_word(update_obj, row, is_admin=False):
    func = update_obj.message.reply_text if hasattr(update_obj, 'message') else update_obj.reply_text
    if not row: await func("Word not found."); return
    text = f"📖 *{row['word']}*\n🏷 {row['level']} | {row['topic']}\n💡 {row['definition']}\n📝 _{row['example']}_\n🗣 {row['pronunciation']}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Edit", callback_data=f"edit_start_{row['id']}"), InlineKeyboardButton("🗑 Delete", callback_data=f"del_conf_{row['id']}") ]]) if is_admin else None
    await func(text, parse_mode="Markdown", reply_markup=kb)

async def admin_callback_handler(update, context):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("del_conf_"): await query.edit_message_text("Delete?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data=f"del_do_{data.split('_')[2]}"), InlineKeyboardButton("❌ No", callback_data="del_cancel")]])); return ConversationHandler.END
    if data == "del_cancel": await query.delete_message(); return ConversationHandler.END
    if data.startswith("del_do_"):
        with db() as c: c.execute("DELETE FROM words WHERE id=?", (data.split("_")[2],))
        await query.edit_message_text("🗑 Deleted."); return ConversationHandler.END
    if data.startswith("edit_start_"):
        context.user_data["edit_id"] = data.split("_")[2]
        await query.edit_message_text("Edit what?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Def", callback_data="edit_f_definition"), InlineKeyboardButton("Ex", callback_data="edit_f_example")]])); return EDIT_CHOOSE
    if data.startswith("edit_f_"): context.user_data["edit_field"] = data.split("_")[2]; await query.edit_message_text(f"📝 Enter new value:"); return EDIT_VALUE
    return ConversationHandler.END

async def edit_save_handler(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    with db() as c: c.execute(f"UPDATE words SET {context.user_data['edit_field']}=? WHERE id=?", (text, context.user_data['edit_id']))
    await update.message.reply_text("✅ Updated!"); return ConversationHandler.END

async def send_daily_scheduler(context):
    tehran = pytz.timezone("Asia/Tehran")
    now_str = datetime.now(tehran).strftime("%H:%M")
    with db() as c: users = c.execute("SELECT * FROM users WHERE daily_enabled=1 AND daily_time=?", (now_str,)).fetchall()
    
    for u in users:
        for _ in range(u["daily_count"]):
            word = pick_word_for_user(u["user_id"])
            if word:
                try: await context.bot.send_message(u["user_id"], f"⏰ Daily Word:\n\n📖 *{word['word']}*\n💡 {word['definition']}", parse_mode="Markdown")
                except: pass

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Precision Timing: Start exactly at 00 seconds
    now = datetime.now(); seconds_left = 60 - now.second
    app.job_queue.run_repeating(send_daily_scheduler, interval=60, first=seconds_left)

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
        states={
            # DAILY
            DAILY_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_count_handler)],
            DAILY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_time_handler)],
            # MULTI-SELECT
            MULTI_SELECT_STATE: [CallbackQueryHandler(multiselect_callback)],
            # LIST/SEARCH VIEW
            LIST_VIEW: [CallbackQueryHandler(list_action_handler)],
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_perform)],
            
            # ADMIN
            EDIT_CHOOSE: [CallbackQueryHandler(admin_callback_handler)],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_save_handler)],
            
            # LEGACY (ADD/BULK/SETTINGS)
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_choice)],
            AI_ADD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add_process)],
            MANUAL_ADD_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_EX: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            MANUAL_ADD_PRON: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add_steps)],
            SETTINGS_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_choice)],
            SETTINGS_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_priority)],
            REPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_handler)],
            BULK_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_choice)],
            BULK_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_manual)],
            BULK_AI: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_ai)],
            BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_handler)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", common_cancel)]
    )
    
    app.add_handler(CallbackQueryHandler(join_check_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(del_|edit_)"))
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()

