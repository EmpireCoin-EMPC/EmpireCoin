import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "bot.db")
COMPANY_WALLET = os.getenv("GRAM_COMPANY_WALLET", "")
HOURLY_REWARD = int(os.getenv("HOURLY_REWARD", "10"))
POOL_START = int(os.getenv("MINING_POOL", "172000000"))
FEE_PERCENT = int(os.getenv("WITHDRAWAL_FEE_PERCENT", "10"))
ACTIVATION_FEE = os.getenv("ACTIVATION_FEE_GRAM", "0.5")
WAIT_DAYS = int(os.getenv("ACTIVATION_WAIT_DAYS", "30"))

def now():
    return datetime.now(timezone.utc)

def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0,
            wallet TEXT, last_mine TEXT, activation_tx TEXT, activation_at TEXT,
            withdraw_after TEXT, lang TEXT DEFAULT 'en')""")
        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
            fee INTEGER, net INTEGER, wallet TEXT, status TEXT DEFAULT 'pending',
            tx_hash TEXT, created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, reward INTEGER,
            active INTEGER DEFAULT 1)""")
        c.execute("""CREATE TABLE IF NOT EXISTS task_claims(
            user_id INTEGER, task_id INTEGER, PRIMARY KEY(user_id, task_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, details TEXT,
            status TEXT DEFAULT 'pending')""")
        c.execute("""CREATE TABLE IF NOT EXISTS lotteries(
            id INTEGER PRIMARY KEY AUTOINCREMENT, prize INTEGER, status TEXT DEFAULT 'open',
            winner_id INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS lottery_entries(
            lottery_id INTEGER, user_id INTEGER, UNIQUE(lottery_id,user_id))""")
        cols = [row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()]
        if "lang" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'en'")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('pool',?)", (str(POOL_START),))

def is_admin(m: Message):
    return m.from_user and m.from_user.id == ADMIN_ID

def user_upsert(m: Message):
    with db() as c:
        c.execute("INSERT INTO users(user_id,username) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                  (m.from_user.id, m.from_user.username or ""))

def pool_change(c, delta):
    row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
    current = int(row[0]) if row else POOL_START
    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('pool',?)", (str(max(0, current + delta)),))

bot = Bot(TOKEN)
dp = Dispatcher()



def copy_text_keyboard(value: str, label: str = "📋 کپی"):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=value))
    ]]) if value else None

def get_user_lang(user_id: int) -> str:
    with db() as c:
        row = c.execute("SELECT lang FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row and row[0] in ("en", "fa", "ru") else "en"

def language_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
        [InlineKeyboardButton(text="🇮🇷 فارسی", callback_data="lang:fa")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
    ])

MENU_LABELS = {
    "en": ["💰 My balance", "⛏ Hourly mining", "📋 Tasks", "🎟 Lottery", "👛 Set wallet", "💸 Withdraw", "🤝 Trade", "💳 Activate account", "🌐 Language"],
    "fa": ["💰 موجودی من", "⛏ استخراج ساعتی", "📋 وظایف", "🎟 قرعه‌کشی", "👛 ثبت کیف پول", "💸 درخواست برداشت", "🤝 معامله", "💳 فعال‌سازی حساب", "🌐 تغییر زبان"],
    "ru": ["💰 Мой баланс", "⛏ Почасовая добыча", "📋 Задания", "🎟 Лотерея", "👛 Мой кошелёк", "💸 Вывод", "🤝 Сделка", "💳 Активация", "🌐 Язык"],
}

def user_menu_keyboard(lang="en"):
    a = MENU_LABELS.get(lang, MENU_LABELS["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=a[0], callback_data="user:balance"), InlineKeyboardButton(text=a[1], callback_data="user:mine")],
        [InlineKeyboardButton(text=a[2], callback_data="user:tasks"), InlineKeyboardButton(text=a[3], callback_data="user:lottery")],
        [InlineKeyboardButton(text=a[4], callback_data="user:wallet"), InlineKeyboardButton(text=a[5], callback_data="user:withdraw")],
        [InlineKeyboardButton(text=a[6], callback_data="user:trade"), InlineKeyboardButton(text=a[7], callback_data="user:activate")],
        [InlineKeyboardButton(text=a[8], callback_data="user:language")],
    ])

def user_upsert_from_id(user_id: int, username: str):
    with db() as c:
        c.execute("INSERT INTO users(user_id,username) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                  (user_id, username))

@dp.callback_query(F.data.startswith("lang:"))
async def choose_language(q: CallbackQuery):
    if not q.from_user:
        await q.answer()
        return
    lang = q.data.split(":", 1)[1]
    if lang not in ("en", "fa", "ru"):
        await q.answer("Invalid language", show_alert=True)
        return
    user_upsert_from_id(q.from_user.id, q.from_user.username or "")
    with db() as c:
        c.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, q.from_user.id))
    messages = {"en": "Language saved.", "fa": "زبان شما ذخیره شد.", "ru": "Язык сохранён."}
    await q.message.answer(messages[lang], reply_markup=user_menu_keyboard(lang))
    await q.answer()

