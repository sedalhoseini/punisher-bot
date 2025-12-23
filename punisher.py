import os
import json
import random
from datetime import datetime, time, timedelta
import pytz
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    PicklePersistence,
)

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = {527164608}
DATA_FILE = "daily_words.json"
TEHRAN = pytz.timezone("Asia/Tehran")

# ===== DATA STORAGE =====
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
else:
    data = {
        "topics": {},         # topic: [words]
        "subscriptions": {},  # user_id: {"time": "HH:MM", "topics": []}
    }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ===== HELPERS =====
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in ADMIN_USER_IDS:
            await update.message.reply_text("You are not allowed to use this command.")
            return
        return await func(update, context)
    return wrapper

def get_next_delivery_time(user_time: str):
    """Return a datetime object for the next delivery based on HH:MM string."""
    now = datetime.now(TEHRAN)
    hour, minute = map(int, user_time.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target < now:
        target += timedelta(days=1)
    return target

async def send_word(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Send a random word to a user based on subscription."""
    sub = data["subscriptions"].get(str(user_id))
    if not sub:
        return
    topics = sub.get("topics")
    all_words = []
    if topics:
        for topic in topics:
            all_words.extend(data["topics"].get(topic, []))
    else:
        for words in data["topics"].values():
            all_words.extend(words)
    if not all_words:
        await context.bot.send_message(chat_id=user_id, text="No words available yet.")
        return
    word = random.choice(all_words)
    await context.bot.send_message(chat_id=user_id, text=f"📌 Today's word: {word}")
    print(f"Sent word '{word}' to {user_id}")

async def schedule_daily_words(context: ContextTypes.DEFAULT_TYPE):
    """Check subscriptions and send words at the right time."""
    now = datetime.now(TEHRAN)
    for user_id, sub in data["subscriptions"].items():
        user_time = sub.get("time", "08:00")
        target = get_next_delivery_time(user_time)
        delta = (target - now).total_seconds()
        if 0 <= delta < 60:  # within current minute
            await send_word(int(user_id), context)

# ===== ADMIN COMMANDS =====
@admin_only
async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addword <topic> <word>")
        return
    topic = context.args[0]
    word = " ".join(context.args[1:])
    data["topics"].setdefault(topic, []).append(word)
    save_data()
    await update.message.reply_text(f"Added word '{word}' to topic '{topic}'.")

@admin_only
async def addwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /addwords <topic> (reply with words in new lines)")
        return
    topic = context.args[0]
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("Reply to a message containing words (one per line).")
        return
    words = update.message.reply_to_message.text.splitlines()
    data["topics"].setdefault(topic, []).extend(words)
    save_data()
    await update.message.reply_text(f"Added {len(words)} words to topic '{topic}'.")

@admin_only
async def listtopics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not data["topics"]:
        await update.message.reply_text("No topics added yet.")
        return
    topics = "\n".join(data["topics"].keys())
    await update.message.reply_text(f"Topics:\n{topics}")

@admin_only
async def listwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /listwords <topic>")
        return
    topic = context.args[0]
    words = data["topics"].get(topic)
    if not words:
        await update.message.reply_text(f"No words in topic '{topic}'")
        return
    await update.message.reply_text(f"Words in '{topic}':\n" + "\n".join(words))

# ===== STUDENT COMMANDS =====
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data["subscriptions"].setdefault(user_id, {"time": "08:00", "topics": []})
    save_data()
    await update.message.reply_text("Subscribed to daily words! Use /settime HH:MM to change delivery time.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in data["subscriptions"]:
        del data["subscriptions"][user_id]
        save_data()
        await update.message.reply_text("Unsubscribed from daily words.")
    else:
        await update.message.reply_text("You were not subscribed.")

async def getword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    topic = context.args[0] if context.args else None
    all_words = []
    if topic:
        all_words.extend(data["topics"].get(topic, []))
    else:
        for words in data["topics"].values():
            all_words.extend(words)
    if not all_words:
        await update.message.reply_text("No words available yet.")
        return
    word = random.choice(all_words)
    await update.message.reply_text(f"📌 Word: {word}")

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not ":" in context.args[0]:
        await update.message.reply_text("Usage: /settime HH:MM")
        return
    user_id = str(update.effective_user.id)
    time_str = context.args[0]
    if user_id not in data["subscriptions"]:
        data["subscriptions"][user_id] = {"time": time_str, "topics": []}
    else:
        data["subscriptions"][user_id]["time"] = time_str
    save_data()
    await update.message.reply_text(f"Daily word delivery time set to {time_str}.")

# ===== APPLICATION =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# ---- ADMIN ----
app.add_handler(CommandHandler("addword", addword))
app.add_handler(CommandHandler("addwords", addwords))
app.add_handler(CommandHandler("listtopics", listtopics))
app.add_handler(CommandHandler("listwords", listwords))

# ---- STUDENT ----
app.add_handler(CommandHandler("subscribe", subscribe))
app.add_handler(CommandHandler("unsubscribe", unsubscribe))
app.add_handler(CommandHandler("getword", getword))
app.add_handler(CommandHandler("settime", settime))

# ---- JOBS: Check every minute ----
from telegram.ext import IntervalJob
app.job_queue.run_repeating(schedule_daily_words, interval=60, first=0)

print("Daily Word Bot is running...")
app.run_polling()
