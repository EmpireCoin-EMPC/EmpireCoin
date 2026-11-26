import asyncio
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "empire_support.db")
dp = Dispatcher()
LANGS = {"en": "English", "fa": "فارسی", "ru": "Русский"}
PROMPTS = {
 "en": "Please send your question, message, or a photo/screenshot of the issue. Your Telegram ID and username will be attached automatically.",
 "fa": "لطفاً سؤال، پیام یا عکس/اسکرین‌شات مربوط به مشکل خود را ارسال کنید. شناسه و نام کاربری تلگرام شما به‌صورت خودکار همراه پیام ثبت می‌شود.",
 "ru": "Отправьте вопрос, сообщение или фото/скриншот проблемы. Ваш Telegram ID и username будут добавлены автоматически."
}
ACK = {
 "en": "Your message has been sent to the Empire Support team. We will reply as soon as possible. You can send another message any time.",
 "fa": "پیام شما به تیم Empire Support ارسال شد. تیم در اولین فرصت پاسخ خواهد داد. هر زمان خواستید می‌توانید پیام دیگری نیز ارسال کنید.",
 "ru": "Ваше сообщение отправлено команде Empire Support. Мы ответим как можно скорее. Вы можете отправить ещё сообщение в любое время."
}
def db():
    return sqlite3.connect(DB_PATH)
def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, lang TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS admin_messages(message_id INTEGER PRIMARY KEY,user_id INTEGER,ticket_id INTEGER)")
def lang_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English",callback_data="lang:en")],
        [InlineKeyboardButton(text="🇮🇷 فارسی",callback_data="lang:fa")],
        [InlineKeyboardButton(text="🇷🇺 Русский",callback_data="lang:ru")]])
def get_lang(uid):
    with db() as c:
        row=c.execute("SELECT lang FROM users WHERE user_id=?",(uid,)).fetchone()
    return row[0] if row else "en"
@dp.message(CommandStart())
async def start(m: Message):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id,username,lang) VALUES(?,?,?)",(m.from_user.id,m.from_user.username or "", "en"))
        c.execute("UPDATE users SET username=? WHERE user_id=?",(m.from_user.username or "",m.from_user.id))
    await m.answer("Welcome to Empire Support! Please choose your language.\n\nبه Empire Support خوش آمدید! زبان را انتخاب کنید.\n\nДобро пожаловать! Выберите язык.",reply_markup=lang_keyboard())
@dp.callback_query(F.data.startswith("lang:"))
async def language(q: CallbackQuery):
    l=q.data.split(":")[1]
    if l not in LANGS: return await q.answer()
    with db() as c: c.execute("UPDATE users SET lang=? WHERE user_id=?",(l,q.from_user.id))
    await q.message.answer(PROMPTS[l])
    await q.answer()
@dp.message(F.reply_to_message)
async def admin_reply(m: Message):
    if m.chat.id != ADMIN_CHAT_ID: return
    with db() as c:
        row=c.execute("SELECT user_id,ticket_id FROM admin_messages WHERE message_id=?",(m.reply_to_message.message_id,)).fetchone()
    if not row:
        return
    uid,ticket=row
    try:
        await bot.send_message(uid, "💬 Empire Support:\n\n"+(m.text or m.caption or ""))
        if m.photo: await bot.send_photo(uid,m.photo[-1].file_id,caption=m.caption or "💬 Empire Support")
        elif m.document: await bot.send_document(uid,m.document.file_id,caption=m.caption or "💬 Empire Support")
        elif m.video: await bot.send_video(uid,m.video.file_id,caption=m.caption or "💬 Empire Support")
        elif m.voice: await bot.send_voice(uid,m.voice.file_id)
        await m.answer("Reply sent to the user.")
    except Exception as e:
        await m.answer(f"Delivery failed: {type(e).__name__}")
@dp.message()
async def receive(m: Message):
    if m.chat.id == ADMIN_CHAT_ID: return
    uid=m.from_user.id
    l=get_lang(uid)
    with db() as c:
        cur=c.execute("INSERT INTO tickets(user_id,created_at) VALUES(?,?)",(uid,datetime.now(timezone.utc).isoformat()))
        ticket=cur.lastrowid
        username="@"+m.from_user.username if m.from_user.username else "(no username)"
        info=f"📩 Support ticket #{ticket}\n👤 {m.from_user.full_name}\n🔖 {username}\n🆔 User ID: {uid}\n🌐 Language: {l}\n\nReply directly to this forwarded message to answer the user."
    forwarded=await bot.send_message(ADMIN_CHAT_ID,info)
    with db() as c: c.execute("INSERT INTO admin_messages(message_id,user_id,ticket_id) VALUES(?,?,?)",(forwarded.message_id,uid,ticket))
    if m.text: await bot.send_message(ADMIN_CHAT_ID,"Message:\n"+m.text)
    elif m.photo: await bot.send_photo(ADMIN_CHAT_ID,m.photo[-1].file_id,caption=f"Ticket #{ticket} | User ID: {uid}")
    elif m.document: await bot.send_document(ADMIN_CHAT_ID,m.document.file_id,caption=f"Ticket #{ticket} | User ID: {uid}")
    elif m.video: await bot.send_video(ADMIN_CHAT_ID,m.video.file_id,caption=f"Ticket #{ticket} | User ID: {uid}")
    elif m.voice: await bot.send_voice(ADMIN_CHAT_ID,m.voice.file_id,caption=f"Ticket #{ticket} | User ID: {uid}")
    elif m.audio: await bot.send_audio(ADMIN_CHAT_ID,m.audio.file_id,caption=f"Ticket #{ticket} | User ID: {uid}")
    elif m.sticker: await bot.send_sticker(ADMIN_CHAT_ID,m.sticker.file_id)
    else: await bot.send_message(ADMIN_CHAT_ID,f"Ticket #{ticket} received (unsupported message type). User ID: {uid}")
    await m.answer(ACK[l])
async def main():
    global bot
    if not TOKEN or not ADMIN_CHAT_ID: raise RuntimeError("Set BOT_TOKEN and ADMIN_CHAT_ID in .env")
    bot=Bot(TOKEN)
    init_db()
    await dp.start_polling(bot)
if __name__=="__main__":
    asyncio.run(main())