USER_TEXT = {
 "en": {
  "balance":"Balance: {balance} GRM\nMining pool remaining: {pool} GRM\n{status}",
  "status":"Withdrawals available after: {date}", "inactive":"Activation payment is not confirmed yet.",
  "mine_wait":"One hour has not passed. Time remaining: {left}", "mine_empty":"The mining pool is empty.",
  "mine_ok":"{reward} GRM has been added to your balance.", "tasks_empty":"No tasks are available right now.",
  "claim_hint":"\nTo claim a task reward: /claim TASK_ID", "lottery_none":"There is no active lottery.",
  "lottery_ok":"You have entered the lottery.", "lottery_dup":"You have already entered this lottery.",
  "wallet":"To save your wallet, send:\n/setwallet WALLET_ADDRESS",
  "withdraw":"To request a withdrawal, send:\n/withdraw AMOUNT\nWithdrawals are available 30 days after activation approval.",
  "trade":"To request a trade, send:\n/trade TRADE_DETAILS",
  "activate":"Activation fee: {fee} GRAM\nCompany wallet:\n{wallet}\nAfter payment, submit the transaction hash using /activate TX_HASH",
  "invalid":"Unknown option.", "copy_company":"📋 Copy company wallet", "copy_wallet":"📋 Copy my wallet"
 },
 "fa": {
  "balance":"موجودی: {balance} GRM\nباقی‌مانده استخر: {pool} GRM\n{status}",
  "status":"زمان مجاز برداشت: {date}", "inactive":"پرداخت فعال‌سازی هنوز تأیید نشده است.",
  "mine_wait":"هنوز یک ساعت کامل نشده است. زمان باقی‌مانده: {left}", "mine_empty":"استخر استخراج خالی است.",
  "mine_ok":"{reward} GRM به موجودی شما اضافه شد.", "tasks_empty":"فعلاً وظیفه‌ای ثبت نشده است.",
  "claim_hint":"\nبرای دریافت پاداش: /claim TASK_ID", "lottery_none":"قرعه‌کشی فعالی وجود ندارد.",
  "lottery_ok":"در قرعه‌کشی ثبت شدید.", "lottery_dup":"قبلاً در این قرعه‌کشی ثبت شده‌اید.",
  "wallet":"برای ثبت کیف پول بفرستید:\n/setwallet WALLET_ADDRESS",
  "withdraw":"برای درخواست برداشت بفرستید:\n/withdraw AMOUNT\nبرداشت ۳۰ روز پس از تأیید فعال‌سازی ممکن است.",
  "trade":"برای درخواست معامله بفرستید:\n/trade TRADE_DETAILS",
  "activate":"مبلغ فعال‌سازی: {fee} GRAM\nکیف پول شرکت:\n{wallet}\nپس از پرداخت، شناسه تراکنش را با دستور /activate TX_HASH بفرستید.",
  "invalid":"گزینه نامعتبر است.", "copy_company":"📋 کپی آدرس کیف پول شرکت", "copy_wallet":"📋 کپی آدرس کیف پول من"
 },
 "ru": {
  "balance":"Баланс: {balance} GRM\nОстаток пула: {pool} GRM\n{status}",
  "status":"Вывод доступен после: {date}", "inactive":"Платёж активации ещё не подтверждён.",
  "mine_wait":"Один час ещё не прошёл. Осталось: {left}", "mine_empty":"В пуле больше нет токенов.",
  "mine_ok":"На ваш баланс добавлено {reward} GRM.", "tasks_empty":"Сейчас заданий нет.",
  "claim_hint":"\nЧтобы получить награду: /claim TASK_ID", "lottery_none":"Нет активной лотереи.",
  "lottery_ok":"Вы зарегистрированы в лотерее.", "lottery_dup":"Вы уже участвуете в этой лотерее.",
  "wallet":"Чтобы сохранить кошелёк, отправьте:\n/setwallet WALLET_ADDRESS",
  "withdraw":"Чтобы запросить вывод, отправьте:\n/withdraw AMOUNT\nВывод доступен через 30 дней после подтверждения активации.",
  "trade":"Чтобы запросить сделку, отправьте:\n/trade TRADE_DETAILS",
  "activate":"Плата за активацию: {fee} GRAM\nКошелёк компании:\n{wallet}\nПосле оплаты отправьте хеш транзакции командой /activate TX_HASH",
  "invalid":"Неизвестная команда.", "copy_company":"📋 Копировать кошелёк компании", "copy_wallet":"📋 Копировать мой кошелёк"
 }
}

