import asyncio
import os
import subprocess
import sys

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
from slip_recognition import DEFAULT_PHONE_NUMBER, SlipRecognition, recognize_slip
from time_slots import normalize_time_slot

load_dotenv()

WAITING_FOR_TIME = 1

def format_recognition(result: SlipRecognition) -> str:
    phone = result.phone_number or f"{DEFAULT_PHONE_NUMBER} (default)"
    return (
        f"tracking={result.tracking_number or 'not found'}, "
        f"phone={phone}, confidence={result.confidence:.2f}"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a photo of your redelivery slip.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the file from the last (highest resolution) photo
    photo_file = await update.message.photo[-1].get_file()
    
    # Download the photo
    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{photo_file.file_id}.jpg"
    await photo_file.download_to_drive(file_path)
    
    # Start recognition now so the user's time-slot reply hides most of the latency.
    context.user_data['photo_path'] = file_path
    context.user_data['recognition_task'] = asyncio.create_task(
        asyncio.to_thread(recognize_slip, file_path)
    )
    
    await update.message.reply_text("Got it! What time tomorrow should I book the redelivery for? (e.g., '19:00-21:00')")
    return WAITING_FOR_TIME

async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_slot = normalize_time_slot(update.message.text)
    photo_path = context.user_data.get('photo_path', 'slip.jpg')
    
    await update.message.reply_text(f"Booking redelivery for {time_slot}...")
    
    try:
        recognition_task = context.user_data.get('recognition_task')
        if recognition_task:
            recognition = await recognition_task
        else:
            recognition = await asyncio.to_thread(recognize_slip, photo_path)

        if not recognition.tracking_number:
            await update.message.reply_text(
                f"I could not confidently read the tracking number. Notes: {recognition.notes or 'none'}"
            )
            return ConversationHandler.END

        await update.message.reply_text(f"Slip read: {format_recognition(recognition)}")

        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "tools/playwright_booking.py",
                recognition.tracking_number,
                recognition.booking_phone_number,
                time_slot,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        await update.message.reply_text(f"Result:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"Booking automation failed:\n{e.stderr}")
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
        states={WAITING_FOR_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time)]},
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    
    print("Bot is ready and listening for messages!")
    app.run_polling()

if __name__ == '__main__':
    main()
