# App entrypoint for EAU Confessions Bot (aiogram v2)
# Reads configuration from environment variables for Render deployment
import os
import logging
import sqlite3
import random
import html
import time
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode, ReplyKeyboardMarkup, KeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

# Load .env locally if available (optional)
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

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

BOT_USERNAME = None

# Database helpers

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

class AddCommentState(StatesGroup):
    waiting_for_comment = State()

# ---------- Helpers ----------

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

# ---------- Top Menu ----------

def get_top_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.add(KeyboardButton("📝 Confess"))
    kb.add(KeyboardButton("👀 Browse Confessions"))
    return kb

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    global BOT_USERNAME
    text = f"Welcome to {CONFESSION_NAME} — send an anonymous confession and I'll post it.\n\n"
    await message.answer(text, reply_markup=get_top_menu())

    if message.get_args():
        arg = message.get_args()
        if arg.startswith("view_"):
            try:
                conf_id = int(arg.split("_",1)[1])
                await send_comments_page(message.chat.id, conf_id, page=1, edit_message_id=None)
                return
            except Exception:
                pass
        if arg.startswith("add_"):
            try:
                conf_id = int(arg.split("_",1)[1])
                await message.answer("Send your comment:")
                state = dp.current_state(chat=message.chat.id, user=message.from_user.id)
                await state.update_data(confession_id=conf_id)
                await AddCommentState.waiting_for_comment.set()
                return
            except Exception:
                pass

@dp.message_handler(commands=["help"])
async def cmd_help(message: types.Message):
    await message.answer("Use the buttons in the channel to interact with confessions.")

@dp.message_handler(lambda m: m.text in ["📝 Confess", "👀 Browse Confessions"])
async def top_menu_buttons(message: types.Message):
    if message.text == "📝 Confess":
        await message.answer("Send your confession now.", reply_markup=types.ReplyKeyboardRemove())
    else:
        await message.answer("Browse confessions:", reply_markup=types.ReplyKeyboardRemove())
        await message.answer("https://t.me/eauvents")

@dp.message_handler()
async def receive_confession(message: types.Message):
    if message.chat.type != "private":
        return
    uid = message.from_user.id
    now = time.time()
    last = _last_confession.get(uid, 0)
    if now - last < CONFESSION_COOLDOWN:
        await message.reply(f"Wait {int(CONFESSION_COOLDOWN - (now-last))}s before sending another confession.")
        return

    text = message.text.strip() if message.text else (message.caption.strip() if message.caption else "")
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
                parse_mode=ParseMode.HTML,
                reply_markup=build_channel_keyboard(conf_id, 0, BOT_USERNAME)
            )
            db_execute("UPDATE confessions SET channel_message_id=? WHERE id=?", (sent.message_id, conf_id))
        except Exception as e:
            logger.exception("Failed to post confession to channel")
            await message.reply("Bot cannot post in channel.")
            return

    _last_confession[uid] = now
    await message.reply(f"Posted as {CONFESSION_NAME} #{conf_id}")

# ---------- Add Comment ----------
@dp.message_handler(state=AddCommentState.waiting_for_comment)
async def process_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    confession_id = data.get("confession_id")
    if not confession_id:
        await message.reply("Session expired.")
        await state.finish()
        return

    uid = message.from_user.id
    now = time.time()
    last = _last_comment.get(uid, 0)
    if now - last < COMMENT_COOLDOWN:
        await message.reply(f"Wait {int(COMMENT_COOLDOWN - (now-last))}s before commenting again.")
        await state.finish()
        return

    text = message.text.strip()
    if not text:
        await message.reply("Comment canceled.")
        await state.finish()
        return

    if check_profanity(text):
        await message.reply("Your comment contains banned words.")
        await state.finish()
        return

    avatar = random.choice(AVATAR_EMOJIS)
    ts = int(time.time())
    db_execute(
        "INSERT INTO comments (confession_id, text, avatar, timestamp) VALUES (?, ?, ?, ?)",
        (confession_id, text, avatar, ts)
    )

    rows = db_execute("SELECT channel_message_id FROM confessions WHERE id=?", (confession_id,), fetch=True)
    if rows and rows[0][0] and CHANNEL_ID is not None:
        ch_msg = rows[0][0]
        cnt = db_execute("SELECT COUNT(*) FROM comments WHERE confession_id=?", (confession_id,), fetch=True)[0][0]
        try:
            await bot.edit_message_reply_markup(
                CHANNEL_ID, ch_msg,
                reply_markup=build_channel_keyboard(confession_id, cnt, BOT_USERNAME)
            )
        except Exception:
            pass

    _last_comment[uid] = now
    await message.reply("Comment added!")
    await state.finish()

# ---------- View Comments ----------
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
            await bot.edit_message_text(body, chat_id, edit_message_id, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception:
            pass

    await bot.send_message(chat_id, body, parse_mode=ParseMode.HTML, reply_markup=kb)

# ---------- Callback Page ----------
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("page:"))
async def callback_page(call: types.CallbackQuery):
    await call.answer()
    _, conf, pg = call.data.split(":")
    await send_comments_page(call.from_user.id, int(conf), int(pg), edit_message_id=call.message.message_id)

# ---------- Startup ----------
async def on_startup(dp_local):
    global BOT_USERNAME
    init_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username
    logger.info("Bot started")

# Webhook configuration (use WEBHOOK_HOST to enable webhooks)
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # e.g. https://your-service.onrender.com
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH") or f"/webhook/{API_TOKEN.split(':')[0]}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else None
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", "8000"))
USE_WEBHOOK = bool(WEBHOOK_HOST)


async def on_shutdown(dp_local):
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    try:
        await dp_local.storage.close()
    except Exception:
        pass


if __name__ == "__main__":
    if USE_WEBHOOK:
        # Run as a web service using aiogram's start_webhook (requires WEBHOOK_HOST to be a HTTPS URL)
        from aiogram.utils.executor import start_webhook

        if not WEBHOOK_URL:
            logger.error("WEBHOOK_HOST was provided but WEBHOOK_URL could not be constructed.")
            raise SystemExit("Invalid WEBHOOK configuration")

        # on_startup will initialize DB and set BOT_USERNAME
        async def _on_startup(dp_local):
            await on_startup(dp_local)
            # set webhook to receive updates
            try:
                await bot.set_webhook(WEBHOOK_URL)
                logger.info(f"Webhook set to {WEBHOOK_URL}")
            except Exception:
                logger.exception("Failed to set webhook")

        # create an aiohttp web app and add a health endpoint so Render health checks pass
        try:
            from aiohttp import web
        except Exception:
            web = None

        web_app = None
        if web is not None:
            web_app = web.Application()

            async def _health(request):
                return web.Response(text="OK")

            async def _root(request):
                return web.Response(text="EAU Confessions Bot")

            web_app.router.add_get('/health', _health)
            web_app.router.add_get('/', _root)

        start_webhook(
            dp,
            webhook_path=WEBHOOK_PATH,
            skip_updates=True,
            on_startup=_on_startup,
            on_shutdown=on_shutdown,
            host=WEBAPP_HOST,
            port=WEBAPP_PORT,
            web_app=web_app,
        )
    else:
        # initialize DB and start long-polling (worker mode)
        init_db()
        executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