USER_COMMAND_TEXT = {
  "balance": ("Balance: {balance} GRM\\\nMining pool remaining: {pool} GRM\\\n{status}", "موجودی: {balance} GRM\\\nباقی‌مانده استخر: {pool} GRM\\\n{status}", "Баланс: {balance} GRM\\\nОстаток пула: {pool} GRM\\\n{status}"),
  "activation_pending": ("Activation request submitted and is awaiting admin review. Required payment: {fee} GRAM\\\nCompany wallet: {wallet}\\\nThe 30-day period starts only after the admin verifies the payment.", "درخواست فعال‌سازی ثبت شد و منتظر بررسی مدیر است. مبلغ لازم: {fee} GRAM\\\nکیف پول شرکت: {wallet}\\\nمهلت ۳۰ روزه فقط پس از تأیید واقعی پرداخت توسط مدیر آغاز می‌شود.", "Заявка на активацию отправлена и ожидает проверки администратора. Сумма: {fee} GRAM\\\nКошелёк компании: {wallet}\\\n30-дневный срок начнётся только после проверки платежа администратором."),
  "wallet_saved": ("Wallet saved:\\\n{wallet}\\\nPlease verify the address carefully before requesting a withdrawal.", "آدرس کیف پول ذخیره شد:\\\n{wallet}\\\nپیش از درخواست برداشت، آدرس را با دقت بررسی کنید.", "Кошелёк сохранён:\\\n{wallet}\\\nПеред запросом вывода внимательно проверьте адрес."),
  "wallet": ("To save your wallet, send:\n/setwallet WALLET_ADDRESS", "برای ثبت کیف پول بفرستید:\n/setwallet WALLET_ADDRESS", "Чтобы сохранить кошелёк, отправьте:\n/setwallet WALLET_ADDRESS"),
  "withdraw_usage": ("Usage: /withdraw AMOUNT_G​​RM", "روش استفاده: /withdraw مقدار_GRM", "Использование: /withdraw СУММА_GRM"),
  "wallet_required": ("Please set your TON wallet first using /setwallet WALLET_ADDRESS.", "ابتدا کیف پول TON خود را با دستور /setwallet آدرس ثبت کنید.", "Сначала укажите TON-кошелёк командой /setwallet АДРЕС."),
  "withdraw_locked": ("Withdrawals are not available yet. Pay {fee} GRAM and wait {days} days after admin approval.", "برداشت هنوز فعال نیست. مبلغ {fee} GRAM را پرداخت کنید و پس از تأیید مدیر {days} روز صبر کنید.", "Вывод пока недоступен. Оплатите {fee} GRAM и подождите {days} дней после подтверждения администратором."),
  "insufficient": ("Insufficient balance.", "موجودی کافی نیست.", "Недостаточно средств."),
  "withdraw_created": ("Withdrawal request #{id} submitted. Gross: {amount} GRM; fee ({percent}%): {fee} GRM; net: {net} GRM. Payment is manual after admin approval.", "درخواست برداشت #{id} ثبت شد. مبلغ ناخالص: {amount} GRM؛ کارمزد ({percent}%): {fee} GRM؛ مبلغ خالص: {net} GRM. پرداخت پس از تأیید مدیر دستی انجام می‌شود.", "Заявка на вывод №{id} создана. Сумма: {amount} GRM; комиссия ({percent}%): {fee} GRM; к выплате: {net} GRM. Выплата производится вручную после одобрения администратора."),
  "tasks_empty": ("No tasks are available right now.", "فعلاً وظیفه‌ای ثبت نشده است.", "Сейчас заданий нет."),
  "claim_usage": ("Usage: /claim TASK_ID", "روش استفاده: /claim شماره_وظیفه", "Использование: /claim ID_ЗАДАНИЯ"),
  "task_missing": ("Task not found.", "وظیفه پیدا نشد.", "Задание не найдено."),
  "task_duplicate": ("You have already claimed this task.", "این وظیفه قبلاً برای شما ثبت شده است.", "Вы уже отправили заявку по этому заданию."),
  "task_paid": ("{reward} GRM added. Note: task completion is self-reported in this version.", "{reward} GRM اضافه شد. توجه: انجام وظیفه در نسخه فعلی به‌صورت خوداظهاری است.", "Добавлено {reward} GRM. В этой версии выполнение задания подтверждается самим пользователем."),
  "trade_usage": ("Usage: /trade TRADE_DETAILS", "روش استفاده: /trade توضیحات_معامله", "Использование: /trade ОПИСАНИЕ_СДЕЛКИ"),
  "trade_sent": ("Your trade request has been sent to the administrator for review.", "درخواست معامله برای بررسی مدیر ارسال شد.", "Запрос на сделку отправлен администратору на рассмотрение."),
  "lottery_none": ("There is no active lottery.", "قرعه‌کشی فعالی وجود ندارد.", "Нет активной лотереи."),
  "lottery_dup": ("You have already entered this lottery.", "قبلاً در این قرعه‌کشی ثبت شده‌اید.", "Вы уже участвуете в этой лотерее."),
  "lottery_ok": ("You have entered the lottery.", "در قرعه‌کشی ثبت شدید.", "Вы зарегистрированы в лотерее."),
}


def ut(lang, key, **kwargs):
    template = USER_TEXT.get(lang, USER_TEXT["en"]).get(key, USER_TEXT["en"].get(key, key))
    return template.format(**kwargs)

