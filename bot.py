import os
import logging
import re
import json
import asyncio
import time
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError
from flask import Flask
from threading import Thread
from waitress import serve

# ==============================
# 🔧 CONFIGURATION
# ==============================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME')
PORT = int(os.environ.get('PORT', 8080))

if not all([API_ID, API_HASH, BOT_TOKEN, CHANNEL_USERNAME]):
    logger.error("❌ Missing environment variables! Required: API_ID, API_HASH, BOT_TOKEN, CHANNEL_USERNAME")
    exit(1)

logger.info("="*50)
logger.info(f"API ID: {API_ID}")
logger.info(f"Bot Token: {BOT_TOKEN[:5]}***{BOT_TOKEN[-5:]}")
logger.info(f"Channel: {CHANNEL_USERNAME}")
logger.info("="*50)

# ==============================
# 💾 DATABASE
# ==============================

DB_FILE = "movies_db.json"
movies_db = {}
indexing_in_progress = False
last_indexed = None

def save_db():
    """Save movie database to disk"""
    try:
        serializable = {}
        for k, v in movies_db.items():
            entry = v.copy()
            entry["keywords"] = list(entry.get("keywords", []))
            serializable[str(k)] = entry
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Saved {len(movies_db)} movies to disk.")
    except Exception as e:
        logger.error(f"Save DB error: {e}")

def load_db():
    """Load movie database from disk"""
    global movies_db
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        movies_db = {}
        for k, v in data.items():
            v["keywords"] = set(v.get("keywords", []))
            movies_db[int(k)] = v
        logger.info(f"📁 Loaded {len(movies_db)} movies from disk.")
    except FileNotFoundError:
        movies_db = {}
        logger.info("No existing DB found — starting fresh.")

# ==============================
# 🌐 FLASK SERVER
# ==============================

app = Flask(__name__)

@app.route('/')
def home():
    status = "Indexing..." if indexing_in_progress else "Ready"
    return f'''
    <h1>🎬 Movie Bot v5.0 (Bot-Compatible)</h1>
    <p>Status: {status}</p>
    <p>Total Movies: {len(movies_db)}</p>
    <p>Last Indexed: {last_indexed or "Never"}</p>
    <p>Channel: {CHANNEL_USERNAME}</p>
    <p><small>Real-time indexing + Message ID scanning</small></p>
    ''', 200

@app.route('/health')
def health():
    return 'OK', 200

def run_flask():
    """Run Flask using Waitress"""
    try:
        logger.info(f"🌐 Starting Flask on port {PORT}...")
        serve(app, host='0.0.0.0', port=PORT)
    except Exception as e:
        logger.error(f"Flask error: {e}")

# ==============================
# 🤖 PYROGRAM BOT
# ==============================

bot = Client(
    "movie_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ==============================
# 🔍 HELPERS
# ==============================

def clean_text(text):
    return re.sub(r'\s+', ' ', text or "").strip()

def extract_movie_title(text, caption=None):
    content = text or caption or ""
    if not content:
        return "Unknown Movie"

    lines = content.split('\n')
    for line in lines[:3]:
        line = clean_text(line)
        line = re.sub(r'[^\w\s\-:().]', '', line)
        if len(line) > 3 and not line.lower().startswith(('http', 'www', 'join', 'channel')):
            return line[:80]
    return clean_text(content[:80])

def extract_keywords(text):
    if not text:
        return set()
    text = text.lower()
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
        'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have',
        'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
        'might', 'must', 'can', 'movie', 'film', 'watch', 'download', 'free', 'full',
        'hd', 'quality', 'link', 'join', 'channel', 'telegram', 'group', 'size', 'mb', 'gb'
    }
    return {w for w in words if len(w) > 2 and w not in stop_words}

def calculate_match_score(query, movie_data):
    score = 0
    query = query.lower().strip()
    query_words = set(query.split())
    title = movie_data.get('title', '').lower()
    keywords = movie_data.get('keywords', set())
    text = movie_data.get('text', '').lower()

    if query == title:
        return 10000
    if query in title:
        score += 5000
    if title.startswith(query):
        score += 3000
    title_matches = len(query_words & set(title.split()))
    score += title_matches * 1000
    keyword_matches = len(query_words & keywords)
    score += keyword_matches * 500
    if query in text:
        score += 100
    if movie_data.get('media_type') in ['video', 'document']:
        score += 50
    return score

