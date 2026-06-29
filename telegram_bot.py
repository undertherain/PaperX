import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from redelivery_agent import (
    RedeliveryPlan,
    book_confirmed_redelivery,
    format_agent_trace,
    format_plan_confirmation,
    plan_redelivery,
)

load_dotenv()

WAITING_FOR_TIME = 1
WAITING_FOR_CONFIRMATION = 2

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a photo of your redelivery slip.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the file from the last (highest resolution) photo
    photo_file = await update.message.photo[-1].get_file()
    
    # Download the photo
    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{photo_file.file_id}.jpg"
    await photo_file.download_to_drive(file_path)
    
    context.user_data['photo_path'] = file_path
    
    await update.message.reply_text("Got it! What time tomorrow should I book the redelivery for? (e.g., '19:00-21:00')")
    return WAITING_FOR_TIME

async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requested_time = update.message.text.strip()
    photo_path = context.user_data.get('photo_path', 'slip.jpg')

    await update.message.reply_text("Starting the redelivery agent...")
    
    try:
        async def progress(message: str) -> None:
            await update.message.reply_text(message)

        plan = await plan_redelivery(
            photo_path,
            requested_time,
            progress=progress,
        )
        context.user_data['booking_plan'] = plan.model_dump()
        await update.message.reply_text(format_plan_confirmation(plan))
        return WAITING_FOR_CONFIRMATION
    except Exception as e:
        await update.message.reply_text(f"Booking failed:\n{e}")
        
    return ConversationHandler.END

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().lower()
    if answer not in {"yes", "y", "ok", "confirm", "book", "はい", "お願いします"}:
        await update.message.reply_text("Canceled. No booking was made.")
        return ConversationHandler.END

    plan_payload = context.user_data.get('booking_plan')
    if not plan_payload:
        await update.message.reply_text("I lost the booking plan. Please send the slip again.")
        return ConversationHandler.END

    plan = RedeliveryPlan.model_validate(plan_payload)

    async def progress(message: str) -> None:
        await update.message.reply_text(message)

    try:
        result = await book_confirmed_redelivery(plan, progress=progress)
        if result.success:
            await update.message.reply_text(f"Result:\n{result.stdout}")
            await update.message.reply_text(format_agent_trace(plan, result))
        else:
            await update.message.reply_text(f"Booking automation failed:\n{result.stderr or result.stdout}")
    except Exception as e:
        await update.message.reply_text(f"Booking failed:\n{e}")

    return ConversationHandler.END

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        print("Error: TELEGRAM_TOKEN environment variable not set.")
        print("Usage: export TELEGRAM_TOKEN='your:token' && python telegram_bot.py")
        return

    print("Starting Telegram polling bot...")
    app = Application.builder().token(token).build()
    
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, handle_photo)],
        states={
            WAITING_FOR_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time)],
            WAITING_FOR_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirmation)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    
    print("Bot is ready and listening for messages!")
    app.run_polling()

if __name__ == '__main__':
    main()