def uct(lang, key, **kwargs):
    values = USER_COMMAND_TEXT.get(key)
    if not values:
        return key
    index = {"en": 0, "fa": 1, "ru": 2}.get(lang, 0)
    return values[index].format(**kwargs)


@dp.callback_query(F.data.startswith("user:"))
async def user_menu_actions(q: CallbackQuery):
    if not q.from_user:
        await q.answer()
        return
    uid = q.from_user.id
    action = q.data.split(":", 1)[1]
    user_upsert_from_id(uid, q.from_user.username or "")
    lang = get_user_lang(uid)
    if action == "language":
        prompts = {"en": "Choose your language:", "fa": "زبان خود را انتخاب کنید:", "ru": "Выберите язык:"}
        await q.message.answer(prompts[lang], reply_markup=language_keyboard())
        await q.answer()
        return
    if action == "balance":
        with db() as c:
            row = c.execute("SELECT balance,withdraw_after FROM users WHERE user_id=?", (uid,)).fetchone()
            pool = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0]
        status = ut(lang, "status", date=row[1]) if row[1] else ut(lang, "inactive")
        text = ut(lang, "balance", balance=row[0], pool=pool, status=status)
    elif action == "mine":
        t = now()
        with db() as c:
            row = c.execute("SELECT last_mine FROM users WHERE user_id=?", (uid,)).fetchone()
            pool = int(c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0])
            if row[0] and t - datetime.fromisoformat(row[0]) < timedelta(hours=1):
                left = timedelta(hours=1) - (t - datetime.fromisoformat(row[0]))
                text = ut(lang, "mine_wait", left=str(left).split('.')[0])
            else:
                reward = min(HOURLY_REWARD, pool)
                if reward <= 0:
                    text = ut(lang, "mine_empty")
                else:
                    c.execute("UPDATE users SET balance=balance+?,last_mine=? WHERE user_id=?", (reward, t.isoformat(), uid))
                    pool_change(c, -reward)
                    text = ut(lang, "mine_ok", reward=reward)
    elif action == "tasks":
        with db() as c:
            rows = c.execute("SELECT id,title,reward FROM tasks WHERE active=1").fetchall()
        text = "\n".join([f"{i}. {title} — {reward} GRM" for i,title,reward in rows]) or ut(lang, "tasks_empty")
        if rows:
            text += ut(lang, "claim_hint")
    elif action == "lottery":
        with db() as c:
            lot = c.execute("SELECT id FROM lotteries WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
            if not lot:
                text = ut(lang, "lottery_none")
            else:
                try:
                    c.execute("INSERT INTO lottery_entries(lottery_id,user_id) VALUES(?,?)", (lot[0], uid))
                    text = ut(lang, "lottery_ok")
                except sqlite3.IntegrityError:
                    text = ut(lang, "lottery_dup")
    elif action == "wallet":
        text = ut(lang, "wallet")
    elif action == "withdraw":
        text = ut(lang, "withdraw")
    elif action == "trade":
        text = ut(lang, "trade")
    elif action == "activate":
        text = ut(lang, "activate", fee=ACTIVATION_FEE, wallet=COMPANY_WALLET)
    else:
        text = ut(lang, "invalid")
    markup = copy_text_keyboard(COMPANY_WALLET, ut(lang, "copy_company")) if action == "activate" and COMPANY_WALLET else user_menu_keyboard(lang)
    await q.message.answer(text, reply_markup=markup)
    await q.answer()

def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 کاربران", callback_data="panel:users"),
         InlineKeyboardButton(text="📋 وظایف", callback_data="panel:tasks")],
        [InlineKeyboardButton(text="🎟 قرعه‌کشی", callback_data="panel:lotteries"),
         InlineKeyboardButton(text="💸 برداشت‌ها", callback_data="panel:withdrawals")],
        [InlineKeyboardButton(text="🤝 معاملات", callback_data="panel:trades"),
         InlineKeyboardButton(text="⛏ استخر استخراج", callback_data="panel:pool")],
    ])

@dp.message(Command("admin"))
async def admin_panel(m: Message):
    if not is_admin(m):
        await m.answer("این بخش فقط برای مدیر است.")
        return
    await m.answer("⚙️ پنل مدیریت GRM Mining\nیک بخش را انتخاب کنید:", reply_markup=admin_panel_keyboard())

