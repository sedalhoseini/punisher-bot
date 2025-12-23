from telegram.ext import ApplicationBuilder, CommandHandler

BOT_TOKEN = "8537616205:AAHQLsfnbQa-PqxmgouwUWMl4eGKw3LvWKY"

async def start(update, context):
    print(f"Received /start from {update.effective_user.id}")
    await update.message.reply_text("Bot is alive!")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
print("Polling bot starting...")
app.run_polling()
