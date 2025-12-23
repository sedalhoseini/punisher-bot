from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
    MessageHandler,
    filters
)
import os, json, random
from datetime import datetime
import pytz

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
ADMIN_USER_IDS = {527164608}  # Replace with your Telegram ID
WORDS_FILE = "words.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
LOCAL_TZ = pytz.timezone("Asia/Tehran")  # Adjust if needed

# ===== GLOBALS =====
pending_words = {}  # {admin_user_id: topic} for /addwords
last_sent_minutes = {}  # {user_id: last_sent_minute}

# ===== HELPERS =====
def load_json(file_path, default):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in ADMIN_USER_IDS:
            await update.message.reply_text("You are not allowed to use this command.")
            return
        return await func(update, context)
    return wrapper

def get_words(topic=None):
    words_data = load_json(WORDS_FILE, {})
    if topic:
        return words_data.get(topic, [])
    else:
        # Flatten all words if no topic
        return [w for ws in words_data.values() for w in ws]

# ===== ADMIN COMMANDS =====
@admin_only
async def addwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /addwords <topic>")
        return
    topic = context.args[0]
    pending_words[update.effective_user.id] = topic
    await update.message.reply_text(f"Send the words line by line for topic '{topic}' now.")

async def receive_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pending_words:
        return  # Not in adding mode
    topic = pending_words.pop(user_id)
    new_words = update.message.text.splitlines()
    words_data = load_json(WORDS_FILE, {})
    words_data.setdefault(topic, [])
    added_count = 0
    for w in new_words:
        w_clean = w.strip()
        if w_clean and w_clean not in words_data[topic]:
            words_data[topic].append(w_clean)
            added_count += 1
    save_json(WORDS_FILE, words_data)
    await update.message.reply_text(f"Added {added_count} words to topic '{topic}'.")

@admin_only
async def listtopics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words_data = load_json(WORDS_FILE, {})
    if not words_data:
        await update.message.reply_text("No topics available.")
        return
    await update.message.reply_text("Topics:\n" + "\n".join(words_data.keys()))

@admin_only
async def listwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /listwords <topic>")
        return
    topic = context.args[0]
    words = get_words(topic)
    if not words:
        await update.message.reply_text(f"No words found for topic '{topic}'.")
        return
    await update.message.reply_text(f"Words for '{topic}':\n" + "\n".join(words))

# ===== USER COMMANDS =====
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    if user_id in subs:
        await update.message.reply_text("You are already subscribed.")
        return
    subs[user_id] = {"time": "09:00", "topic": None}
    save_json(SUBSCRIPTIONS_FILE, subs)
    await update.message.reply_text("Subscribed to daily words. Default time is 09:00. Use /settime HH:MM to change.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    if user_id in subs:
        subs.pop(user_id)
        save_json(SUBSCRIPTIONS_FILE, subs)
        await update.message.reply_text("Unsubscribed from daily words.")
    else:
        await update.message.reply_text("You were not subscribed.")

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /settime HH:MM (24-hour)")
        return
    t = context.args[0]
    try:
        hh, mm = map(int, t.split(":"))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except:
        await update.message.reply_text("Invalid time format. Use HH:MM (24-hour).")
        return
    user_id = str(update.effective_user.id)
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    if user_id not in subs:
        await update.message.reply_text("You are not subscribed. Use /subscribe first.")
        return
    subs[user_id]["time"] = t
    save_json(SUBSCRIPTIONS_FILE, subs)
    await update.message.reply_text(f"Your daily word time is set to {t}.")

async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words_data = load_json(WORDS_FILE, {})
    if not words_data:
        await update.message.reply_text("No topics available.")
        return
    await update.message.reply_text("Available topics:\n" + "\n".join(words_data.keys()))

async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /settopic <topic>")
        return
    topic = context.args[0]
    words_data = load_json(WORDS_FILE, {})
    if topic not in words_data:
        await update.message.reply_text("Topic not found.")
        return
    user_id = str(update.effective_user.id)
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    if user_id not in subs:
        await update.message.reply_text("You are not subscribed. Use /subscribe first.")
        return
    subs[user_id]["topic"] = topic
    save_json(SUBSCRIPTIONS_FILE, subs)
    await update.message.reply_text(f"Your daily word topic is set to '{topic}'.")

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    if user_id not in subs:
        await update.message.reply_text("You are not subscribed. Use /subscribe first.")
        return
    topic = subs[user_id].get("topic")
    words = get_words(topic)
    if not words:
        await update.message.reply_text("No words available yet.")
        return
    await update.message.reply_text(f"Today's word: {random.choice(words)}")

# ===== DAILY JOB =====
async def send_daily_words(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(LOCAL_TZ)
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    for user_id, data in subs.items():
        hh, mm = map(int, data.get("time", "09:00").split(":"))
        # Avoid sending multiple times within same minute
        last_min = last_sent_minutes.get(user_id)
        if now.hour == hh and now.minute == mm and last_min != now.minute:
            topic = data.get("topic")
            words = get_words(topic)
            if not words:
                continue
            word = random.choice(words)
            try:
                await context.bot.send_message(chat_id=int(user_id), text=f"Daily word: {word}")
                last_sent_minutes[user_id] = now.minute
            except Exception as e:
                print(f"Failed to send daily word to {user_id}: {e}")

# ===== APPLICATION =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# ---- ADMIN HANDLERS ----
app.add_handler(CommandHandler("addwords", addwords))
app.add_handler(CommandHandler("listtopics", listtopics))
app.add_handler(CommandHandler("listwords", listwords))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_words))

# ---- USER HANDLERS ----
app.add_handler(CommandHandler("subscribe", subscribe))
app.add_handler(CommandHandler("unsubscribe", unsubscribe))
app.add_handler(CommandHandler("settime", settime))
app.add_handler(CommandHandler("topics", topics))
app.add_handler(CommandHandler("settopic", settopic))
app.add_handler(CommandHandler("today", today))

# ---- JOB QUEUE ----
job_queue: JobQueue = app.job_queue
job_queue.run_repeating(send_daily_words, interval=60, first=10)

print("Daily Word Bot with feedback is running...")
app.run_polling()
