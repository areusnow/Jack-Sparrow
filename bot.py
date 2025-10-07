import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from dotenv import load_dotenv
from rapidfuzz import fuzz, process
import re

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

movie_cache = []


# --- Helper to parse captions into structured format ---
def parse_caption(caption: str):
    """
    Parse captions like:
    Loki | Series | English | S02
    Interstellar | Movie | English | 2014
    """
    parts = [p.strip() for p in caption.split("|")]
    data = {
        "title": parts[0] if len(parts) > 0 else None,
        "type": parts[1].capitalize() if len(parts) > 1 else "Movie",
        "lang": parts[2] if len(parts) > 2 else None,
        "season_or_year": parts[3] if len(parts) > 3 else None,
        "caption": caption,
    }
    return data


async def build_movie_cache():
    """Load all movies and series info from your channel."""
    global movie_cache
    movie_cache.clear()
    print("📥 Fetching data from channel...")

    async for msg in bot.iter_chat_history(CHANNEL_ID, limit=3000):
        if msg.caption:
            parsed = parse_caption(msg.caption)
            parsed["video"] = msg.video.file_id if msg.video else None
            parsed["document"] = msg.document.file_id if msg.document else None
            movie_cache.append(parsed)

    print(f"✅ Loaded {len(movie_cache)} items into cache.")


@dp.message(commands=["start"])
async def start(message: Message):
    await message.answer(
        "🎬 Welcome!\n"
        "Send me a movie or series name and I’ll find it for you.\n\n"
        "_Example:_ `Loki`, `Interstellar`, `Money Heist`",
        parse_mode="Markdown"
    )


@dp.message(commands=["refresh"])
async def refresh_cache(message: Message):
    await message.answer("🔄 Refreshing movie database...")
    await build_movie_cache()
    await message.answer("✅ Database refreshed successfully!")


@dp.message()
async def search_movie(message: Message):
    query = message.text.lower().strip()

    if not movie_cache:
        await message.answer("⏳ Please wait, loading database...")
        await build_movie_cache()

    # Fuzzy match by title
    titles = list(set([m["title"] for m in movie_cache if m["title"]]))
    best_matches = process.extract(query, titles, scorer=fuzz.token_set_ratio, limit=5)
    relevant_titles = [t for t, score, _ in best_matches if score >= 60]

    if not relevant_titles:
        await message.answer("❌ No close match found. Try again.")
        return

    # Iterate through all close titles
    for title in relevant_titles:
        results = [m for m in movie_cache if m["title"].lower() == title.lower()]
        if not results:
            continue

        item_type = results[0]["type"]

        if item_type.lower() == "series":
            # Group by season
            seasons = {}
            for r in results:
                season = r["season_or_year"] or "Unknown"
                seasons[season] = r

            # Build inline keyboard
            buttons = [
                [InlineKeyboardButton(text=season, callback_data=f"get_{title}_{season}")]
                for season in sorted(seasons.keys())
            ]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer(f"📺 *{title}* — Select a season:", parse_mode="Markdown", reply_markup=keyboard)

        else:
            # Movies: send all matching entries (different langs/years)
            for r in results:
                caption = r["caption"]
                if r["video"]:
                    await message.answer_video(r["video"], caption=caption)
                elif r["document"]:
                    await message.answer_document(r["document"], caption=caption)
                else:
                    await message.answer(caption)


@dp.callback_query(lambda c: c.data.startswith("get_"))
async def send_season(callback: CallbackQuery):
    _, title, season = callback.data.split("_", 2)
    results = [
        m for m in movie_cache
        if m["title"].lower() == title.lower() and (m["season_or_year"] == season)
    ]

    if not results:
        await callback.message.answer("⚠️ No episodes found for that season.")
        return

    for r in results:
        if r["video"]:
            await callback.message.answer_video(r["video"], caption=r["caption"])
        elif r["document"]:
            await callback.message.answer_document(r["document"], caption=r["caption"])
        else:
            await callback.message.answer(r["caption"])

    await callback.answer()  # Acknowledge click


async def main():
    await build_movie_cache()
    print("🤖 Bot running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
