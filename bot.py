import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask
from threading import Thread

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

# Validate environment variables
if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set!")
    exit(1)
if not CHANNEL_ID:
    logger.error("CHANNEL_ID is not set!")
    exit(1)

logger.info("="*50)
logger.info(f"Bot Token: {BOT_TOKEN[:20]}...")
logger.info(f"Channel ID: {CHANNEL_ID}")
logger.info(f"Port: {PORT}")
logger.info("="*50)

# Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return 'Movie Bot is running! 🎬', 200

@app.route('/health')
def health():
    return 'OK', 200

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    logger.info(f"START command from user {update.effective_user.id}")
    welcome_text = (
        "🎬 *Welcome to Movie Bot!*\n\n"
        "*Commands:*\n"
        "• /search <movie\\_name> - Search for movies\n"
        "• /latest - Get latest movies\n"
        "• /test - Test bot\n"
        "• /help - Show this message\n\n"
        "Or just type any movie name to search!"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot is working"""
    logger.info(f"TEST command from user {update.effective_user.id}")
    await update.message.reply_text(
        f"✅ Bot is working!\n\n"
        f"Your ID: {update.effective_user.id}\n"
        f"Channel ID: {CHANNEL_ID}\n"
        f"Bot Token: Set ✓"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    await start(update, context)

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for movies"""
    if not context.args:
        await update.message.reply_text("❌ Please provide a movie name!\n\nUsage: /search Avengers")
        return
    
    query = ' '.join(context.args).lower()
    logger.info(f"SEARCH: '{query}' by user {update.effective_user.id}")
    
    await update.message.reply_text(f"🔍 Searching for '{query}'...")
    
    try:
        found = []
        
        # Try forwarding messages 1-50
        for msg_id in range(1, 51):
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                found.append(msg_id)
                logger.info(f"Forwarded message {msg_id}")
                
                if len(found) >= 3:  # Limit to 3 results for testing
                    break
            except Exception as e:
                logger.debug(f"Message {msg_id} failed: {e}")
                continue
        
        if found:
            await update.message.reply_text(f"✅ Found {len(found)} result(s)")
        else:
            await update.message.reply_text(
                "❌ No movies found\n\n"
                "Possible issues:\n"
                "• Bot is not admin in channel\n"
                "• Channel ID is wrong\n"
                "• No messages in channel"
            )
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def get_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get latest movies"""
    logger.info(f"LATEST command from user {update.effective_user.id}")
    await update.message.reply_text("📥 Fetching latest movies...")
    
    try:
        count = 0
        for msg_id in range(1, 10):
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                count += 1
                if count >= 3:
                    break
            except Exception:
                continue
        
        if count > 0:
            await update.message.reply_text(f"✅ Showing {count} movies")
        else:
            await update.message.reply_text("❌ Could not fetch movies")
    except Exception as e:
        logger.error(f"Latest error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    text = update.message.text
    logger.info(f"MESSAGE from {update.effective_user.id}: {text}")
    
    if text and not text.startswith('/'):
        await update.message.reply_text(f"Searching for: {text}")
        context.args = text.split()
        await search_movies(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"ERROR: {context.error}", exc_info=context.error)

def run_bot():
    """Run the Telegram bot"""
    try:
        logger.info("🤖 Initializing bot...")
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("test", test_command))
        application.add_handler(CommandHandler("search", search_movies))
        application.add_handler(CommandHandler("latest", get_latest))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_error_handler(error_handler)
        
        logger.info("✅ Bot handlers registered")
        logger.info("🚀 Starting polling...")
        
        # Start polling
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}", exc_info=True)

def run_flask():
    """Run Flask server"""
    try:
        logger.info(f"🌐 Starting Flask on port {PORT}...")
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask error: {e}")

if __name__ == '__main__':
    logger.info("🎬 Starting Movie Bot...")
    
    # Start Flask in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run bot in main thread
    run_bot()
