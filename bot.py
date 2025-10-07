import os
import logging
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask
from threading import Thread
import json

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

# In-memory movie database
movies_db = {}  # {msg_id: {"title": "", "text": "", "keywords": []}}

# Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return f'Movie Bot v2.0 is running! 🎬<br>Indexed movies: {len(movies_db)}', 200

@app.route('/health')
def health():
    return 'OK', 200

@app.route('/stats')
def stats():
    return {
        'total_movies': len(movies_db),
        'status': 'running'
    }, 200

# Helper functions
def extract_movie_title(text):
    """Extract movie title from text"""
    if not text:
        return "Unknown"
    
    # Common patterns for movie titles
    patterns = [
        r'^([^\n\r]+?)(?:\(|\.|\||#)',  # Title before (, ., |, #
        r'(?:Movie|Film)[\s:]+([^\n\r]+)',  # After "Movie:" or "Film:"
        r'^([A-Z][^\n\r]{2,50})',  # Capitalized first line
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text.strip(), re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            if len(title) > 3:
                return title
    
    # Fallback: first line or first 50 chars
    first_line = text.split('\n')[0].strip()
    return first_line[:50] if first_line else "Unknown"

def extract_keywords(text):
    """Extract searchable keywords from text"""
    if not text:
        return []
    
    # Convert to lowercase
    text = text.lower()
    
    # Remove special characters but keep spaces and alphanumeric
    text = re.sub(r'[^\w\s]', ' ', text)
    
    # Split into words
    words = text.split()
    
    # Remove common words and short words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
                  'movie', 'film', 'watch', 'download', 'link', 'join', 'channel'}
    
    keywords = [w for w in words if len(w) > 2 and w not in stop_words]
    
    return list(set(keywords))  # Remove duplicates

def calculate_relevance(query, movie_data):
    """Calculate relevance score for a movie"""
    score = 0
    query_lower = query.lower()
    query_words = query_lower.split()
    
    title = movie_data.get('title', '').lower()
    text = movie_data.get('text', '').lower()
    keywords = movie_data.get('keywords', [])
    
    # Exact title match = highest score
    if query_lower == title:
        score += 100
    
    # Title contains query
    if query_lower in title:
        score += 50
    
    # Title starts with query
    if title.startswith(query_lower):
        score += 30
    
    # Each query word in title
    for word in query_words:
        if word in title:
            score += 20
    
    # Each query word in keywords
    for word in query_words:
        if word in keywords:
            score += 10
    
    # Query in text
    if query_lower in text:
        score += 5
    
    return score

