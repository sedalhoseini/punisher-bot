import asyncio
import json
import os
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
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {527164608}  # Add admin user IDs here
DATA_FILE = "daily_words.json"
TIMEZONE = pytz.timezone("Asia/Tehran")

# ===== STORAGE HELPERS =====
def load_data():
    if not os.path.exists(DATA_FILE):
        data = {"words": {}, "students": {}}
        save_data(data)
        return data
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ===== HELPERS =====
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("You are not allowed to use this command.")
            return
        return await func(update, context)
    return wrapper

def pick_word(words_dict, topic=None):
    if topic:
        return random.choice(words_dict.get(topic, [])) if words_dict.get(topic) else None
    all_words = [w for t in words_dict.values() for w in t]
    return random.choice(all_words) if all_words else None

# ===== DAILY WORD SENDER =====
async def daily_word_job(app):
    while True:
        now = datetime.now(TIMEZONE)
        data = load_data()
        for user_id, info in data["students"].items():
            try:
                sub_time = info.get("time", "09:00")
                hour, minute = map(int, sub_time.split(":"))
                send_time = dt_time(hour, minute)
                if now.time().hour == send_time.hour and now.time().minute == send_time.minute:
                    word = pick_word(data["words"], info.get("topic"))
                    if not word:
                        await app.bot.send_message(
                            chat_id=int(user_id),
                            text="No words available yet. Admin can add words using /addword."
                        )
                        continue
                    await app.bot.send_message(
                        chat_id=int(user_id),
                        text=f"Today's word: {word}"
                    )
            except Exception as e:
                await app.bot.send_message(chat_id=int(user_id), text=f"Error sending word: {e}")
        await asyncio.sleep(60)  # check every minute

# ===== COMMANDS =====
@admin_only
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if len(context.args) < 2:
        await msg.reply_text("Usage: /addword <topic> <word1,word2,...>")
        return
    topic = context.args[0]
    words = " ".join(context.args[1:]).split(",")
    data = load_data()
    if topic not in data["words"]:
        data["words"][topic] = []
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

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = str(msg.from_user.id)
    mode = "random"
    topic = None
    send_time = "09:00"
    if context.args:
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
    word = pick_word(data["words"], info.get("topic"))
    if not word:
        await msg.reply_text("No words available yet. Admin can add words using /addword.")
        return
    await msg.reply_text(f"Your word: {word}")

async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Debug: received command: {update.message.text}")

# ===== APPLICATION =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Admin commands
app.add_handler(CommandHandler("addword", add_word))
app.add_handler(CommandHandler("listtopics", list_topics))

# Student commands
app.add_handler(CommandHandler("subscribe", subscribe))
app.add_handler(CommandHandler("unsubscribe", unsubscribe))
app.add_handler(CommandHandler("getword", get_word))

# Debug (catch-all)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug))

# ===== MAIN =====
async def main():
    # Start daily word task
    asyncio.create_task(daily_word_job(app))
    print("Daily Word Bot running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
