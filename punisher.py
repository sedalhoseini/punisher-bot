from telegram.ext import ApplicationBuilder, CommandHandler

BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

async def start(update, context):
    await update.message.reply_text("Bot is alive!")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.run_polling()
