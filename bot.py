import asyncio
import re
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db import init_db, add_file, search_files
from config import API_ID, API_HASH, BOT_TOKEN, CHANNEL_ID

# --- Flask Keep-Alive ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running fine on Render!", 200

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# --- Pyrogram Bot ---
bot = Client("moviebot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start"))
async def start(_, msg):
    await msg.reply("🎬 Welcome! Send me the movie or series name to search.")

@bot.on_message(filters.chat(CHANNEL_ID))
async def index_channel(_, msg):
    # When uploading new files to your private channel, this indexes them
    if msg.document or msg.video:
        caption = msg.caption or ""
        title = re.search(r"Title:\s*(.*)", caption)
        type_ = re.search(r"Type:\s*(.*)", caption)
        season = re.search(r"Season:\s*(\d+)", caption)
        episode = re.search(r"Episode:\s*(\d+)", caption)
        quality = re.search(r"Quality:\s*(.*)", caption)

        add_file(
            message_id = msg.id,
            title=title.group(1).strip() if title else "Unknown",
            type_=type_.group(1).strip() if type_ else "Movie",
            season=int(season.group(1)) if season else None,
            episode=int(episode.group(1)) if episode else None,
            quality=quality.group(1).strip() if quality else None,
        )

@bot.on_message(filters.text & ~filters.command("start"))
async def search(_, msg):
    query = msg.text.strip()
    results = search_files(query)
    if not results:
        await msg.reply("❌ No matches found.")
        return

    buttons = []
    for title, message_id, type_, season in results:
        if type_.lower() == "series":
            buttons.append([InlineKeyboardButton(f"{title} (Series)", callback_data=f"series:{title}")])
        else:
            buttons.append([InlineKeyboardButton(f"{title}", callback_data=f"movie:{file_id}")])

    await msg.reply("🔎 Closest matches:", reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex("^series:"))
async def handle_series(_, query):
    title = query.data.split(":")[1]
    from sqlite3 import connect
    conn = connect("movies.db")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT season FROM files WHERE title = ?", (title,))
    seasons = cur.fetchall()
    conn.close()

    buttons = [
        [InlineKeyboardButton(f"Season {s[0]}", callback_data=f"season:{title}:{s[0]}")]
        for s in seasons if s[0] is not None
    ]
    await query.message.reply(f"📺 Choose a season for *{title}*:", reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex("^season:"))
async def handle_season(_, query):
    _, title, season = query.data.split(":")
    from sqlite3 import connect
    conn = connect("movies.db")
    cur = conn.cursor()
    cur.execute("SELECT message_id, episode FROM files WHERE title=? AND season=?", (title, season))
    episodes = cur.fetchall()
    conn.close()

    buttons = [
        [InlineKeyboardButton(f"Episode {e[1]}", callback_data=f"send:{e[0]}")]
        for e in episodes
    ]
    await query.message.reply(f"📼 Choose episode:", reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex("^movie:"))
async def send_movie(client, query):
    message_id = int(query.data.split(":")[1])
    try:
        await client.copy_message(
            chat_id=query.message.chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=message_id
        )
    except Exception as e:
        await query.message.reply(f"⚠️ Error sending file: {e}")

@bot.on_callback_query(filters.regex("^send:"))
async def send_episode(client, query):
    message_id = int(query.data.split(":")[1])
    try:
        await client.copy_message(
            chat_id=query.message.chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=message_id
        )
    except Exception as e:
        await query.message.reply(f"⚠️ Error sending episode: {e}")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask).start()
    asyncio.run(bot.run())
