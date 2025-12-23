from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import os

BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is alive! ✅")
    print(f"/start called by {update.effective_user.id}")

async def debug_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Message received from {update.effective_user.id}: {update.message.text}")
    await update.message.reply_text(f"Received: {update.message.text}")

# Build application
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_echo))

print("Debug bot running...")
app.run_polling()