@dp.callback_query(F.data.startswith("panel:"))
async def admin_panel_sections(q: CallbackQuery):
    if not q.from_user or q.from_user.id != ADMIN_ID:
        await q.answer("دسترسی فقط برای مدیر مجاز است.", show_alert=True)
        return
    section = q.data.split(":", 1)[1]
    with db() as c:
        if section == "users":
            total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active = c.execute("SELECT COUNT(*) FROM users WHERE withdraw_after IS NOT NULL").fetchone()[0]
            text = f"👥 کاربران ثبت‌شده: {total}\nفعال‌سازی تأییدشده: {active}"
        elif section == "tasks":
            rows = c.execute("SELECT id,title,reward,active FROM tasks ORDER BY id DESC LIMIT 20").fetchall()
            text = "📋 وظایف (۲۰ مورد آخر):\n" + ("\n".join([f"#{i} {title} — {reward} GRM | {'فعال' if a else 'غیرفعال'}" for i,title,reward,a in rows]) or "هنوز وظیفه‌ای ثبت نشده است.")
            text += "\n\nافزودن: /addtask عنوان 25"
        elif section == "lotteries":
            rows = c.execute("SELECT id,prize,status,winner_id FROM lotteries ORDER BY id DESC LIMIT 20").fetchall()
            text = "🎟 قرعه‌کشی‌ها:\n" + ("\n".join([f"#{i} جایزه {p} GRM | {st} | برنده: {w or 'ندارد'}" for i,p,st,w in rows]) or "قرعه‌کشی‌ای ثبت نشده است.")
            text += "\n\nایجاد: /lottery_create 1000\nانتخاب برنده: /lottery_draw شماره"
        elif section == "withdrawals":
            rows = c.execute("SELECT id,user_id,amount,net,wallet FROM withdrawals WHERE status='pending' ORDER BY id").fetchall()
            text = "💸 درخواست‌های برداشت در انتظار:\n" + ("\n".join([f"#{i} | کاربر {u} | مبلغ {a} | خالص {n} GRM | {w}" for i,u,a,n,w in rows]) or "درخواستی در انتظار نیست.")
            buttons = [[InlineKeyboardButton(text=f"رد #{i} ↩️", callback_data=f"wd:reject:{i}"),
                        InlineKeyboardButton(text=f"تأیید #{i} ✓", callback_data=f"wd:approve:{i}")]
                       + ([InlineKeyboardButton(text=f"📋 کپی والت #{i}", copy_text=CopyTextButton(text=w))] if w else [])
                       for i,_,_,_,w in rows[:10]]
            if buttons:
                await q.message.answer("اقدام برای درخواست:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        elif section == "trades":
            rows = c.execute("SELECT id,user_id,details FROM trades WHERE status='pending' ORDER BY id").fetchall()
            text = "🤝 معاملات در انتظار:\n" + ("\n".join([f"#{i} | کاربر {u}: {d}" for i,u,d in rows]) or "معامله‌ای در انتظار نیست.")
            buttons = [[InlineKeyboardButton(text=f"رد #{i} ✕", callback_data=f"tr:reject:{i}"),
                        InlineKeyboardButton(text=f"تأیید #{i} ✓", callback_data=f"tr:approve:{i}")] for i,_,_ in rows[:10]]
            if buttons:
                await q.message.answer("اقدام برای معامله:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        elif section == "pool":
            pool = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
            text = f"⛏ موجودی استخر: {pool[0] if pool else POOL_START} GRM\nبرای تنظیم: /pool مقدار"
        else:
            text = "بخش پیدا نشد."
    await q.message.answer(text, reply_markup=admin_panel_keyboard())
    await q.answer()

@dp.callback_query(F.data.startswith("wd:"))
async def admin_withdraw_action(q: CallbackQuery):
    if not q.from_user or q.from_user.id != ADMIN_ID:
        await q.answer("فقط مدیر مجاز است.", show_alert=True)
        return
    _, action, raw_id = q.data.split(":")
    if not raw_id.isdigit() or action not in ("approve", "reject"):
        await q.answer("درخواست نامعتبر است.", show_alert=True)
        return
    req_id = int(raw_id)
    with db() as c:
        row = c.execute("SELECT user_id,amount,net,status FROM withdrawals WHERE id=?", (req_id,)).fetchone()
        if not row or row[3] != "pending":
            await q.answer("این درخواست دیگر در انتظار نیست.", show_alert=True)
            return
        if action == "approve":
            c.execute("UPDATE withdrawals SET status='approved' WHERE id=? AND status='pending'", (req_id,))
            result = f"درخواست #{req_id} تأیید شد. مبلغ خالص {row[2]} GRM را دستی پرداخت کنید و سپس /paid {req_id} TX_HASH را بزنید."
        else:
            c.execute("UPDATE withdrawals SET status='rejected' WHERE id=? AND status='pending'", (req_id,))
            pool_change(c, row[1])
            result = f"درخواست #{req_id} رد شد و {row[1]} GRM به استخر برگشت."
    await q.message.answer(result, reply_markup=admin_panel_keyboard())
    await q.answer("انجام شد.")

@dp.callback_query(F.data.startswith("tr:"))
async def admin_trade_action(q: CallbackQuery):
    if not q.from_user or q.from_user.id != ADMIN_ID:
        await q.answer("فقط مدیر مجاز است.", show_alert=True)
        return
    _, action, raw_id = q.data.split(":")
    if not raw_id.isdigit() or action not in ("approve", "reject"):
        await q.answer("درخواست نامعتبر است.", show_alert=True)
        return
    status = "approved" if action == "approve" else "rejected"
    with db() as c:
        cur = c.execute("UPDATE trades SET status=? WHERE id=? AND status='pending'", (status, int(raw_id)))
    await q.message.answer(f"معامله #{raw_id}: {'تأیید' if action == 'approve' else 'رد'} شد." if cur.rowcount else "این معامله دیگر در انتظار نیست.", reply_markup=admin_panel_keyboard())
    await q.answer("انجام شد.")

@dp.message(CommandStart())
async def start(m: Message):
    user_upsert(m)
    lang = get_user_lang(m.from_user.id)
    welcome = {
        "en": "Welcome to GRM Mining!\nChoose an option below.",
        "fa": "به ربات GRM Mining خوش آمدید!\nیکی از گزینه‌های زیر را انتخاب کنید.",
        "ru": "Добро пожаловать в GRM Mining!\nВыберите действие ниже."
    }
    await m.answer(
        welcome[lang] + ("\n/admin — admin panel" if is_admin(m) else ""),
        reply_markup=admin_panel_keyboard() if is_admin(m) else user_menu_keyboard(lang)
    )

@dp.message(Command("balance"))
@dp.message(Command("balance"))
async def balance(m: Message):
    user_upsert(m)
    lang = get_user_lang(m.from_user.id)
    with db() as c:
        row = c.execute("SELECT balance,withdraw_after FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
        pool = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0]
    status = ut(lang, "status", date=row[1]) if row[1] else ut(lang, "inactive")
    await m.answer(ut(lang, "balance", balance=row[0], pool=pool, status=status))

@dp.message(Command("mine"))
async def mine(m: Message):
    user_upsert(m)
    lang = get_user_lang(m.from_user.id)
    t = now()
    with db() as c:
        row = c.execute("SELECT last_mine FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
        pool = int(c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0])
        if row[0] and t - datetime.fromisoformat(row[0]) < timedelta(hours=1):
            left = timedelta(hours=1) - (t - datetime.fromisoformat(row[0]))
            await m.answer(ut(lang, "mine_wait", left=str(left).split('.')[0]))
            return
        reward = min(HOURLY_REWARD, pool)
        if reward <= 0:
            await m.answer(ut(lang, "mine_empty"))
            return
        c.execute("UPDATE users SET balance=balance+?,last_mine=? WHERE user_id=?", (reward, t.isoformat(), m.from_user.id))
        pool_change(c, -reward)
    await m.answer(ut(lang, "mine_ok", reward=reward))

@dp.message(Command("activate"))
@dp.message(Command("activate"))
async def activate(m: Message):
    user_upsert(m)
    lang = get_user_lang(m.from_user.id)
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) != 2 or len(parts[1].strip()) < 8:
        await m.answer(ut(lang, "activate", fee=ACTIVATION_FEE, wallet=COMPANY_WALLET), reply_markup=copy_text_keyboard(COMPANY_WALLET, ut(lang, "copy_company")))
        return
    tx = parts[1].strip()
    with db() as c:
        c.execute("UPDATE users SET activation_tx=?,activation_at=NULL,withdraw_after=NULL WHERE user_id=?", (tx, m.from_user.id))
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"Activation review request\nUser: {m.from_user.id}\nTX: {tx}\nExpected: {ACTIVATION_FEE} GRAM\nDestination: {COMPANY_WALLET}\nAfter checking TON explorer: /activation_ok {m.from_user.id}")
    await m.answer(uct(lang, "activation_pending", fee=ACTIVATION_FEE, wallet=COMPANY_WALLET), reply_markup=copy_text_keyboard(COMPANY_WALLET, ut(lang, "copy_company")))

