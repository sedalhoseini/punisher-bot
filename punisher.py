import json
import os
import random
import pytz
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # already set on VPS
ADMIN_IDS = {527164608}
DATA_FILE = "daily_words.json"
TIMEZONE = pytz.timezone("Asia/Tehran")

# ================= STORAGE =================
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

# ================= HELPERS =================
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("You are not allowed to use this command.")
            return
        return await func(update, context)
    return wrapper

def pick_word(words_dict, topic=None):
    if topic and topic in words_dict:
        return random.choice(words_dict[topic]) if words_dict[topic] else None
    all_words = [w for t in words_dict.values() for w in t]
    return random.choice(all_words) if all_words else None

# ================= DAILY JOB =================
async def daily_word_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    data = load_data()

    for user_id, info in data["students"].items():
        try:
            send_time = info.get("time", "09:00")
            hour, minute = map(int, send_time.split(":"))

            # send ONLY at exact minute
            if now.hour != hour or now.minute != minute:
                continue

            # prevent duplicate sends
            last_sent = info.get("last_sent")
            today = now.strftime("%Y-%m-%d")
            if last_sent == today:
                continue

            word = pick_word(data["words"], info.get("topic"))
            if not word:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text="No words available yet. Admin must add words."
                )
            else:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"📘 Today's word:\n{word}"
                )

            info["last_sent"] = today
            save_data(data)

        except Exception as e:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"Error sending daily word:\n{e}"
            )

# ================= COMMANDS =================
@admin_only
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage:\n/addword <topic> <word1,word2,...>")
        return

    topic = context.args[0]
    words = " ".join(context.args[1:]).split(",")

    data = load_data()
    data["words"].setdefault(topic, [])
    data["words"][topic].extend(w.strip() for w in words if w.strip())
    save_data(data)

    await update.message.reply_text(f"Words added to topic '{topic}'.")

@admin_only
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    topics = data["words"].keys()
    if not topics:
        await update.message.reply_text("No topics available.")
        return
    await update.message.reply_text("Available topics:\n" + "\n".join(topics))

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    topic = None
    send_time = "09:00"

    for arg in context.args:
        if arg.startswith("time="):
            send_time = arg.split("=", 1)[1]
        elif arg.startswith("topic="):
            topic = arg.split("=", 1)[1]

    data = load_data()
    data["students"][user_id] = {
        "topic": topic,
        "time": send_time,
        "last_sent": None
    }
    save_data(data)

    await update.message.reply_text(
        f"Subscribed.\nTime: {send_time}\nTopic: {topic or 'random'}"
    )

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()

    if user_id in data["students"]:
        del data["students"][user_id]
        save_data(data)
        await update.message.reply_text("You are unsubscribed.")
    else:
        await update.message.reply_text("You were not subscribed.")

async def get_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    info = data["students"].get(user_id, {})

    word = pick_word(data["words"], info.get("topic"))
    if not word:
        await update.message.reply_text("No words available.")
        return

    await update.message.reply_text(f"Your word:\n{word}")

async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Received:\n{update.message.text}")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Admin
    app.add_handler(CommandHandler("addword", add_word))
    app.add_handler(CommandHandler("listtopics", list_topics))

    # Users
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("getword", get_word))

    # Debug
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug))

    # Job every minute
    app.job_queue.run_repeating(daily_word_job, interval=60, first=10)

    print("Daily Word Bot is running.")
    app.run_polling()

if __name__ == "__main__":
    main()
