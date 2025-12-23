import os
import json
import random
import pytz
from datetime import datetime, time as dt_time
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Make sure this is set in your environment
ADMIN_IDS = {527164608}  # Add your admin Telegram ID(s)
DATA_FILE = "daily_words.json"
TIMEZONE = pytz.timezone("Asia/Tehran")

# ===== STORAGE HELPERS =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"words": {}, "students": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ===== HELPERS =====
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            await update.message.reply_text("You are not allowed to use this command.")
            return
        return await func(update, context)
    return wrapper

def pick_word(words_data, topic=None):
    if topic:
        topic_words = words_data.get(topic, [])
    else:
        topic_words = [w for t in words_data.values() for w in t]
    return random.choice(topic_words) if topic_words else None

# ===== ADMIN COMMANDS =====
@admin_only
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if len(context.args) < 2:
        await msg.reply_text("Usage: /addword <topic> <word1,word2,...>")
        return
    topic = context.args[0]
    words = " ".join(context.args[1:]).split(",")
    data = load_data()
    data["words"].setdefault(topic, [])
    data["words"][topic].extend([w.strip() for w in words if w.strip()])
    save_data(data)
    await msg.reply_text(f"Added words to topic '{topic}': {', '.join(words)}")

@admin_only
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    topics = list(data["words"].keys())
    if not topics:
        await update.message.reply_text("No topics available yet.")
        return
    await update.message.reply_text("Topics:\n" + "\n".join(topics))

# ===== STUDENT COMMANDS =====
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = str(msg.from_user.id)
    mode = "random"
    topic = None
    send_time = "09:00"
    # Parse optional arguments
    for arg in context.args:
        if arg.startswith("time="):
            send_time = arg.split("=")[1]
        elif arg.startswith("topic="):
            topic = arg.split("=")[1]
        elif arg.startswith("mode="):
            mode = arg.split("=")[1]
    data = load_data()
    data["students"][user_id] = {"mode": mode, "topic": topic, "time": send_time}
    save_data(data)
    await msg.reply_text(f"Subscribed to daily words at {send_time}. Mode: {mode}. Topic: {topic or 'any'}")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = str(msg.from_user.id)
    data = load_data()
    if user_id in data["students"]:
        data["students"].pop(user_id)
        save_data(data)
        await msg.reply_text("You have unsubscribed from daily words.")
    else:
        await msg.reply_text("You are not subscribed.")

async def get_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = str(msg.from_user.id)
    data = load_data()
    info = data["students"].get(user_id, {})
    topic = info.get("topic", None)
    word = pick_word(data["words"], topic)
    if not word:
        await msg.reply_text("No words available yet.")
        return
    await msg.reply_text(f"Your word: {word}")

# ===== DEBUG HANDLER =====
async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Received: {update.message.text}")

# ===== SCHEDULED DAILY WORD TASK =====
async def daily_word_job(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    now = datetime.now(TIMEZONE)
    for user_id, info in data["students"].items():
        try:
            hour, minute = map(int, info.get("time", "09:00").split(":"))
            if now.hour == hour and now.minute == minute:
                topic = info.get("topic")
                word = pick_word(data["words"], topic)
                if word:
                    await context.bot.send_message(chat_id=int(user_id), text=f"Today's word: {word}")
                else:
                    await context.bot.send_message(chat_id=int(user_id), text="No words available yet.")
        except Exception as e:
            print(f"Error sending daily word to {user_id}: {e}")

# ===== APPLICATION SETUP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Admin
app.add_handler(CommandHandler("addword", add_word))
app.add_handler(CommandHandler("listtopics", list_topics))

# Students
app.add_handler(CommandHandler("subscribe", subscribe))
app.add_handler(CommandHandler("unsubscribe", unsubscribe))
app.add_handler(CommandHandler("getword", get_word))

# Debug
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug))

# Schedule job every minute
app.job_queue.run_repeating(daily_word_job, interval=60, first=0)

print("Daily Word Bot running...")
app.run_polling()
