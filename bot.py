import os
import logging
import re
import json
import asyncio
import time
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import FloodWait
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
    <h1>🎬 Movie Bot v4.2 (Fixed)</h1>
    <p>Status: {status}</p>
    <p>Total Movies: {len(movies_db)}</p>
    <p>Last Indexed: {last_indexed or "Never"}</p>
    <p>Channel: {CHANNEL_USERNAME}</p>
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

# ==============================
# ⚙️ INDEXING
# ==============================

async def index_channel():
    global indexing_in_progress, last_indexed
    indexing_in_progress = True
    logger.info("🔄 Starting channel indexing...")

    try:
        indexed = 0
        start_time = time.time()

        # FIXED: Use iter_chat_history instead of get_chat_history
        async for message in bot.iter_chat_history(CHANNEL_USERNAME, limit=5000):
            try:
                text = message.text or message.caption or ""
                if not text and not (message.video or message.document):
                    continue

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

                indexed += 1
                if indexed % 200 == 0:
                    logger.info(f"Indexed {indexed} messages... autosaving")
                    save_db()
                    await asyncio.sleep(1)

            except FloodWait as e:
                logger.warning(f"FloodWait: sleeping {e.value}s")
                await asyncio.sleep(e.value)
            except Exception as e:
                logger.debug(f"Error indexing message: {e}")
                continue

        elapsed = time.time() - start_time
        last_indexed = time.strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"✅ Indexing complete: {indexed} movies in {elapsed:.2f}s")
        save_db()

    except Exception as e:
        logger.error(f"Indexing error: {e}")
    finally:
        indexing_in_progress = False

# ==============================
# 🧠 COMMANDS
# ==============================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    welcome = (
        "🎬 **Movie Bot v4.2 - Fixed!**\n\n"
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
    await start_command(client, message)

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client, message: Message):
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
    if indexing_in_progress:
        await message.reply_text("⏳ Indexing already in progress...")
        return
    status_msg = await message.reply_text("🔄 Starting indexing...")
    await index_channel()
    await status_msg.edit_text(f"✅ Indexed {len(movies_db)} movies!")

@bot.on_message(filters.command("latest") & filters.private)
async def latest_command(client, message: Message):
    status_msg = await message.reply_text("📥 Fetching latest movies...")
    count = 0
    try:
        # FIXED: Use iter_chat_history
        async for msg in bot.iter_chat_history(CHANNEL_USERNAME, limit=10):
            try:
                await msg.forward(message.chat.id)
                count += 1
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                logger.debug(f"Could not forward: {e}")
        await status_msg.delete()
        await message.reply_text(f"✅ Sent {count} latest movies")
    except Exception as e:
        logger.error(f"Latest error: {e}")
        await message.reply_text("❌ Error fetching movies")

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
        await message.reply_text("⏳ Database is empty. Running /index first...")
        await index_channel()
        if not movies_db:
            await message.reply_text("❌ No movies found in channel")
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
        await message.reply_text(f"❌ No results for '**{query}**'")
        return

    summary = f"✅ **Found {len(results[:5])} result(s):**\n\n"
    for i, r in enumerate(results[:5], 1):
        summary += f"{i}. {r['title']}\n"
    await message.reply_text(summary)

    for result in results[:5]:
        try:
            await bot.forward_messages(message.chat.id, CHANNEL_USERNAME, result['msg_id'])
            await asyncio.sleep(0.5)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error forwarding {result['msg_id']}: {e}")

# ==============================
# 🚀 STARTUP
# ==============================

async def startup():
    logger.info("🤖 Bot started successfully!")
    load_db()
    if not movies_db:
        logger.info("🔄 Running initial indexing...")
        await index_channel()
    logger.info("✅ Bot ready to serve!")

async def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    async with bot:
        await startup()
        await idle()

if __name__ == '__main__':
    logger.info("🎬 Starting Movie Bot v4.2 (Fixed)...")
    asyncio.run(main())
