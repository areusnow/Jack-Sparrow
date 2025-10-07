import os
import logging
import re
import asyncio
import time
import sqlite3
from threading import Thread
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait
from pyrogram.types import Message
from waitress import serve

# ==============================
# 🔧 CONFIGURATION
# ==============================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME")
PORT = int(os.environ.get("PORT", 8080))
DB_FILE = "movies.db"

if not all([API_ID, API_HASH, BOT_TOKEN, CHANNEL_USERNAME]):
    logger.error("❌ Missing environment variables!")
    exit(1)

logger.info(f"Bot Token: {BOT_TOKEN[:5]}***{BOT_TOKEN[-5:]}")
logger.info(f"Channel: {CHANNEL_USERNAME}")

# ==============================
# 🗄️ SQLITE DATABASE
# ==============================

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS movies (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        text TEXT,
        keywords TEXT,
        media_type TEXT,
        date TEXT
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_title_keywords ON movies(title, keywords)")
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized")

def save_movie(msg_id, title, text, keywords, media_type, date):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO movies (id, title, text, keywords, media_type, date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (msg_id, title, text[:500], ",".join(keywords), media_type, date))
    conn.commit()
    conn.close()

def fetch_movies():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM movies")
    rows = c.fetchall()
    conn.close()
    return rows

def get_latest_indexed_id():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT MAX(id) FROM movies")
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else 0

# ==============================
# 🌐 FLASK WEB SERVER
# ==============================

app = Flask(__name__)
indexing_in_progress = False
last_indexed = None

@app.route("/")
def home():
    status = "Indexing..." if indexing_in_progress else "Ready"
    total = len(fetch_movies())
    return f"""
    <h1>🎬 Movie Bot SQLite</h1>
    <p>Status: {status}</p>
    <p>Total Movies: {total}</p>
    <p>Last Indexed: {last_indexed or "Never"}</p>
    <p>Channel: {CHANNEL_USERNAME}</p>
    """

@app.route("/health")
def health():
    return "OK", 200

def run_flask():
    logger.info(f"🌐 Starting Flask on port {PORT}...")
    serve(app, host="0.0.0.0", port=PORT)

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
# 🔍 HELPER FUNCTIONS
# ==============================

def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()

def extract_movie_title(text, caption=None):
    content = text or caption or ""
    if not content:
        return "Unknown Movie"
    lines = content.split("\n")
    for line in lines[:3]:
        line = clean_text(line)
        line = re.sub(r"[^\w\s\-:().]", "", line)
        if len(line) > 3 and not line.lower().startswith(("http", "www", "join", "channel")):
            return line[:80]
    return clean_text(content[:80])

def extract_keywords(text):
    if not text:
        return set()
    text = text.lower()
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    words = text.split()
    stop_words = {
        'the','a','an','and','or','but','in','on','at','to','for','of',
        'with','by','from','as','is','was','are','were','been','be','have',
        'has','had','do','does','did','will','would','could','should','may',
        'might','must','can','movie','film','watch','download','free','full',
        'hd','quality','link','join','channel','telegram','group','size','mb','gb'
    }
    return {w for w in words if len(w) > 2 and w not in stop_words}

def calculate_match_score(query, movie_data):
    score = 0
    query_words = set(query.lower().split())
    title = movie_data["title"].lower()
    keywords = set(movie_data["keywords"].split(","))
    text = movie_data["text"].lower()
    if query.lower() == title:
        return 10000
    if query.lower() in title:
        score += 5000
    if title.startswith(query.lower()):
        score += 3000
    score += len(query_words & set(title.split())) * 1000
    score += len(query_words & keywords) * 500
    if query.lower() in text:
        score += 100
    if movie_data["media_type"] in ["video", "document"]:
        score += 50
    return score

# ==============================
# ⚙️ CHANNEL INDEXING
# ==============================

async def index_channel():
    global indexing_in_progress, last_indexed
    indexing_in_progress = True
    logger.info("🔄 Starting channel indexing...")
    last_id = get_latest_indexed_id()
    indexed = 0
    start_time = time.time()

    try:
        async for message in bot.get_chat_history(CHANNEL_USERNAME, limit=1000):
            if message.id <= last_id:
                continue
            try:
                text = message.text or message.caption or ""
                if not text and not (message.video or message.document):
                    continue

                title = extract_movie_title(message.text, message.caption)
                keywords = extract_keywords(text)
                media_type = None
                if message.video:
                    media_type = "video"
                elif message.document:
                    media_type = "document"
                elif message.photo:
                    media_type = "photo"

                save_movie(message.id, title, text, keywords, media_type, message.date.strftime("%Y-%m-%d") if message.date else None)
                indexed += 1

                if indexed % 200 == 0:
                    logger.info(f"Indexed {indexed} new messages... waiting briefly")
                    await asyncio.sleep(2)

            except FloodWait as e:
                logger.warning(f"FloodWait: sleeping {e.value}s")
                await asyncio.sleep(e.value)
            except Exception as e:
                logger.debug(f"Error indexing message: {e}")
                continue

        last_indexed = time.strftime("%Y-%m-%d %H:%M:%S")
        elapsed = time.time() - start_time
        logger.info(f"✅ Indexing complete: {indexed} new messages in {elapsed:.2f}s")

    finally:
        indexing_in_progress = False

# ==============================
# 📝 BOT COMMANDS
# ==============================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    await message.reply_text(
        "🎬 **Movie Bot SQLite**\n\n"
        "Type a movie name to search!\n\n"
        "**Commands:**\n"
        "• /search <name>\n"
        "• /latest\n"
        "• /stats\n"
        "• /index\n"
        "• /help"
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    await start_command(client, message)

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client, message: Message):
    total = len(fetch_movies())
    status = "🔄 Indexing..." if indexing_in_progress else "✅ Ready"
    await message.reply_text(
        f"📊 Status: {status}\n"
        f"Total Movies: {total}\n"
        f"Last Indexed: {last_indexed or 'Never'}"
    )

@bot.on_message(filters.command("index") & filters.private)
async def index_command(client, message: Message):
    if indexing_in_progress:
        await message.reply_text("⏳ Indexing already in progress...")
        return
    await message.reply_text("🔄 Starting indexing...")
    await index_channel()
    await message.reply_text("✅ Indexing finished!")

@bot.on_message(filters.command("latest") & filters.private)
async def latest_command(client, message: Message):
    await message.reply_text("📥 Fetching latest movies...")
    count = 0
    try:
        async for msg in bot.get_chat_history(CHANNEL_USERNAME, limit=10):
            try:
                await msg.forward(message.chat.id)
                count += 1
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"Latest error: {e}")
    await message.reply_text(f"✅ Sent {count} latest movies")

@bot.on_message(filters.command("search") & filters.private)
async def search_command(client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("❌ Usage: /search <movie>")
        return
    query = parts[1].strip().lower()
    rows = fetch_movies()
    results = []
    for row in rows:
        score = calculate_match_score(query, row)
