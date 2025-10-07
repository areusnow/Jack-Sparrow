import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from flask import Flask, request
import asyncio
from threading import Thread

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID')  # Format: @channelname or -100123456789
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')  # Your Render app URL
PORT = int(os.environ.get('PORT', 8080))

# Flask app for health checks
app = Flask(__name__)

# Store movie data (in production, use a database)
movies_cache = []

@app.route('/')
def home():
    return 'Bot is running!', 200

@app.route('/health')
def health():
    return 'OK', 200

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start is issued"""
    welcome_text = (
        "🎬 Welcome to Movie Bot!\n\n"
        "Commands:\n"
        "/search <movie_name> - Search for movies\n"
        "/latest - Get latest movies\n"
        "/help - Show this message"
    )
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    await start(update, context)

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for movies in the channel"""
    if not context.args:
        await update.message.reply_text("Please provide a movie name.\nUsage: /search <movie_name>")
        return
    
    query = ' '.join(context.args).lower()
    await update.message.reply_text(f"🔍 Searching for '{query}'...")
    
    try:
        # Search through channel messages
        results = []
        async for message in context.bot.get_chat(CHANNEL_ID).__aiter__():
            if message.text and query in message.text.lower():
                results.append(message)
            if len(results) >= 10:
                break
        
        if results:
            for msg in results:
                # Forward the movie message to user
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg.message_id
                )
        else:
            await update.message.reply_text(f"❌ No movies found matching '{query}'")
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("❌ Error searching movies. Make sure the bot is admin in the channel.")

async def get_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get latest movies from channel"""
    await update.message.reply_text("📥 Fetching latest movies...")
    
    try:
        # Get recent messages from channel
        messages = []
        count = 0
        
        async for message in context.bot.get_chat(CHANNEL_ID).__aiter__():
            if message.document or message.video:  # Filter for media files
                messages.append(message)
                count += 1
            if count >= 5:
                break
        
        if messages:
            await update.message.reply_text(f"🎬 Here are the {len(messages)} latest movies:")
            for msg in messages:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg.message_id
                )
        else:
            await update.message.reply_text("❌ No movies found in the channel")
    
    except Exception as e:
        logger.error(f"Latest movies error: {e}")
        await update.message.reply_text("❌ Error fetching movies. Make sure the bot is admin in the channel.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages"""
    text = update.message.text
    
    # Treat any text as a search query
    if text and not text.startswith('/'):
        context.args = text.split()
        await search_movies(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")

def run_flask():
    """Run Flask in a separate thread"""
    app.run(host='0.0.0.0', port=PORT)

async def main():
    """Main function to run the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_movies))
    application.add_handler(CommandHandler("latest", get_latest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # Start Flask in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start the bot with webhook
    await application.initialize()
    await application.start()
    
    if WEBHOOK_URL:
        # Use webhook for Render
        webhook_url = f"{WEBHOOK_URL}/webhook"
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
        
        # Keep the application running
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    else:
        # Use polling for local development
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    # Keep running
    await application.updater.idle()

if __name__ == '__main__':
    asyncio.run(main())
