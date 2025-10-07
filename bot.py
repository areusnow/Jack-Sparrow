import os
import logging
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from flask import Flask
from threading import Thread
import asyncio
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = os.environ.get('API_ID')  # Get from my.telegram.org
API_HASH = os.environ.get('API_HASH')  # Get from my.telegram.org
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME')  # @channelname or channel ID
PORT = int(os.environ.get('PORT', 8080))

# Validate
if not all([API_ID, API_HASH, BOT_TOKEN, CHANNEL_USERNAME]):
    logger.error("Missing environment variables!")
    logger.error("Required: API_ID, API_HASH, BOT_TOKEN, CHANNEL_USERNAME")
    exit(1)

logger.info("="*50)
logger.info(f"API ID: {API_ID}")
logger.info(f"Bot Token: {BOT_TOKEN[:20]}...")
logger.info(f"Channel: {CHANNEL_USERNAME}")
logger.info("="*50)

# Movie database - stores indexed movies
movies_db = {}  # {msg_id: {title, text, keywords, date, media_type}}
indexing_in_progress = False
last_indexed = None

# Flask for health checks
app = Flask(__name__)

@app.route('/')
def home():
    status = "Indexing..." if indexing_in_progress else "Ready"
    return f'''
    <h1>🎬 Movie Bot v4.0 (Pyrogram)</h1>
    <p>Status: {status}</p>
    <p>Total Movies: {len(movies_db)}</p>
    <p>Last Indexed: {last_indexed or "Never"}</p>
    <p>Channel: {CHANNEL_USERNAME}</p>
    ''', 200

@app.route('/health')
def health():
    return 'OK', 200

# Initialize Pyrogram client
bot = Client(
    "movie_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Helper functions
def clean_text(text):
    """Clean text for processing"""
    if not text:
        return ""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_movie_title(text, caption=None):
    """Extract movie title intelligently"""
    content = text or caption or ""
    if not content:
        return "Unknown Movie"
    
    lines = content.split('\n')
    
    # Try first non-empty line
    for line in lines[:3]:  # Check first 3 lines
        line = clean_text(line)
        # Remove emojis and special chars
        line = re.sub(r'[^\w\s\-:().]', '', line)
        if len(line) > 3 and not line.lower().startswith(('http', 'www', 'join', 'channel')):
            return line[:80]  # Max 80 chars
    
    return clean_text(content[:80])

def extract_keywords(text):
    """Extract searchable keywords"""
    if not text:
        return set()
    
    text = text.lower()
    # Remove URLs
    text = re.sub(r'http\S+', '', text)
    # Keep only alphanumeric
    text = re.sub(r'[^\w\s]', ' ', text)
    
    words = text.split()
    
    # Stop words
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
        'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have',
        'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
        'might', 'must', 'can', 'movie', 'film', 'watch', 'download', 'free', 'full',
        'hd', 'quality', 'link', 'join', 'channel', 'telegram', 'group', 'size', 'mb', 'gb'
    }
    
    keywords = {w for w in words if len(w) > 2 and w not in stop_words}
    return keywords

def calculate_match_score(query, movie_data):
    """Calculate relevance score"""
    score = 0
    query = query.lower().strip()
    query_words = set(query.split())
    
    title = movie_data.get('title', '').lower()
    keywords = movie_data.get('keywords', set())
    text = movie_data.get('text', '').lower()
    
    # Exact title match
    if query == title:
        return 10000
    
    # Query in title
    if query in title:
        score += 5000
    
    # Title starts with query
    if title.startswith(query):
        score += 3000
    
    # Word matches in title
    title_words = set(title.split())
    title_matches = len(query_words & title_words)
    score += title_matches * 1000
    
    # Keyword matches
    keyword_matches = len(query_words & keywords)
    score += keyword_matches * 500
    
    # Query in full text
    if query in text:
        score += 100
    
    # Bonus for video/document
    if movie_data.get('media_type') in ['video', 'document']:
        score += 50
    
    return score

