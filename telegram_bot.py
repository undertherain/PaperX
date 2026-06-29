import asyncio
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
    DriverCallPlan,
    RedeliveryPlan,
    book_confirmed_redelivery,
    call_confirmed_driver,
    format_agent_trace,
    format_driver_call_outcome,
    format_driver_call_confirmation,
    format_driver_call_trace,
    format_plan_confirmation,
    get_driver_call_status,
    plan_driver_call,
    plan_redelivery,
    summarize_driver_call_outcome,
)

load_dotenv()

WAITING_FOR_ACTION = 1
WAITING_FOR_TIME = 2
WAITING_FOR_CONFIRMATION = 3
WAITING_FOR_CALL_CONFIRMATION = 4

YES_ANSWERS = {"yes", "y", "ok", "confirm", "book", "call", "はい", "お願いします"}

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
    
    await update.message.reply_text(
        "Got it. Should I fill the redelivery form for tomorrow, or call the driver for today?\n"
        "Reply: form or call"
    )
    return WAITING_FOR_ACTION

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = update.message.text.strip().lower()
    if action in {"form", "book", "tomorrow", "website", "web", "フォーム", "明日"}:
        await update.message.reply_text("What time tomorrow should I book? (e.g., 'around six pm')")
        return WAITING_FOR_TIME
    if action in {"call", "driver", "today", "phone", "電話", "今日"}:
        photo_path = context.user_data.get('photo_path', 'slip.jpg')
        await update.message.reply_text("Starting the driver-call agent...")

        async def progress(message: str) -> None:
            await update.message.reply_text(message)

        try:
            plan = await plan_driver_call(photo_path, progress=progress)
            context.user_data['driver_call_plan'] = plan.model_dump()
            await update.message.reply_text(format_driver_call_confirmation(plan))
            return WAITING_FOR_CALL_CONFIRMATION
        except Exception as e:
            await update.message.reply_text(f"Driver call setup failed:\n{e}")
            return ConversationHandler.END

    await update.message.reply_text("Please reply with form or call.")
    return WAITING_FOR_ACTION

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
    if answer not in YES_ANSWERS:
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

async def handle_call_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().lower()
    if answer not in YES_ANSWERS:
        await update.message.reply_text("Canceled. No call was made.")
        return ConversationHandler.END

    plan_payload = context.user_data.get('driver_call_plan')
    if not plan_payload:
        await update.message.reply_text("I lost the call plan. Please send the slip again.")
        return ConversationHandler.END

    plan = DriverCallPlan.model_validate(plan_payload)

    async def progress(message: str) -> None:
        await update.message.reply_text(message)

    try:
        result = await call_confirmed_driver(plan, progress=progress)
        if result.success:
            await update.message.reply_text(
                f"Call started.\nSID: {result.call_sid}\nStatus: {result.status or 'created'}"
            )
            await update.message.reply_text(format_driver_call_trace(plan, result))
            if result.call_sid:
                context.application.create_task(
                    watch_driver_call(
                        context,
                        update.effective_chat.id,
                        result.call_sid,
                    )
                )
        else:
            await update.message.reply_text(f"Driver call failed:\n{result.error}")
    except Exception as e:
        await update.message.reply_text(f"Driver call failed:\n{e}")

    return ConversationHandler.END

async def watch_driver_call(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    call_sid: str,
) -> None:
    terminal_statuses = {"completed", "disconnected", "error", "busy", "failed", "no-answer", "canceled"}
    await context.application.bot.send_message(chat_id=chat_id, text="Watching the call transcript...")

    last_record = None
    for _ in range(24):
        await asyncio.sleep(5)
        try:
            record = await asyncio.to_thread(get_driver_call_status, call_sid)
        except Exception as exc:
            await context.application.bot.send_message(
                chat_id=chat_id,
                text=f"Could not fetch call transcript yet:\n{exc}",
            )
            return

        last_record = record
        status = str(record.get("status") or "")
        if status in terminal_statuses:
            outcome = summarize_driver_call_outcome(record)
            await context.application.bot.send_message(
                chat_id=chat_id,
                text=format_driver_call_outcome(outcome),
            )
            return

    if last_record is not None:
        outcome = summarize_driver_call_outcome(last_record)
        await context.application.bot.send_message(
            chat_id=chat_id,
            text="Call is still in progress or transcript is delayed.\n\n" + format_driver_call_outcome(outcome),
        )

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
            WAITING_FOR_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_action)],
            WAITING_FOR_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time)],
            WAITING_FOR_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirmation)],
            WAITING_FOR_CALL_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_call_confirmation)
            ],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    
    print("Bot is ready and listening for messages!")
    app.run_polling()

if __name__ == '__main__':
    main()
