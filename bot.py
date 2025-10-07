import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask
from threading import Thread
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID')
PORT = int(os.environ.get('PORT', 8080))

# Flask app for health checks
app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!', 200

@app.route('/health')
def health():
    return 'OK', 200

def run_flask():
    """Run Flask in a separate thread"""
    app.run(host='0.0.0.0', port=PORT, debug=False)

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    welcome_text = (
        "🎬 Welcome to Movie Bot!\n\n"
        "Commands:\n"
        "/search <movie_name> - Search for movies\n"
        "/latest - Get latest movies\n"
        "/help - Show this message\n\n"
        "Or just type any movie name to search!"
    )
    await update.message.reply_text(welcome_text)
    logger.info(f"User {update.effective_user.id} started the bot")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    await start(update, context)

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for movies in the channel"""
    if not context.args:
        await update.message.reply_text("Please provide a movie name.\nUsage: /search <movie_name>")
        return
    
    query = ' '.join(context.args).lower()
    logger.info(f"Searching for: {query}")
    await update.message.reply_text(f"🔍 Searching for '{query}'...")
    
    try:
        found_messages = []
        
        # Try to forward messages from channel (checking existence)
        for msg_id in range(1, 100):  # Check last 100 messages
            try:
                # Try to copy message to check if it exists and matches
                msg = await context.bot.copy_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                
                # Get the copied message
                copied = await context.bot.get_messages(update.effective_chat.id, msg.message_id)
                
                # Check if query matches
                text_to_search = ""
                if copied.text:
                    text_to_search = copied.text.lower()
                elif copied.caption:
                    text_to_search = copied.caption.lower()
                
                # Delete the test copy
                await context.bot.delete_message(update.effective_chat.id, msg.message_id)
                
                if query in text_to_search:
                    found_messages.append(msg_id)
                    if len(found_messages) >= 5:
                        break
                        
            except Exception:
                continue
        
        # Forward the found messages
        if found_messages:
            await update.message.reply_text(f"✅ Found {len(found_messages)} result(s):")
            for msg_id in found_messages:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
        else:
            await update.message.reply_text(f"❌ No movies found matching '{query}'")
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}\n\nMake sure bot is admin in channel!")

async def get_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get latest movies from channel"""
    await update.message.reply_text("📥 Fetching latest movies...")
    logger.info("Fetching latest movies")
    
    try:
        count = 0
        # Get last 5 messages
        for msg_id in range(1, 20):
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                count += 1
                if count >= 5:
                    break
            except Exception:
                continue
        
        if count > 0:
            await update.message.reply_text(f"✅ Showing {count} latest movies")
        else:
            await update.message.reply_text("❌ Could not fetch movies. Check bot permissions!")
    
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages"""
    text = update.message.text
    logger.info(f"Message from {update.effective_user.id}: {text}")
    
    if text and not text.startswith('/'):
        context.args = text.split()
        await search_movies(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Error: {context.error}")

def main():
    """Main function"""
    logger.info("Starting bot...")
    logger.info(f"Bot Token: {BOT_TOKEN[:10]}...")
    logger.info(f"Channel ID: {CHANNEL_ID}")
    
    # Start Flask in background
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask started on port {PORT}")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_movies))
    application.add_handler(CommandHandler("latest", get_latest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # Start bot with polling
    logger.info("Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