def index_message(message):
    """Index a single message"""
    try:
        text = message.text or message.caption or ""
        if not text and not (message.video or message.document):
            return False

        title = extract_movie_title(message.text, message.caption)
        keywords = extract_keywords(text)
        media_type = None
        if message.video:
            media_type = 'video'
        elif message.document:
            media_type = 'document'
        elif message.photo:
            media_type = 'photo'

        movies_db[message.id] = {
            'id': message.id,
            'title': title,
            'text': text[:500],
            'keywords': keywords,
            'media_type': media_type,
            'date': message.date.strftime('%Y-%m-%d') if message.date else None
        }
        return True
    except Exception as e:
        logger.debug(f"Error indexing message {message.id}: {e}")
        return False

# ==============================
# ⚙️ AUTO-INDEXING NEW POSTS
# ==============================

@bot.on_message(filters.channel)
async def auto_index_channel_post(client, message: Message):
    """Automatically index new channel posts"""
    try:
        # Check if it's from our target channel
        if message.chat.username != CHANNEL_USERNAME.lstrip('@'):
            return
        
        if index_message(message):
            logger.info(f"✅ Auto-indexed: {message.id} - {movies_db[message.id]['title']}")
            # Auto-save every 10 new posts
            if len(movies_db) % 10 == 0:
                save_db()
    except Exception as e:
        logger.error(f"Auto-index error: {e}")

# ==============================
# ⚙️ MESSAGE ID SCANNING
# ==============================

async def scan_by_message_ids(start_id=1, end_id=1000, batch_size=50):
    """
    Scan messages by trying sequential message IDs
    This works because bots CAN forward messages if they know the ID
    """
    global indexing_in_progress, last_indexed
    indexing_in_progress = True
    logger.info(f"🔄 Scanning message IDs {start_id} to {end_id}...")

    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        indexed = 0
        start_time = time.time()
        
        for msg_id in range(start_id, end_id + 1):
            try:
                # Try to get the message by ID
                message = await bot.get_messages(chat.id, msg_id)
                
                if message and not message.empty:
                    if index_message(message):
                        indexed += 1
                        
                        if indexed % 50 == 0:
                            logger.info(f"✅ Scanned: {indexed} messages (currently at ID {msg_id})")
                            save_db()
                
                # Rate limiting
                if msg_id % batch_size == 0:
                    await asyncio.sleep(2)
                    
            except FloodWait as e:
                logger.warning(f"FloodWait: sleeping {e.value}s")
                await asyncio.sleep(e.value)
            except RPCError as e:
                # Message not found or deleted - skip silently
                pass
            except Exception as e:
                logger.debug(f"Error at ID {msg_id}: {e}")
                continue

        elapsed = time.time() - start_time
        last_indexed = time.strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"✅ Scan complete: {indexed} movies in {elapsed:.2f}s")
        save_db()
        return indexed

    except Exception as e:
        logger.error(f"Scanning error: {e}")
        return 0
    finally:
        indexing_in_progress = False

# ==============================
# 🧠 COMMANDS
# ==============================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    welcome = (
        "🎬 **Movie Bot v5.0 - Bot-Compatible!**\n\n"
        "Just type a movie name to search!\n\n"
        "**Commands:**\n"
        "• /search <name> - Search movies\n"
        "• /stats - Statistics\n"
        "• /index - Scan old messages (by ID)\n"
        "• /help - This message\n\n"
        "**Examples:**\n"
        "`Avengers`\n"
        "`Kantara`\n"
        "`Iron Man`\n\n"
        "**Note:** New posts are indexed automatically!\n"
        "Use /index to scan old messages (1-5000)."
    )
    await message.reply_text(welcome)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    await start_command(client, message)

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client, message: Message):
    status = "🔄 Indexing..." if indexing_in_progress else "✅ Ready"
    stats = (
        f"📊 **Bot Statistics**\n\n"
        f"Status: {status}\n"
        f"Indexed Movies: **{len(movies_db)}**\n"
        f"Last Indexed: {last_indexed or 'Never'}\n"
        f"Channel: `{CHANNEL_USERNAME}`\n\n"
        f"💡 **How it works:**\n"
        f"• New posts → Auto-indexed ✅\n"
        f"• Old posts → Use /index to scan\n"
        f"• No admin needed! 🎉"
    )
    await message.reply_text(stats)