@dp.message(Command("setwallet"))
@dp.message(Command("setwallet"))
async def setwallet(m: Message):
    p = (m.text or "").split(maxsplit=1)
    lang = get_user_lang(m.from_user.id)
    if len(p) != 2:
        await m.answer(uct(lang, "wallet",))
        return
    with db() as c:
        c.execute("UPDATE users SET wallet=? WHERE user_id=?", (p[1].strip(), m.from_user.id))
    await m.answer(uct(lang, "wallet_saved", wallet=p[1].strip()), reply_markup=copy_text_keyboard(p[1].strip(), ut(lang, "copy_wallet")))

@dp.message(Command("withdraw"))
async def withdraw(m: Message):
    p = (m.text or "").split()
    lang = get_user_lang(m.from_user.id)
    if len(p) != 2 or not p[1].isdigit() or int(p[1]) <= 0:
        await m.answer(uct(lang, "withdraw_usage"))
        return
    amount = int(p[1])
    with db() as c:
        u = c.execute("SELECT balance,wallet,withdraw_after FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
        if not u or not u[1]:
            await m.answer(uct(lang, "wallet_required"))
            return
        if not u[2] or now() < datetime.fromisoformat(u[2]):
            await m.answer(uct(lang, "withdraw_locked", fee=ACTIVATION_FEE, days=WAIT_DAYS))
            return
        if amount > u[0]:
            await m.answer(uct(lang, "insufficient"))
            return
        fee = amount * FEE_PERCENT // 100
        net = amount - fee
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, m.from_user.id))
        cur = c.execute("INSERT INTO withdrawals(user_id,amount,fee,net,wallet,created_at) VALUES(?,?,?,?,?,?)", (m.from_user.id, amount, fee, net, u[1], now().isoformat()))
        req_id = cur.lastrowid
    await m.answer(uct(lang, "withdraw_created", id=req_id, amount=amount, percent=FEE_PERCENT, fee=fee, net=net))
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"Withdrawal #{req_id}\nUser: {m.from_user.id}\nGross: {amount}\nNet: {net}\nWallet: {u[1]}\nReview: /pending")