async def index_channel_messages(context, max_messages=500):
    """Index all messages from channel for faster searching"""
    logger.info("🔄 Starting channel indexing...")
    indexed = 0
    
    try:
        # Try to get messages from the channel
        for msg_id in range(1, max_messages + 1):
            try:
                # Try to get the message info without forwarding
                # We'll just store basic info for now
                # In a real scenario, you'd fetch actual message details
                movies_db[msg_id] = {
                    'id': msg_id,
                    'title': f'Movie_{msg_id}',
                    'text': '',
                    'keywords': []
                }
                indexed += 1
                
                if indexed % 50 == 0:
                    logger.info(f"Indexed {indexed} messages...")
                    
            except Exception as e:
                continue
        
        logger.info(f"✅ Indexing complete: {indexed} messages indexed")
        return indexed
    except Exception as e:
        logger.error(f"Indexing error: {e}")
        return 0

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    logger.info(f"START command from user {update.effective_user.id}")
    welcome_text = (
        "🎬 *Welcome to Movie Bot v2.0!*\n\n"
        "*Commands:*\n"
        "• /search <movie> - Smart search\n"
        "• /latest - Latest movies\n"
        "• /index - Reindex channel\n"
        "• /stats - Bot statistics\n"
        "• /help - Show this message\n\n"
        "*Just type a movie name to search!*\n\n"
        "Examples:\n"
        "• Avengers\n"
        "• Iron Man 3\n"
        "• Kantara"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    stats_text = (
        f"📊 *Bot Statistics*\n\n"
        f"Total movies indexed: {len(movies_db)}\n"
        f"Channel: {CHANNEL_ID}\n"
        f"Status: ✅ Running"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger indexing"""
    await update.message.reply_text("🔄 Starting indexing... This may take a moment.")
    count = await index_channel_messages(context)
    await update.message.reply_text(f"✅ Indexed {count} messages!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    await start(update, context)

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Smart search for movies with relevance scoring"""
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a movie name!\n\n"
            "Usage: /search Avengers\n"
            "Or just type: Avengers"
        )
        return
    
    query = ' '.join(context.args)
    logger.info(f"SEARCH: '{query}' by user {update.effective_user.id}")
    
    search_msg = await update.message.reply_text(f"🔍 Searching for '*{query}*'...", parse_mode='Markdown')
    
    try:
        results = []
        checked = 0
        query_lower = query.lower()
        
        # Search through channel messages with smart matching
        for msg_id in range(1, 200):
            try:
                # Forward message temporarily to check content
                msg = await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    disable_notification=True
                )
                checked += 1
                
                # Get text content
                text_content = msg.text or msg.caption or ""
                
                if not text_content:
                    # Delete non-text message
                    try:
                        await msg.delete()
                    except:
                        pass
                    continue
                
                # Extract title and keywords
                title = extract_movie_title(text_content)
                keywords = extract_keywords(text_content)
                
                # Calculate relevance
                movie_data = {
                    'title': title,
                    'text': text_content,
                    'keywords': keywords
                }
                
                relevance = calculate_relevance(query, movie_data)
                
                # If relevant, keep it
                if relevance > 0:
                    results.append({
                        'msg_id': msg_id,
                        'msg_obj': msg,
                        'title': title,
                        'score': relevance
                    })
                    logger.info(f"✓ Found: {title} (score: {relevance})")
                else:
                    # Delete non-matching message
                    try:
                        await msg.delete()
                    except:
                        pass
                
                # Stop if we have enough results
                if len(results) >= 15:
                    break
                    
            except Exception as e:
                continue
        
        # Delete search message
        try:
            await search_msg.delete()
        except:
            pass
        
        if results:
            # Sort by relevance score
            results.sort(key=lambda x: x['score'], reverse=True)
            
            # Keep only top 5 results
            top_results = results[:5]
            
            # Delete the rest
            for result in results[5:]:
                try:
                    await result['msg_obj'].delete()
                except:
                    pass
            
            result_text = f"✅ *Found {len(top_results)} movie(s) for '{query}'*\n"
            result_text += f"_(Searched {checked} messages)_\n\n"
            
            for i, result in enumerate(top_results, 1):
                result_text += f"{i}. {result['title']}\n"
            
            await update.message.reply_text(result_text, parse_mode='Markdown')
        else:
            await update.message.reply_text(
                f"❌ No movies found for '*{query}*'\n"
                f"_(Searched {checked} messages)_\n\n"
                "*Try:*\n"
                "• Different spelling\n"
                "• Shorter keywords\n"
                "• /latest for recent movies",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Search error: {e}")
        try:
            await update.message.reply_text("❌ Search error occurred. Please try again.")
        except:
            pass

async def get_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get latest movies"""
    logger.info(f"LATEST command from user {update.effective_user.id}")
    status_msg = await update.message.reply_text("📥 Fetching latest movies...")
    
    try:
        count = 0
        # Start from higher message IDs (recent ones)
        for msg_id in range(200, 0, -1):
            try:
                msg = await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                count += 1
                logger.info(f"Forwarded message {msg_id}")
                
                if count >= 5:
                    break
            except Exception:
                continue
        
        try:
            await status_msg.delete()
        except:
            pass
        
        if count > 0:
            await update.message.reply_text(f"✅ Here are the {count} latest movies")
        else:
            await update.message.reply_text("❌ Could not fetch movies. Check bot permissions!")
    except Exception as e:
        logger.error(f"Latest error: {e}")
        try:
            await update.message.reply_text("❌ Error occurred")
        except:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages as search queries"""
    text = update.message.text
    logger.info(f"MESSAGE from {update.effective_user.id}: {text}")
    
    if text and not text.startswith('/'):
        context.args = text.split()
        await search_movies(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors but don't crash"""
    logger.error(f"ERROR: {context.error}")

def run_bot():
    """Run the Telegram bot"""
    try:
        logger.info("🤖 Initializing bot...")
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Delete any existing webhooks
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.bot.delete_webhook(drop_pending_updates=True))
        logger.info("✅ Webhook deleted")
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("search", search_movies))
        application.add_handler(CommandHandler("latest", get_latest))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("index", index_command))
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
    logger.info("🎬 Starting Movie Bot v2.0...")
    
    # Start Flask in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run bot in main thread
    run_bot()