async def index_channel():
    """Index all messages from channel - FAST with Pyrogram"""
    global movies_db, indexing_in_progress, last_indexed
    
    indexing_in_progress = True
    logger.info("🔄 Starting channel indexing...")
    
    try:
        indexed = 0
        start_time = time.time()
        
        # Pyrogram allows us to iterate through messages directly!
        async for message in bot.get_chat_history(CHANNEL_USERNAME, limit=1000):
            try:
                # Get message content
                text = message.text or message.caption or ""
                
                if not text and not (message.video or message.document):
                    continue  # Skip empty messages without media
                
                # Extract info
                title = extract_movie_title(message.text, message.caption)
                keywords = extract_keywords(text)
                
                # Determine media type
                media_type = None
                if message.video:
                    media_type = 'video'
                elif message.document:
                    media_type = 'document'
                elif message.photo:
                    media_type = 'photo'
                
                # Store in database
                movies_db[message.id] = {
                    'id': message.id,
                    'title': title,
                    'text': text[:500],  # Store first 500 chars
                    'keywords': keywords,
                    'media_type': media_type,
                    'date': message.date.strftime('%Y-%m-%d') if message.date else None
                }
                
                indexed += 1
                
                if indexed % 100 == 0:
                    logger.info(f"Indexed {indexed} messages...")
                
            except Exception as e:
                logger.debug(f"Error indexing message: {e}")
                continue
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Indexing complete: {indexed} movies in {elapsed:.2f}s")
        last_indexed = time.strftime('%Y-%m-%d %H:%M:%S')
        
    except FloodWait as e:
        logger.warning(f"FloodWait: sleeping for {e.value}s")
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"Indexing error: {e}")
    finally:
        indexing_in_progress = False

# Bot command handlers
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    """Welcome message"""
    logger.info(f"START from {message.from_user.id}")
    
    welcome = (
        "🎬 **Movie Bot v4.0 - Lightning Fast!**\n\n"
        "Just type a movie name to search!\n\n"
        "**Commands:**\n"
        "• /search <name> - Search movies\n"
        "• /latest - Latest 10 movies\n"
        "• /stats - Statistics\n"
        "• /index - Rebuild index\n"
        "• /help - This message\n\n"
        "**Examples:**\n"
        "`Avengers`\n"
        "`Kantara`\n"
        "`Iron Man`"
    )
    await message.reply_text(welcome)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    """Help message"""
    await start_command(client, message)

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client, message: Message):
    """Show statistics"""
    status = "🔄 Indexing..." if indexing_in_progress else "✅ Ready"
    
    stats = (
        f"📊 **Bot Statistics**\n\n"
        f"Status: {status}\n"
        f"Indexed Movies: **{len(movies_db)}**\n"
        f"Last Indexed: {last_indexed or 'Never'}\n"
        f"Channel: `{CHANNEL_USERNAME}`"
    )
    await message.reply_text(stats)

@bot.on_message(filters.command("index") & filters.private)
async def index_command(client, message: Message):
    """Manually trigger indexing"""
    if indexing_in_progress:
        await message.reply_text("⏳ Indexing already in progress...")
        return
    
    status_msg = await message.reply_text("🔄 Starting indexing...")
    await index_channel()
    await status_msg.edit_text(f"✅ Indexed {len(movies_db)} movies!")

@bot.on_message(filters.command("search") & filters.private)
async def search_command(client, message: Message):
    """Search for movies"""
    # Get query from command
    query = message.text.split(maxsplit=1)
    if len(query) < 2:
        await message.reply_text("❌ Please provide a movie name!\n\nExample: `/search Avengers`")
        return
    
    query = query[1].strip()
    await perform_search(client, message, query)