@dp.message(Command("tasks"))
@dp.message(Command("tasks"))
async def tasks(m: Message):
    lang = get_user_lang(m.from_user.id)
    with db() as c:
        rows = c.execute("SELECT id,title,reward FROM tasks WHERE active=1").fetchall()
    await m.answer("\n".join([f"{i}. {title} — {reward} GRM" for i,title,reward in rows]) or uct(lang, "tasks_empty"))

@dp.message(Command("claim"))
async def claim(m: Message):
    p = (m.text or "").split()
    lang = get_user_lang(m.from_user.id)
    if len(p) != 2 or not p[1].isdigit():
        await m.answer(uct(lang, "claim_usage"))
        return
    tid = int(p[1])
    with db() as c:
        task = c.execute("SELECT reward FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
        if not task:
            await m.answer(uct(lang, "task_missing"))
            return
        try:
            c.execute("INSERT INTO task_claims(user_id,task_id) VALUES(?,?)", (m.from_user.id,tid))
        except sqlite3.IntegrityError:
            await m.answer(uct(lang, "task_duplicate"))
            return
        pool = int(c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0])
        reward = min(task[0], pool)
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward,m.from_user.id))
        pool_change(c,-reward)
    await m.answer(uct(lang, "task_paid", reward=reward))

@dp.message(Command("trade"))
@dp.message(Command("trade"))
async def trade(m: Message):
    p=(m.text or "").split(maxsplit=1)
    lang = get_user_lang(m.from_user.id)
    if len(p)!=2:
        await m.answer(uct(lang, "trade_usage"))
        return
    with db() as c:
        cur=c.execute("INSERT INTO trades(user_id,details) VALUES(?,?)",(m.from_user.id,p[1]))
        tid=cur.lastrowid
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID,f"New trade #{tid} from user {m.from_user.id}: {p[1]}\n/approve_trade {tid} or /reject_trade {tid}")
    await m.answer(uct(lang, "trade_sent"))

