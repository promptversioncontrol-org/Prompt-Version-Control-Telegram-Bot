from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime, timezone
from aiohttp import web
import html
import asyncio
import re
import os
from dotenv import load_dotenv

from prisma import Prisma

# ============================
# LOAD ENV
# ============================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "3001"))

if not BOT_TOKEN:
    raise Exception("❌ BOT_TOKEN missing in .env")

TOKEN_REGEX = re.compile(r"^[a-f0-9]{64}$")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
db = Prisma()

# ============================
# DB CONNECT
# ============================

async def ensure_db():
    if not db.is_connected():
        await db.connect()

# ============================
# HTTP NOTIFY ENDPOINT
# ============================

async def notify(request):
    data = await request.json()

    required_fields = ["userId", "workspaceSlug", "event"]
    for f in required_fields:
        if f not in data:
            return web.json_response({"error": f"Missing field: {f}"}, status=400)

    user_id = data["userId"]
    workspace_slug = data["workspaceSlug"]
    event = data["event"]

    await ensure_db()

    tg = await db.usertelegram.find_unique(where={"userId": user_id})
    if not tg:
        return web.json_response({"error": "User not connected to Telegram"}, status=404)

    chat_id = tg.chatId

    timestamp = event.get("timestamp")
    try:
        timestamp_formatted = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except:
        timestamp_formatted = timestamp

    snippet = html.escape(event.get("snippet", "")[:200])
    severity = event.get("severity", "unknown").upper()

    msg = f"""
🚨 <b>Leak Detected ({severity})</b>

👤 <b>User:</b> {event.get("username")}
🏷 <b>Rule:</b> {event.get("ruleId")}
📌 <b>Message:</b> {event.get("message")}

🗂 <b>Workspace:</b> {workspace_slug}

🔍 <b>Snippet:</b>
<code>{snippet}</code>

⏰ <b>Time:</b> {timestamp_formatted}
"""

    await bot.send_message(chat_id, msg)
    return web.json_response({"status": "ok"})

# ============================
# TELEGRAM START
# ============================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Witaj! Wyślij mi token wygenerowany w aplikacji.")

# ============================
# TOKEN HANDLER
# ============================

@dp.message()
async def handle_token(message: Message):
    text = message.text.strip()

    all_tokens = await db.telegramtoken.find_many()
    print("\n===================== DEBUG TOKEN LIST =====================")
    for t in all_tokens:
        print(f"- token: {t.token} | userId: {t.userId} | expiresAt: {t.expiresAt}")
    print("============================================================\n")

    token_row = await db.telegramtoken.find_unique(where={"token": text})

    if not token_row:
        await message.answer("Token jest nieprawidłowy lub wygasł.")
        return

    if token_row.expiresAt < datetime.now(timezone.utc):
        await message.answer("Token wygasł.")
        return

    await db.usertelegram.create(
        data={
            "chatId": str(message.chat.id),
            "userId": token_row.userId,
        }
    )

    await db.telegramtoken.delete(where={"id": token_row.id})

    await message.answer("Połączono konto Telegram z aplikacją 🔥")

# ============================
# RUN BOT + SERVER
# ============================

async def main():
    print("➡️ Connecting to DB...")
    await db.connect()
    
    print(f"📡 Starting bot & HTTP server on port {PORT}...")

    app = web.Application()
    app.router.add_post("/notify", notify)

    await asyncio.gather(
        dp.start_polling(bot),
        web._run_app(app, port=PORT)
    )

if __name__ == "__main__":
    asyncio.run(main())