@bot.on_message(filters.command("latest") & filters.private)
async def latest_command(client, message: Message):
    """Get latest movies"""
    logger.info(f"LATEST from {message.from_user.id}")
    
    status_msg = await message.reply_text("📥 Fetching latest movies...")
    
    try:
        # Get latest messages directly from channel
        count = 0
        async for msg in bot.get_chat_history(CHANNEL_USERNAME, limit=10):
            try:
                # Forward to user
                await msg.forward(message.chat.id)
                count += 1
            except Exception as e:
                logger.debug(f"Could not forward: {e}")
                continue
        
        await status_msg.delete()
        
        if count > 0:
            await message.reply_text(f"✅ Sent {count} latest movies")
        else:
            await message.reply_text("❌ No movies found")
            
    except Exception as e:
        logger.error(f"Latest error: {e}")
        await message.reply_text("❌ Error fetching movies")

@bot.on_message(filters.text & filters.private & ~filters.command(""))
async def handle_text(client, message: Message):
    """Handle plain text as search query"""
    query = message.text.strip()
    logger.info(f"TEXT from {message.from_user.id}: {query}")
    await perform_search(client, message, query)

async def perform_search(client, message: Message, query: str):
    """Perform fast search using indexed data"""
    logger.info(f"SEARCH: '{query}' by {message.from_user.id}")
    
    if not movies_db:
        await message.reply_text("⏳ Database is empty. Running /index first...")
        await index_channel()
        if not movies_db:
            await message.reply_text("❌ No movies found in channel")
            return
    
    search_msg = await message.reply_text(f"🔍 Searching for '**{query}**'...")
    
    try:
        # Search through indexed database
        results = []
        
        for msg_id, movie_data in movies_db.items():
            score = calculate_match_score(query, movie_data)
            if score > 0:
                results.append({
                    'msg_id': msg_id,
                    'title': movie_data['title'],
                    'score': score
                })
        
        # Sort by relevance
        results.sort(key=lambda x: x['score'], reverse=True)
        
        # Take top 5
        top_results = results[:5]
        
        await search_msg.delete()
        
        if top_results:
            # Show results summary
            summary = f"✅ **Found {len(top_results)} result(s):**\n\n"
            for i, r in enumerate(top_results, 1):
                summary += f"{i}. {r['title']}\n"
            
            await message.reply_text(summary)
            
            # Forward the actual messages
            for result in top_results:
                try:
                    # Forward from channel to user
                    await bot.forward_messages(
                        chat_id=message.chat.id,
                        from_chat_id=CHANNEL_USERNAME,
                        message_ids=result['msg_id']
                    )
                    await asyncio.sleep(0.5)  # Small delay to avoid flood
                except Exception as e:
                    logger.error(f"Error forwarding {result['msg_id']}: {e}")
        else:
            await message.reply_text(
                f"❌ No results for '**{query}**'\n\n"
                "Try:\n"
                "• Different keywords\n"
                "• Shorter search terms\n"
                "• /latest for recent movies"
            )
            
    except Exception as e:
        logger.error(f"Search error: {e}")
        await message.reply_text("❌ Search error occurred")

def run_flask():
    """Run Flask server"""
    try:
        logger.info(f"🌐 Starting Flask on port {PORT}...")
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask error: {e}")

async def startup():
    """Bot startup tasks"""
    logger.info("🤖 Bot started successfully!")
    logger.info("🔄 Starting initial indexing...")
    await index_channel()
    logger.info("✅ Bot ready to serve!")

if __name__ == '__main__':
    logger.info("🎬 Starting Movie Bot v4.0 (Pyrogram)...")
    
    # Start Flask in background
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start bot
    logger.info("🚀 Starting Pyrogram bot...")
    
    # Run startup tasks and then start bot
    bot.start()
    
    # Run indexing on startup
    loop = asyncio.get_event_loop()
    loop.run_until_complete(startup())
    
    # Keep bot running
    from pyrogram import idle
    idle()
    
    bot.stop()