@dp.message(Command("lottery_join"))
async def lottery_join(m: Message):
    lang = get_user_lang(m.from_user.id)
    with db() as c:
        lot=c.execute("SELECT id FROM lotteries WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
        if not lot:
            await m.answer(uct(lang, "lottery_none"))
            return
        try:
            c.execute("INSERT INTO lottery_entries(lottery_id,user_id) VALUES(?,?)",(lot[0],m.from_user.id))
        except sqlite3.IntegrityError:
            await m.answer(uct(lang, "lottery_dup"))
            return
    await m.answer(uct(lang, "lottery_ok"))

@dp.message(Command("pending"))
async def pending(m: Message):
    if not is_admin(m): return
    with db() as c:
        rows=c.execute("SELECT id,user_id,amount,net,wallet FROM withdrawals WHERE status='pending'").fetchall()
    await m.answer("\n".join([f"#{i} user={u} gross={a} net={n} wallet={w}" for i,u,a,n,w in rows]) or "درخواست معلقی نیست.")

@dp.message(Command("activation_ok"))
async def activation_ok(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit():
        await m.answer("روش استفاده: /activation_ok USER_ID")
        return
    uid=int(p[1]); start=now(); end=start+timedelta(days=WAIT_DAYS)
    with db() as c:
        row=c.execute("SELECT activation_tx FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or not row[0]:
            await m.answer("برای این کاربر تراکنش ثبت نشده است."); return
        c.execute("UPDATE users SET activation_at=?,withdraw_after=? WHERE user_id=?",(start.isoformat(),end.isoformat(),uid))
    await m.answer(f"فعال‌سازی کاربر {uid} تأیید شد. برداشت از {end.isoformat()} مجاز می‌شود.")
    await bot.send_message(uid,f"پرداخت فعال‌سازی شما تأیید شد. امکان برداشت از {end.strftime('%Y-%m-%d %H:%M UTC')} فعال می‌شود.")

@dp.message(Command("approve"))
async def approve(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit(): await m.answer("روش استفاده: /approve REQUEST_ID"); return
    with db() as c: c.execute("UPDATE withdrawals SET status='approved' WHERE id=? AND status='pending'",(int(p[1]),))
    await m.answer("درخواست تأیید شد. مبلغ خالص را دستی به کیف پول کاربر ارسال کنید؛ سپس /paid REQUEST_ID TX_HASH را ثبت کنید.")

@dp.message(Command("reject"))
async def reject(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit(): await m.answer("روش استفاده: /reject REQUEST_ID"); return
    with db() as c:
        r=c.execute("SELECT user_id,amount FROM withdrawals WHERE id=? AND status IN ('pending','approved')",(int(p[1]),)).fetchone()
        if not r: await m.answer("درخواست پیدا نشد یا قبلاً نهایی شده است."); return
        c.execute("UPDATE withdrawals SET status='rejected' WHERE id=?",(int(p[1]),))
        pool_change(c,r[1])
    await m.answer("درخواست رد شد و مبلغ به استخر استخراج برگشت.")

@dp.message(Command("paid"))
async def paid(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)!=3 or not p[1].isdigit(): await m.answer("روش استفاده: /paid REQUEST_ID TX_HASH"); return
    with db() as c:
        r=c.execute("SELECT user_id FROM withdrawals WHERE id=? AND status='approved'",(int(p[1]),)).fetchone()
        if not r: await m.answer("درخواست تأییدشده پیدا نشد."); return
        c.execute("UPDATE withdrawals SET status='paid',tx_hash=? WHERE id=?",(p[2],int(p[1])))
    await m.answer("پرداخت به‌عنوان انجام‌شده ثبت شد.")
    await bot.send_message(r[0],f"برداشت شما پرداخت شد. شناسه تراکنش: {p[2]}")

@dp.message(Command("addtask"))
async def addtask(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)!=3 or not p[2].isdigit(): await m.answer("روش استفاده: /addtask عنوان | دستور واقعی: /addtask عنوان 25"); return
    with db() as c: c.execute("INSERT INTO tasks(title,reward) VALUES(?,?)",(p[1],int(p[2])))
    await m.answer("وظیفه اضافه شد.")

@dp.message(Command("pool"))
async def pool(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split()
    with db() as c:
        if len(p)==2 and p[1].isdigit(): c.execute("UPDATE settings SET value=? WHERE key='pool'",(p[1],))
        val=c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0]
    await m.answer(f"استخر فعلی: {val} GRM")

@dp.message(Command("approve_trade"))
async def approve_trade(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split()
    if len(p)==2 and p[1].isdigit():
        with db() as c: c.execute("UPDATE trades SET status='approved' WHERE id=? AND status='pending'",(int(p[1]),))
        await m.answer("معامله تأیید شد.")

@dp.message(Command("reject_trade"))
async def reject_trade(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split()
    if len(p)==2 and p[1].isdigit():
        with db() as c: c.execute("UPDATE trades SET status='rejected' WHERE id=? AND status='pending'",(int(p[1]),))
        await m.answer("معامله رد شد.")

@dp.message(Command("lottery_create"))
async def lottery_create(m: Message):
    if not is_admin(m): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit(): await m.answer("روش استفاده: /lottery_create PRIZE_GRM"); return
    with db() as c:
        pool=int(c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0])
        prize=min(int(p[1]),pool)
        cur=c.execute("INSERT INTO lotteries(prize) VALUES(?)",(prize,))
    await m.answer(f"قرعه‌کشی #{cur.lastrowid} با جایزه {prize} GRM ایجاد شد.")

@dp.message(Command("lottery_draw"))
async def lottery_draw(m: Message):
    if not is_admin(m): return
    import secrets
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit(): await m.answer("روش استفاده: /lottery_draw LOTTERY_ID"); return
    with db() as c:
        lot=c.execute("SELECT prize,status FROM lotteries WHERE id=?",(int(p[1]),)).fetchone()
        entries=[x[0] for x in c.execute("SELECT user_id FROM lottery_entries WHERE lottery_id=?",(int(p[1]),)).fetchall()]
        if not lot or lot[1]!='open' or not entries: await m.answer("قرعه‌کشی باز یا شرکت‌کننده‌ای ندارد."); return
        winner=secrets.choice(entries)
        c.execute("UPDATE lotteries SET status='drawn',winner_id=? WHERE id=?",(winner,int(p[1])))
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(lot[0],winner))
        pool_change(c,-lot[0])
    await m.answer(f"برنده قرعه‌کشی: {winner}؛ جایزه {lot[0]} GRM به موجودی داخلی افزوده شد.")

async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN را در فایل .env تنظیم کنید.")
    if not ADMIN_ID:
        raise RuntimeError("ADMIN_ID را در فایل .env تنظیم کنید.")
    init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="شروع ربات"),
        BotCommand(command="balance", description="مشاهده موجودی"),
        BotCommand(command="mine", description="استخراج ساعتی GRM"),
        BotCommand(command="activate", description="ثبت تراکنش فعال‌سازی"),
        BotCommand(command="setwallet", description="ثبت آدرس کیف پول"),
        BotCommand(command="withdraw", description="درخواست برداشت"),
        BotCommand(command="tasks", description="مشاهده وظایف"),
        BotCommand(command="claim", description="دریافت پاداش وظیفه"),
        BotCommand(command="trade", description="درخواست معامله"),
        BotCommand(command="lottery_join", description="شرکت در قرعه‌کشی"),
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