@bot.on_message(filters.command("index") & filters.private)
async def index_command(client, message: Message):
    if indexing_in_progress:
        await message.reply_text("⏳ Indexing already in progress...")
        return
    
    # Parse custom range if provided
    parts = message.text.split()
    if len(parts) >= 3:
        try:
            start = int(parts[1])
            end = int(parts[2])
            status_msg = await message.reply_text(f"🔄 Scanning message IDs {start} to {end}...")
            count = await scan_by_message_ids(start, end)
            await status_msg.edit_text(f"✅ Scan complete! Found {count} movies.\nTotal in DB: {len(movies_db)}")
        except ValueError:
            await message.reply_text("❌ Invalid format! Use: `/index 1 1000`")
    else:
        # Default scan range
        status_msg = await message.reply_text("🔄 Scanning message IDs 1-5000...\n⏱️ This may take 3-5 minutes...")
        count = await scan_by_message_ids(1, 5000)
        await status_msg.edit_text(f"✅ Scan complete! Found {count} movies.\nTotal in DB: {len(movies_db)}")

@bot.on_message(filters.command("search") & filters.private)
async def search_command(client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("❌ Please provide a movie name!\n\nExample: `/search Avengers`")
        return
    await perform_search(client, message, parts[1].strip())

@bot.on_message(filters.text & filters.private & ~filters.regex(r'^/'))
async def handle_text(client, message: Message):
    await perform_search(client, message, message.text.strip())

# ==============================
# 🔎 SEARCH
# ==============================

async def perform_search(client, message: Message, query: str):
    if not movies_db:
        await message.reply_text(
            "⏳ **Database is empty!**\n\n"
            "**Options:**\n"
            "1. Use `/index` to scan old messages (IDs 1-5000)\n"
            "2. Wait for new posts (they auto-index)\n"
            "3. Use `/index 1 1000` for smaller range\n\n"
            "**No admin needed!** ✅"
        )
        return

    search_msg = await message.reply_text(f"🔍 Searching for '**{query}**'...")

    results = []
    query_lower = query.lower()

    for msg_id, movie_data in movies_db.items():
        score = calculate_match_score(query_lower, movie_data)
        if score > 0:
            results.append({'msg_id': msg_id, 'title': movie_data['title'], 'score': score})

    results.sort(key=lambda x: x['score'], reverse=True)
    await search_msg.delete()

    if not results:
        await message.reply_text(f"❌ No results for '**{query}**'\n\nTry running `/index` to scan more messages!")
        return

    summary = f"✅ **Found {min(len(results), 5)} result(s):**\n\n"
    for i, r in enumerate(results[:5], 1):
        summary += f"{i}. {r['title']}\n"
    await message.reply_text(summary)

    chat = await bot.get_chat(CHANNEL_USERNAME)
    for result in results[:5]:
        try:
            await bot.copy_message(message.chat.id, chat.id, result['msg_id'])
            await asyncio.sleep(0.5)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error copying {result['msg_id']}: {e}")

# ==============================
# 🚀 STARTUP
# ==============================

async def startup():
    logger.info("🤖 Bot started successfully!")
    load_db()
    
    if not movies_db:
        logger.info("📭 Database empty. Options:")
        logger.info("   1. Wait for new posts (auto-indexed)")
        logger.info("   2. Run /index to scan message IDs 1-5000")
        logger.info("   3. Database will build over time!")
    else:
        logger.info(f"✅ Loaded {len(movies_db)} movies from disk")
    
    logger.info("✅ Bot ready! Real-time indexing active.")

async def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    async with bot:
        await startup()
        await idle()

if __name__ == '__main__':
    logger.info("🎬 Starting Movie Bot v5.0 (Bot-Compatible)...")
    asyncio.run(main())
