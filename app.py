# App entrypoint for EAU Confessions Bot (aiogram v3)
# Reads configuration from environment variables for Render deployment
import os
import logging
import sqlite3
import random
import html
import time
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, Text
from aiogram.fsm.storage.memory import MemoryStorage

# Optional dotenv for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---------- CONFIG (from environment) ----------
API_TOKEN = os.getenv("API_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
if CHANNEL_ID is not None:
    try:
        CHANNEL_ID = int(CHANNEL_ID)
    except Exception:
        CHANNEL_ID = None
DB_PATH = os.getenv("DB_PATH", "eaubot.db")
CONFESSION_NAME = os.getenv("CONFESSION_NAME", "EAU Confession")
CONFESSION_COOLDOWN = int(os.getenv("CONFESSION_COOLDOWN", "30"))
COMMENT_COOLDOWN = int(os.getenv("COMMENT_COOLDOWN", "10"))
BAD_WORDS = set(filter(None, map(str.strip, os.getenv("BAD_WORDS", "badword1,badword2,fuck,shit,bitch,asshole").split(','))))
AVATAR_EMOJIS = ["🗿","👤","👽","🤖","👻","🦊","🐼","🐵","🐥","🦄","😺","😎","🫥","🪄","🧋"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not API_TOKEN:
    logger.error("API_TOKEN is not set. Set it via environment variable API_TOKEN.")
    raise SystemExit("API_TOKEN not provided")

bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

BOT_USERNAME = None

# --- Database helpers ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS confessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        channel_message_id INTEGER,
        author_id INTEGER
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        confession_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        avatar TEXT,
        timestamp INTEGER NOT NULL
    )
    """)
    conn.commit()
    conn.close()


def db_execute(query, params=(), fetch=False, many=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if many:
        c.executemany(query, params)
        conn.commit()
        conn.close()
        return None
    c.execute(query, params)
    if fetch:
        rows = c.fetchall()
        conn.commit()
        conn.close()
        return rows
    conn.commit()
    conn.close()
    return None

_last_confession = {}
_last_comment = {}

def check_profanity(text: str) -> bool:
    t = text.lower()
    for w in BAD_WORDS:
        if not w:
            continue
        if w in t:
            return True
    return False

def format_confession_message(conf_id: int, text: str) -> str:
    t = html.escape(text)
    return f"👀 <b>{CONFESSION_NAME} #{conf_id}</b>\n\n{t}\n\n#Other"

def build_channel_keyboard(conf_id: int, comment_count: int, bot_username: str):
    view_url = f"https://t.me/{bot_username}?start=view_{conf_id}"
    add_url = f"https://t.me/{bot_username}?start=add_{conf_id}"
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(f"👀 Browse Comments ({comment_count})", url=view_url),
        InlineKeyboardButton("➕ Add Comment", url=add_url)
    )
    return kb

def build_comment_page_keyboard(conf_id: int, page: int, total_pages: int):
    kb = InlineKeyboardMarkup(row_width=2)
    if page > 1:
        kb.row(InlineKeyboardButton("⬅️ Prev", callback_data=f"page:{conf_id}:{page-1}"))
    if page < total_pages:
        kb.insert(InlineKeyboardButton("Next ➡️", callback_data=f"page:{conf_id}:{page+1}"))
    kb.add(InlineKeyboardButton("➕ Add Comment", url=f"https://t.me/{BOT_USERNAME}?start=add_{conf_id}"))
    return kb

def get_top_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.add(KeyboardButton("📝 Confess"))
    kb.add(KeyboardButton("👀 Browse Confessions"))
    return kb


@dp.message.register(Command("start"))
async def cmd_start(message: types.Message):
    global BOT_USERNAME
    text = f"Welcome to {CONFESSION_NAME} — send an anonymous confession and I'll post it.\n\n"
    await message.answer(text, reply_markup=get_top_menu())

    args = message.get_args() if hasattr(message, 'get_args') else None
    if args:
        arg = args
        if arg.startswith("view_"):
            try:
                conf_id = int(arg.split("_", 1)[1])
                await send_comments_page(message.chat.id, conf_id, page=1, edit_message_id=None)
                return
            except Exception:
                pass
        if arg.startswith("add_"):
            try:
                conf_id = int(arg.split("_", 1)[1])
                await message.answer("Send your comment:")
                await dp.storage.set_data(chat=message.chat.id, user=message.from_user.id, data={"confession_id": conf_id})
                await dp.storage.set_state(chat=message.chat.id, user=message.from_user.id, state="WAITING_FOR_COMMENT")
                return
            except Exception:
                pass


@dp.message.register(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Use the buttons in the channel to interact with confessions.")


@dp.message.register(Text(equals=["📝 Confess", "👀 Browse Confessions"]))
async def top_menu_buttons(message: types.Message):
    if message.text == "📝 Confess":
        await message.answer("Send your confession now.", reply_markup=types.ReplyKeyboardRemove())
    else:
        await message.answer("Browse confessions:", reply_markup=types.ReplyKeyboardRemove())
        await message.answer("https://t.me/eauvents")


@dp.message.register()
async def receive_confession(message: types.Message):
    # Only accept in private
    try:
        if message.chat.type != "private":
            return
    except Exception:
        pass

    uid = message.from_user.id
    now = time.time()
    last = _last_confession.get(uid, 0)
    if now - last < CONFESSION_COOLDOWN:
        await message.reply(f"Wait {int(CONFESSION_COOLDOWN - (now-last))}s before sending another confession.")
        return

    text = message.text.strip() if message.text else (message.caption.strip() if getattr(message, 'caption', None) else "")
    if not text:
        await message.reply("Empty confession.")
        return
    if check_profanity(text):
        await message.reply("Your confession contains banned words.")
        return

    ts = int(time.time())
    db_execute("INSERT INTO confessions (text, timestamp, author_id) VALUES (?, ?, ?)", (text, ts, uid))
    conf_id = db_execute("SELECT id FROM confessions ORDER BY id DESC LIMIT 1", fetch=True)[0][0]
    formatted = format_confession_message(conf_id, text)

    if CHANNEL_ID is None:
        await message.reply("Channel ID not configured on server. Confession saved locally.")
    else:
        try:
            sent = await bot.send_message(
                CHANNEL_ID,
                formatted,
                reply_markup=build_channel_keyboard(conf_id, 0, BOT_USERNAME)
            )
            db_execute("UPDATE confessions SET channel_message_id=? WHERE id=?", (sent.message_id, conf_id))
        except Exception:
            logger.exception("Failed to post confession to channel")
            await message.reply("Bot cannot post in channel.")
            return

    _last_confession[uid] = now
    await message.reply(f"Posted as {CONFESSION_NAME} #{conf_id}")


@dp.callback_query.register(lambda c: c.data and c.data.startswith("page:"))
async def callback_page(callback: types.CallbackQuery):
    await callback.answer()
    _, conf, pg = callback.data.split(":")
    await send_comments_page(callback.from_user.id, int(conf), int(pg), edit_message_id=callback.message.message_id)


async def send_comments_page(chat_id: int, confession_id: int, page: int = 1, edit_message_id: int = None):
    PAGE_SIZE = 4
    conf = db_execute("SELECT id, text FROM confessions WHERE id=?", (confession_id,), fetch=True)
    if not conf:
        await bot.send_message(chat_id, "Confession not found.")
        return

    conf_text = conf[0][1]
    total = db_execute("SELECT COUNT(*) FROM comments WHERE confession_id=?", (confession_id,), fetch=True)[0][0]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE

    rows = db_execute(
        "SELECT id, text, avatar, timestamp FROM comments WHERE confession_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (confession_id, PAGE_SIZE, offset), fetch=True)

    body = f"👀 <b>{CONFESSION_NAME} #{confession_id}</b>\n\n{html.escape(conf_text)}\n\n"
    body += f"💬 Comments (page {page}/{total_pages}):\n\n"

    for r in rows:
        cid, ctext, avatar, ts = r
        snippet = html.escape(ctext if len(ctext) <= 250 else ctext[:247] + "...")
        body += f"{avatar} <b>Comment #{cid}</b>\n{snippet}\n\n"

    kb = build_comment_page_keyboard(confession_id, page, total_pages)

    if edit_message_id:
        try:
            await bot.edit_message_text(body, chat_id, edit_message_id, reply_markup=kb)
            return
        except Exception:
            pass

    await bot.send_message(chat_id, body, reply_markup=kb)


async def main():
    # init DB and bot username
    init_db()
    me = await bot.get_me()
    global BOT_USERNAME
    BOT_USERNAME = me.username
    logger.info("Bot started (aiogram v3)")

    # start polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
