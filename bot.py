import os
import logging
import asyncio
import qrcode
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, ConversationHandler
)

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8000))

# --- Conversation States ---
QR_WAITING = 1  # Waiting for link to convert to QR code

# --- Store sessions for each user ---
qr_sessions = {}

# --- Helper Function: Link to QR Code ---
def create_qr_code(link: str, output_path: str, box_size: int = 10, border: int = 4):
    """Creates a QR code image from a given link."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(link)
    qr.make(fit=True)
    
    # Create QR code image
    qr_image = qr.make_image(fill_color="black", back_color="white")
    qr_image.save(output_path)
    return output_path

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔗 *Link to QR Code Bot*\n\n"
        "Send me any link and I'll convert it to a QR code!\n\n"
        "Commands:\n"
        "/qr - Start QR code generation\n"
        "/cancel - Cancel current operation"
    )

async def qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    qr_sessions[user_id] = True
    await update.message.reply_text(
        "🔗 Please send me the link you want to convert to a QR code.\n"
        "Example: https://example.com\n"
        "Use /cancel to abort."
    )
    return QR_WAITING

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text.strip()
    
    # Basic URL validation
    if not (link.startswith("http://") or link.startswith("https://")):
        await update.message.reply_text(
            "⚠️ Please send a valid link starting with http:// or https://"
        )
        return QR_WAITING
    
    await update.message.reply_text("🔳 Generating your QR code...")
    qr_path = f"qr_code_{user_id}.png"
    
    try:
        create_qr_code(link, qr_path)
        
        with open(qr_path, 'rb') as img_file:
            await update.message.reply_photo(
                photo=img_file,
                caption=f"✅ Here's your QR code for:\n{link}"
            )
        
        if os.path.exists(qr_path):
            os.remove(qr_path)
            
    except Exception as e:
        logger.error(f"QR code generation error: {e}")
        await update.message.reply_text(f"❌ Error generating QR code: {str(e)}")
    
    # Clear session
    if user_id in qr_sessions:
        del qr_sessions[user_id]
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in qr_sessions:
        del qr_sessions[user_id]
    
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

# --- Webhook and Server Setup ---
async def main():
    # Create Telegram Bot Application
    app = Application.builder().token(TOKEN).updater(None).build()
    
    # QR code conversation handler
    qr_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("qr", qr_start)],
        states={
            QR_WAITING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(qr_conv_handler)
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Set webhook
    if RENDER_URL:
        webhook_path = "/telegram"
        await app.bot.set_webhook(url=f"{RENDER_URL}{webhook_path}")
        logger.info(f"✅ Webhook set to {RENDER_URL}{webhook_path}")
    else:
        logger.warning("⚠️ RENDER_EXTERNAL_URL not set.")

    # Create Starlette web server
    async def telegram_webhook(request: Request):
        try:
            data = await request.json()
            update = Update.de_json(data, app.bot)
            await app.update_queue.put(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            return Response(status_code=500)

    async def health_check(_: Request):
        return PlainTextResponse("OK")

    starlette_app = Starlette(routes=[
        Route("/telegram", telegram_webhook, methods=["POST"]),
        Route("/healthcheck", health_check, methods=["GET"]),
    ])

    # Run server
    logger.info(f"🚀 Starting web server on port {PORT}...")
    import uvicorn
    webserver = uvicorn.Server(
        uvicorn.Config(starlette_app, host="0.0.0.0", port=PORT, log_level="info")
    )
    
    async with app:
        await app.start()
        await webserver.serve()
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
