import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from dotenv import load_dotenv
from rapidfuzz import fuzz, process

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Cache channel movie list to speed up searches
movie_cache = []

async def build_movie_cache():
    """Load all movies from the channel into memory."""
    global movie_cache
    print("📥 Loading movie list from channel...")
    movie_cache.clear()

    async for msg in bot.iter_chat_history(CHANNEL_ID, limit=2000):
        if msg.caption:
            movie_cache.append({
                "caption": msg.caption,
                "video": msg.video.file_id if msg.video else None,
                "document": msg.document.file_id if msg.document else None
            })

    print(f"✅ Loaded {len(movie_cache)} movies into cache.")


@dp.message(commands=["start", "help"])
async def start_cmd(message: Message):
    await message.answer(
        "🎬 *Welcome!*\n"
        "Send me a movie name, and I'll find the closest match from my collection.\n"
        "_Example:_ `avnger endgm` → `Avengers Endgame`",
        parse_mode="Markdown"
    )


@dp.message()
async def search_movie(message: Message):
    query = message.text.lower().strip()

    if not movie_cache:
        await message.answer("🔄 Please wait, I’m loading the movie database...")
        await build_movie_cache()

    # Prepare movie captions for fuzzy matching
    captions = [m["caption"] for m in movie_cache]

    # Find best match using fuzzy logic
    best_match = process.extractOne(query, captions, scorer=fuzz.token_set_ratio)

    if best_match and best_match[1] >= 65:  # 65% similarity threshold
        matched_title = best_match[0]
        movie = next(m for m in movie_cache if m["caption"] == matched_title)

        if movie["video"]:
            await message.answer_video(movie["video"], caption=movie["caption"])
        elif movie["document"]:
            await message.answer_document(movie["document"], caption=movie["caption"])
        else:
            await message.answer(movie["caption"])

    else:
        await message.answer("❌ No close match found. Please check the spelling or try another title.")


async def main():
    await build_movie_cache()  # Load movie list on startup
    print("🤖 Bot started and ready!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
