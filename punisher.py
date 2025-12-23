from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
)
import os, json, random, asyncio
from datetime import datetime, time as dt_time, timedelta

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Or set directly: BOT_TOKEN = "YOUR_TOKEN_HERE"
ADMIN_USER_IDS = {527164608}  # Replace with your admin ID

WORDS_FILE = "words.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"

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

# ===== WORD MANAGEMENT =====
@admin_only
async def addwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /addwords <topic>\nThen send words line by line in the next message.")
        return

    topic = context.args[0]
    context.user_data['pending_topic'] = topic
    await update.message.reply_text(f"Send the words for topic '{topic}', one per line.")

async def receive_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'pending_topic' not in context.user_data:
        return  # Ignore if not adding words

    topic = context.user_data.pop('pending_topic')
    new_words = update.message.text.splitlines()
    words_data = load_json(WORDS_FILE, {})
    words_data.setdefault(topic, [])
    for w in new_words:
        w_clean = w.strip()
        if w_clean and w_clean not in words_data[topic]:
            words_data[topic].append(w_clean)
    save_json(WORDS_FILE, words_data)
    await update.message.reply_text(f"Added {len(new_words)} words to topic '{topic}'.")

async def listtopics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words_data = load_json(WORDS_FILE, {})
    if not words_data:
        await update.message.reply_text("No topics available.")
        return
    await update.message.reply_text("Topics:\n" + "\n".join(words_data.keys()))

async def listwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /listwords <topic>")
        return
    topic = context.args[0]
    words_data = load_json(WORDS_FILE, {})
    if topic not in words_data or not words_data[topic]:
        await update.message.reply_text(f"No words found for topic '{topic}'.")
        return
    await update.message.reply_text(f"Words for '{topic}':\n" + "\n".join(words_data[topic]))

# ===== USER SUBSCRIPTION =====
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    if user_id in subs:
        await update.message.reply_text("You are already subscribed.")
        return
    subs[user_id] = {"time": "09:00", "topic": None}  # default 9 AM
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
        datetime.strptime(t, "%H:%M")
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
    words_data = load_json(WORDS_FILE, {})
    if topic:
        words = words_data.get(topic, [])
    else:
        # all words
        words = [w for ws in words_data.values() for w in ws]
    if not words:
        await update.message.reply_text("No words available yet.")
        return
    await update.message.reply_text(f"Today's word: {random.choice(words)}")

# ===== DAILY SENDING =====
async def send_daily_words(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow()
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    words_data = load_json(WORDS_FILE, {})

    for user_id, data in subs.items():
        hh, mm = map(int, data.get("time", "09:00").split(":"))
        # compare UTC time (adjust if needed for your timezone)
        if now.hour == hh and now.minute == mm:
            topic = data.get("topic")
            if topic:
                words = words_data.get(topic, [])
            else:
                words = [w for ws in words_data.values() for w in ws]
            if words:
                word = random.choice(words)
                try:
                    await context.bot.send_message(chat_id=int(user_id), text=f"Daily word: {word}")
                except Exception as e:
                    print(f"Failed to send to {user_id}: {e}")

# ===== APPLICATION =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# ---- ADMIN HANDLERS ----
app.add_handler(CommandHandler("addwords", addwords))
app.add_handler(CommandHandler("listtopics", listtopics))
app.add_handler(CommandHandler("listwords", listwords))
app.add_handler(MessageHandler(None, receive_words))  # catch message for adding words

# ---- USER HANDLERS ----
app.add_handler(CommandHandler("subscribe", subscribe))
app.add_handler(CommandHandler("unsubscribe", unsubscribe))
app.add_handler(CommandHandler("settime", settime))
app.add_handler(CommandHandler("topics", topics))
app.add_handler(CommandHandler("settopic", settopic))
app.add_handler(CommandHandler("today", today))

# ---- JOB QUEUE ----
job_queue: JobQueue = app.job_queue
job_queue.run_repeating(send_daily_words, interval=60, first=10)  # check every minute

print("Daily Word Bot is running...")
app.run_polling()
