import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, BotCommandScopeChat, CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message
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
            withdraw_after TEXT, lang TEXT DEFAULT 'en',
            referred_by INTEGER, referral_rewarded INTEGER DEFAULT 0,
            checkin_day INTEGER DEFAULT 0, last_checkin_date TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS balance_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            change_amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            reference TEXT,
            created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
            fee INTEGER, net INTEGER, wallet TEXT, status TEXT DEFAULT 'pending',
            tx_hash TEXT, created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, reward INTEGER,
            active INTEGER DEFAULT 1)""")
        task_cols = [row[1] for row in c.execute("PRAGMA table_info(tasks)").fetchall()]
        for col in ("title_en", "title_fa", "title_ru", "desc_en", "desc_fa", "desc_ru"):
            if col not in task_cols:
                c.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT")
        c.execute("UPDATE tasks SET title_en=COALESCE(title_en,title), title_fa=COALESCE(title_fa,title), title_ru=COALESCE(title_ru,title)")
        c.execute("""CREATE TABLE IF NOT EXISTS task_claims(
            user_id INTEGER, task_id INTEGER, PRIMARY KEY(user_id, task_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS task_submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            evidence TEXT NOT NULL,
            media_file_id TEXT,
            media_type TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            reviewed_at TEXT)""")
        submission_cols = [row[1] for row in c.execute("PRAGMA table_info(task_submissions)").fetchall()]
        for col in ("media_file_id", "media_type"):
            if col not in submission_cols:
                c.execute(f"ALTER TABLE task_submissions ADD COLUMN {col} TEXT")
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
        for col, definition in (("referred_by", "INTEGER"), ("referral_rewarded", "INTEGER DEFAULT 0"),
                                ("checkin_day", "INTEGER DEFAULT 0"), ("last_checkin_date", "TEXT")):
            if col not in cols:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('pool',?)", (str(POOL_START),))

def is_admin(m: Message):
    return m.from_user and m.from_user.id == ADMIN_ID


MIN_WITHDRAWAL = 17000
DAILY_CHECKIN_DAYS = 30

def is_user_activated(user_id: int) -> bool:
    with db() as c:
        row = c.execute("SELECT activation_at FROM users WHERE user_id=?", (user_id,)).fetchone()
    return bool(row and row[0])

def activation_prompt(lang: str) -> str:
    texts = {
        "en": f"Activation is required before mining. First set your wallet with /setwallet WALLET_ADDRESS, then pay {ACTIVATION_FEE} GRAM to the company wallet and submit /activate TX_HASH. Admin confirmation is required. Company wallet: {COMPANY_WALLET}",
        "fa": f"پیش از ماین باید حساب فعال شود. ابتدا با /setwallet آدرس والت را ثبت کنید، سپس {ACTIVATION_FEE} GRAM به والت شرکت بفرستید و /activate TX_HASH را ارسال کنید. تأیید مدیر الزامی است. والت شرکت: {COMPANY_WALLET}",
        "ru": f"Перед майнингом активируйте аккаунт: укажите кошелёк через /setwallet, отправьте {ACTIVATION_FEE} GRAM на кошелёк компании и пришлите /activate TX_HASH. Требуется подтверждение администратора. Кошелёк: {COMPANY_WALLET}"
    }
    return texts.get(lang, texts["en"])

def activation_keyboard(lang):
    label = {"en":"💳 Activate account", "fa":"💳 فعال‌سازی حساب", "ru":"💳 Активировать аккаунт"}.get(lang, "💳 Activate account")
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data="user:activate")]])

def referral_text(lang, link, count, total):
    texts = {
        "en": f"Referral link: {link}\nSuccessful referrals: {count}\nEarned: {total} GRM. You receive 500 GRM only after the invited user pays 0.5 GRAM and admin confirms activation.",
        "fa": f"لینک دعوت: {link}\nدعوت‌های موفق: {count}\nمجموع پاداش: {total} GRM. پس از پرداخت ۰٫۵ GRAM توسط دعوت‌شده و تأیید مدیر، ۵۰۰ GRM دریافت می‌کنید.",
        "ru": f"Реферальная ссылка: {link}\nУспешные приглашения: {count}\nНачислено: {total} GRM. Награда 500 GRM начисляется после оплаты приглашённым 0.5 GRAM и подтверждения администратором."
    }
    return texts.get(lang, texts["en"])

async def daily_checkin(user_id: int, lang: str) -> str:
    today = now().date().isoformat()
    with db() as c:
        row = c.execute("SELECT activation_at,checkin_day,last_checkin_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row[0]:
            return activation_prompt(lang)
        if row[2] == today:
            return {"en":"Already checked in today.", "fa":"امروز قبلاً چک‌این کرده‌اید.", "ru":"Сегодня вы уже отметились."}[lang]
        if int(row[1] or 0) >= DAILY_CHECKIN_DAYS:
            return {"en":"You have completed all 30 check-ins. The withdrawal check-in requirement is satisfied.", "fa":"هر ۳۰ نوبت دیلی‌چک‌این را تکمیل کرده‌اید و شرط چک‌این برداشت انجام شده است.", "ru":"Все 30 отметок завершены. Условие для вывода выполнено."}[lang]
        day = int(row[1] or 0) + 1
        reward = day * 50
        pool_row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
        pool = int(pool_row[0]) if pool_row else 0
        reward = min(reward, pool)
        if reward <= 0:
            return {"en":"Mining pool is empty.", "fa":"استخر پاداش خالی است.", "ru":"Пул наград пуст."}[lang]
        c.execute("UPDATE users SET checkin_day=?,last_checkin_date=?,balance=balance+? WHERE user_id=?", (day,today,reward,user_id))
        log_balance(c,user_id,reward,"daily_checkin",day)
        pool_change(c,-reward)
    messages = {
        "en": f"Check-in {day}/30 complete. Reward: {reward} GRM. Missed days pause progress; next check-in continues from the next number.",
        "fa": f"چک‌این روز {day} از ۳۰ تکمیل شد. پاداش: {reward} GRM. روزهای جاافتاده شمارش را متوقف می‌کنند؛ دفعه بعد از شماره بعدی ادامه می‌دهید.",
        "ru": f"Отметка {day}/30 выполнена. Награда: {reward} GRM. Пропущенные дни приостанавливают прогресс; следующая отметка продолжит со следующего номера."
    }
    return messages[lang]

def user_upsert(m: Message):
    with db() as c:
        c.execute("INSERT INTO users(user_id,username) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                  (m.from_user.id, m.from_user.username or ""))

def log_balance(c, user_id, change_amount, reason, reference=None):
    c.execute(
        "INSERT INTO balance_history(user_id,change_amount,reason,reference,created_at) VALUES(?,?,?,?,?)",
        (user_id, change_amount, reason, str(reference) if reference is not None else None, now().isoformat())
    )


def pool_change(c, delta):
    row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
    current = int(row[0]) if row else POOL_START
    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('pool',?)", (str(max(0, current + delta)),))

bot = Bot(TOKEN)
dp = Dispatcher()


@dp.message(Command("checkin"))
async def checkin_command(m: Message):
    await m.answer(await daily_checkin(m.from_user.id, get_user_lang(m.from_user.id)))

@dp.message(Command("referral"))
async def referral_command(m: Message):
    user_upsert(m)
    lang = get_user_lang(m.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{m.from_user.id}"
    with db() as c:
        count = c.execute("SELECT COUNT(*) FROM users WHERE referred_by=? AND referral_rewarded=1", (m.from_user.id,)).fetchone()[0]
    await m.answer(referral_text(lang, link, count, count * 500))

@dp.message(Command("referrals"))
async def referrals_admin(m: Message):
    if not is_admin(m):
        return
    with db() as c:
        rows = c.execute("SELECT user_id,referred_by,referral_rewarded FROM users WHERE referred_by IS NOT NULL ORDER BY user_id DESC LIMIT 100").fetchall()
    await m.answer("\n".join([f"user={u} inviter={inv} rewarded={bool(done)}" for u,inv,done in rows]) or "No referrals found.")



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
    "en": ["💰 My balance", "⛏ Hourly mining", "📋 Tasks", "🎟 Lottery", "👛 Set wallet", "💸 Withdraw", "🤝 Trade", "💳 Activate account", "🌐 Language", "📅 Daily check-in", "👥 Referrals"],
    "fa": ["💰 موجودی من", "⛏ استخراج ساعتی", "📋 وظایف", "🎟 قرعه‌کشی", "👛 ثبت کیف پول", "💸 درخواست برداشت", "🤝 معامله", "💳 فعال‌سازی حساب", "🌐 تغییر زبان", "📅 دیلی‌چک‌این", "👥 دعوت دوستان"],
    "ru": ["💰 Мой баланс", "⛏ Почасовая добыча", "📋 Задания", "🎟 Лотерея", "👛 Мой кошелёк", "💸 Вывод", "🤝 Сделка", "💳 Активация", "🌐 Язык", "📅 Ежедневный вход", "👥 Рефералы"],
}

def user_menu_keyboard(lang="en"):
    a = MENU_LABELS.get(lang, MENU_LABELS["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=a[0], callback_data="user:balance"), InlineKeyboardButton(text=a[1], callback_data="user:mine")],
        [InlineKeyboardButton(text=a[2], callback_data="user:tasks"), InlineKeyboardButton(text=a[3], callback_data="user:lottery")],
        [InlineKeyboardButton(text=a[4], callback_data="user:wallet"), InlineKeyboardButton(text=a[5], callback_data="user:withdraw")],
        [InlineKeyboardButton(text=a[6], callback_data="user:trade"), InlineKeyboardButton(text=a[7], callback_data="user:activate")],
        [InlineKeyboardButton(text=a[9], callback_data="user:checkin"), InlineKeyboardButton(text=a[10], callback_data="user:referral")],
        [InlineKeyboardButton(text=a[8], callback_data="user:language")],
    ])

def localized_task_text(row, lang):
    index = {"en": 0, "fa": 1, "ru": 2}.get(lang, 0)
    title = row[3 + index] or row[1]
    description = row[6 + index] or ""
    result = f"#{row[0]} {title} — {row[2]} GRM"
    return result + (f"\n{description}" if description else "")

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
  "balance": ("Balance: {balance} GRM\\nMining pool remaining: {pool} GRM\\n{status}", "موجودی: {balance} GRM\\nباقی‌مانده استخر: {pool} GRM\\n{status}", "Баланс: {balance} GRM\\nОстаток пула: {pool} GRM\\n{status}"),
  "activation_pending": ("Activation request submitted and is awaiting admin review. Required payment: {fee} GRAM\\nCompany wallet: {wallet}\\nThe 30-day period starts only after the admin verifies the payment.", "درخواست فعال‌سازی ثبت شد و منتظر بررسی مدیر است. مبلغ لازم: {fee} GRAM\\nکیف پول شرکت: {wallet}\\nمهلت ۳۰ روزه فقط پس از تأیید واقعی پرداخت توسط مدیر آغاز می‌شود.", "Заявка на активацию отправлена и ожидает проверки администратора. Сумма: {fee} GRAM\\nКошелёк компании: {wallet}\\n30-дневный срок начнётся только после проверки платежа администратором."),
  "wallet_saved": ("Wallet saved:\\n{wallet}\\nPlease verify the address carefully before requesting a withdrawal.", "آدرس کیف پول ذخیره شد:\\n{wallet}\\nپیش از درخواست برداشت، آدرس را با دقت بررسی کنید.", "Кошелёк сохранён:\\n{wallet}\\nПеред запросом вывода внимательно проверьте адрес."),
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
    if action not in ("activate", "wallet", "referral") and not is_user_activated(uid):
        await q.message.answer(activation_prompt(lang), reply_markup=copy_text_keyboard(COMPANY_WALLET, ut(lang, "copy_company")))
        await q.answer()
        return
    if action == "checkin":
        await q.message.answer(await daily_checkin(uid, lang))
        await q.answer()
        return
    if action == "referral":
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=ref{uid}"
        with db() as c:
            count = c.execute("SELECT COUNT(*) FROM users WHERE referred_by=? AND referral_rewarded=1", (uid,)).fetchone()[0]
        texts = {
            "en": f"Your referral link: {link}\nSuccessful referrals: {count}\nRewards earned: {count * 500} GRM. 500 GRM is credited after the invited user pays 0.5 GRAM and admin confirms activation.",
            "fa": f"لینک دعوت شما: {link}\nدعوت‌های موفق: {count}\nمجموع پاداش: {count * 500} GRM. پس از پرداخت ۰٫۵ GRAM توسط دعوت‌شده و تأیید مدیر، ۵۰۰ GRM به شما داده می‌شود.",
            "ru": f"Ваша ссылка: {link}\nУспешные приглашения: {count}\nНачислено: {count * 500} GRM. 500 GRM начисляются после оплаты 0.5 GRAM приглашённым и подтверждения администратором."
        }
        await q.message.answer(texts[lang])
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
                    log_balance(c, uid, reward, "hourly_mining")
                    pool_change(c, -reward)
                    text = ut(lang, "mine_ok", reward=reward)
    elif action == "tasks":
        with db() as c:
            rows = c.execute("SELECT id,title,reward,title_en,title_fa,title_ru,desc_en,desc_fa,desc_ru FROM tasks WHERE active=1").fetchall()
        text = "\n\n".join([localized_task_text(row, lang) for row in rows]) or ut(lang, "tasks_empty")
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

ADMIN_LABELS={"en":["Users","Tasks","Lottery","Withdrawals","Trades","Mining pool","Choose a section:"],"fa":["کاربران","وظایف","قرعه‌کشی","برداشت‌ها","معاملات","استخر استخراج","یک بخش را انتخاب کنید:"],"ru":["Пользователи","Задания","Лотерея","Выводы","Сделки","Пул майнинга","Выберите раздел:"]}
ADMIN_MESSAGES={
"en":{"users":"Registered users: {total}\nApproved activations: {active}","tasks":"Tasks (latest 20):\n{items}\n\nAdd: /addtask EN title | FA title | RU title | EN description | FA description | RU description | reward","tasks_empty":"No tasks have been added yet.","lotteries":"Lotteries:\n{items}\n\nCreate: /lottery_create 1000\nDraw: /lottery_draw LOTTERY_ID","lotteries_empty":"No lotteries found.","withdrawals":"Pending withdrawals:\n{items}","withdrawals_empty":"No pending requests.","trades":"Pending trades:\n{items}","trades_empty":"No pending trades.","pool":"Mining pool: {pool} GRM\nSet with: /pool AMOUNT","missing":"Section not found.","menu":"GRM Mining Admin Panel\n{menu}","only":"Administrator only.","action_withdraw":"Withdrawal actions:","action_trade":"Trade actions:"},
"fa":{"users":"کاربران ثبت‌شده: {total}\nفعال‌سازی تأییدشده: {active}","tasks":"وظایف (۲۰ مورد آخر):\n{items}\n\nافزودن: /addtask عنوان انگلیسی | عنوان فارسی | عنوان روسی | توضیح انگلیسی | توضیح فارسی | توضیح روسی | پاداش","tasks_empty":"هنوز وظیفه‌ای ثبت نشده است.","lotteries":"قرعه‌کشی‌ها:\n{items}\n\nایجاد: /lottery_create 1000\nانتخاب برنده: /lottery_draw شماره","lotteries_empty":"قرعه‌کشی‌ای ثبت نشده است.","withdrawals":"درخواست‌های برداشت در انتظار:\n{items}","withdrawals_empty":"درخواستی در انتظار نیست.","trades":"معاملات در انتظار:\n{items}","trades_empty":"معامله‌ای در انتظار نیست.","pool":"موجودی استخر: {pool} GRM\nبرای تنظیم: /pool مقدار","missing":"بخش پیدا نشد.","menu":"پنل مدیریت GRM Mining\n{menu}","only":"این بخش فقط برای مدیر است.","action_withdraw":"اقدام برای درخواست:","action_trade":"اقدام برای معامله:"},
"ru":{"users":"Зарегистрированные пользователи: {total}\nПодтверждённые активации: {active}","tasks":"Задания (последние 20):\n{items}\n\nДобавить: /addtask название EN | название FA | название RU | описание EN | описание FA | описание RU | награда","tasks_empty":"Заданий пока нет.","lotteries":"Лотереи:\n{items}\n\nСоздать: /lottery_create 1000\nРозыгрыш: /lottery_draw ID","lotteries_empty":"Лотерей пока нет.","withdrawals":"Ожидающие выводы:\n{items}","withdrawals_empty":"Нет ожидающих заявок.","trades":"Ожидающие сделки:\n{items}","trades_empty":"Ожидающих сделок нет.","pool":"Остаток пула: {pool} GRM\nИзменить: /pool СУММА","missing":"Раздел не найден.","menu":"Панель администратора GRM Mining\n{menu}","only":"Только для администратора.","action_withdraw":"Действия по заявке:","action_trade":"Действия по сделке:"}}
def admin_msg(lang,key,**kwargs):
    return ADMIN_MESSAGES.get(lang,ADMIN_MESSAGES["en"])[key].format(**kwargs)
def admin_panel_keyboard(lang="en"):
    x=ADMIN_LABELS.get(lang,ADMIN_LABELS["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 "+x[0],callback_data="panel:users"),InlineKeyboardButton(text="📋 "+x[1],callback_data="panel:tasks")],
        [InlineKeyboardButton(text="🎟 "+x[2],callback_data="panel:lotteries"),InlineKeyboardButton(text="💸 "+x[3],callback_data="panel:withdrawals")],
        [InlineKeyboardButton(text="🤝 "+x[4],callback_data="panel:trades"),InlineKeyboardButton(text="⛏ "+x[5],callback_data="panel:pool")],
        [InlineKeyboardButton(text="🌐 Language / زبان / Язык",callback_data="user:language")]])
@dp.message(Command("language"))
async def language_command(m: Message):
    user_upsert(m)
    lang = get_user_lang(m.from_user.id)
    prompts = {"en": "Choose your language:", "fa": "زبان خود را انتخاب کنید:", "ru": "Выберите язык:"}
    await m.answer(prompts[lang], reply_markup=language_keyboard())

@dp.message(Command("admin"))
async def admin_panel(m:Message):
    lang=get_user_lang(m.from_user.id)
    if not is_admin(m):
        await m.answer(admin_msg(lang,"only")); return
    await m.answer(admin_msg(lang,"menu",menu=ADMIN_LABELS[lang][6]),reply_markup=admin_panel_keyboard(lang))
@dp.callback_query(F.data.startswith("panel:"))
async def admin_panel_sections(q:CallbackQuery):
    if not q.from_user or q.from_user.id!=ADMIN_ID:
        await q.answer("Administrator only.",show_alert=True); return
    lang=get_user_lang(q.from_user.id); section=q.data.split(":",1)[1]
    with db() as c:
        if section=="users":
            total=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active=c.execute("SELECT COUNT(*) FROM users WHERE withdraw_after IS NOT NULL").fetchone()[0]
            text=admin_msg(lang,"users",total=total,active=active)
        elif section=="tasks":
            rows=c.execute("SELECT id,title,reward,title_en,title_fa,title_ru,desc_en,desc_fa,desc_ru,active FROM tasks ORDER BY id DESC LIMIT 20").fetchall()
            items="\n\n".join([localized_task_text(row[:9],lang)+(" | Active" if row[9] else " | Inactive") if lang=="en" else localized_task_text(row[:9],lang)+(" | فعال" if row[9] else " | غیرفعال") if lang=="fa" else localized_task_text(row[:9],lang)+(" | Активно" if row[9] else " | Неактивно") for row in rows]) or ADMIN_MESSAGES[lang]["tasks_empty"]
            text=admin_msg(lang,"tasks",items=items)
        elif section=="lotteries":
            rows=c.execute("SELECT id,prize,status,winner_id FROM lotteries ORDER BY id DESC LIMIT 20").fetchall()
            items="\n".join([f"#{i} | {p} GRM | {st} | winner: {w or '-'}" for i,p,st,w in rows]) or ADMIN_MESSAGES[lang]["lotteries_empty"]
            text=admin_msg(lang,"lotteries",items=items)
        elif section=="withdrawals":
            rows=c.execute("SELECT id,user_id,amount,net,wallet FROM withdrawals WHERE status='pending' ORDER BY id").fetchall()
            items="\n".join([f"#{i} | user {u} | gross {a} | net {n} GRM | {w}" for i,u,a,n,w in rows]) or ADMIN_MESSAGES[lang]["withdrawals_empty"]
            text=admin_msg(lang,"withdrawals",items=items)
            buttons=[[InlineKeyboardButton(text=(f"Reject #{i}" if lang=="en" else f"رد #{i}" if lang=="fa" else f"Отклонить #{i}"),callback_data=f"wd:reject:{i}"),InlineKeyboardButton(text=(f"Approve #{i}" if lang=="en" else f"تأیید #{i}" if lang=="fa" else f"Одобрить #{i}"),callback_data=f"wd:approve:{i}")]+([InlineKeyboardButton(text=f"📋 {w}",copy_text=CopyTextButton(text=w))] if w else []) for i,_,_,_,w in rows[:10]]
            if buttons: await q.message.answer(admin_msg(lang,"action_withdraw"),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        elif section=="trades":
            rows=c.execute("SELECT id,user_id,details FROM trades WHERE status='pending' ORDER BY id").fetchall()
            items="\n".join([f"#{i} | user {u}: {d}" for i,u,d in rows]) or ADMIN_MESSAGES[lang]["trades_empty"]
            text=admin_msg(lang,"trades",items=items)
            buttons=[[InlineKeyboardButton(text=(f"Reject #{i}" if lang=="en" else f"رد #{i}" if lang=="fa" else f"Отклонить #{i}"),callback_data=f"tr:reject:{i}"),InlineKeyboardButton(text=(f"Approve #{i}" if lang=="en" else f"تأیید #{i}" if lang=="fa" else f"Одобрить #{i}"),callback_data=f"tr:approve:{i}")] for i,_,_ in rows[:10]]
            if buttons: await q.message.answer(admin_msg(lang,"action_trade"),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        elif section=="pool":
            pool=c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
            text=admin_msg(lang,"pool",pool=pool[0] if pool else POOL_START)
        else: text=admin_msg(lang,"missing")
    await q.message.answer(text,reply_markup=admin_panel_keyboard(lang)); await q.answer()

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
    await q.message.answer(result, reply_markup=admin_panel_keyboard(get_user_lang(q.from_user.id)))
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
    payload = (m.text or "").split(maxsplit=1)
    if len(payload) == 2 and payload[1].startswith("ref") and payload[1][3:].isdigit():
        inviter = int(payload[1][3:])
        if inviter != m.from_user.id:
            with db() as c:
                c.execute("UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL AND activation_at IS NULL",
                          (inviter, m.from_user.id))
    lang = get_user_lang(m.from_user.id)
    welcome = {
        "en": "Welcome to GRM Mining!\nChoose an option below.",
        "fa": "به ربات GRM Mining خوش آمدید!\nیکی از گزینه‌های زیر را انتخاب کنید.",
        "ru": "Добро пожаловать в GRM Mining!\nВыберите действие ниже."
    }
    await m.answer(
        welcome[lang] + ("\n/admin — admin panel" if is_admin(m) else ""),
        reply_markup=admin_panel_keyboard(lang) if is_admin(m) else (user_menu_keyboard(lang) if is_user_activated(m.from_user.id) else activation_keyboard(lang))
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
    if not is_user_activated(m.from_user.id):
        await m.answer(activation_prompt(lang))
        return
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
        log_balance(c, m.from_user.id, reward, "hourly_mining")
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
    with db() as c:
        wallet_row = c.execute("SELECT wallet,activation_at FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
    if not wallet_row or not wallet_row[0]:
        await m.answer({"en":"Set your wallet first: /setwallet WALLET_ADDRESS","fa":"ابتدا والت خود را ثبت کنید: /setwallet آدرس_والت","ru":"Сначала укажите кошелёк: /setwallet АДРЕС"}[lang])
        return
    if wallet_row[1]:
        await m.answer({"en":"Account already activated.","fa":"حساب شما قبلاً فعال شده است.","ru":"Аккаунт уже активирован."}[lang])
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
    if amount < MIN_WITHDRAWAL:
        await m.answer({"en":"Minimum withdrawal is 17,000 GRM.","fa":"حداقل برداشت ۱۷٬۰۰۰ GRM است.","ru":"Минимальный вывод — 17 000 GRM."}[lang])
        return
    if not is_user_activated(m.from_user.id):
        await m.answer(activation_prompt(lang))
        return
    with db() as c:
        u = c.execute("SELECT balance,wallet,checkin_day FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
        if not u or not u[1]:
            await m.answer(uct(lang, "wallet_required"))
            return
        if int(u[2] or 0) < 30:
            await m.answer({"en":"Complete 30 successful daily check-ins before withdrawing.","fa":"برای برداشت باید ۳۰ نوبت دیلی‌چک‌این موفق تکمیل کنید.","ru":"Для вывода необходимо завершить 30 успешных отметок."}[lang])
            return
        if amount > u[0]:
            await m.answer(uct(lang, "insufficient"))
            return
        fee = amount * FEE_PERCENT // 100
        net = amount - fee
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, m.from_user.id))
        log_balance(c, m.from_user.id, -amount, "withdrawal_request")
        cur = c.execute("INSERT INTO withdrawals(user_id,amount,fee,net,wallet,created_at) VALUES(?,?,?,?,?,?)", (m.from_user.id, amount, fee, net, u[1], now().isoformat()))
        req_id = cur.lastrowid
    await m.answer(uct(lang, "withdraw_created", id=req_id, amount=amount, percent=FEE_PERCENT, fee=fee, net=net))
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"Withdrawal #{req_id}\nUser: {m.from_user.id}\nGross: {amount}\nNet: {net}\nWallet: {u[1]}\nReview: /pending")

@dp.message(Command("tasks"))
@dp.message(Command("tasks"))
async def tasks(m: Message):
    lang = get_user_lang(m.from_user.id)
    if not is_user_activated(m.from_user.id):
        await m.answer(activation_prompt(lang)); return
    with db() as c:
        rows = c.execute("SELECT id,title,reward,title_en,title_fa,title_ru,desc_en,desc_fa,desc_ru FROM tasks WHERE active=1").fetchall()
    await m.answer("\n\n".join([localized_task_text(row, lang) for row in rows]) or uct(lang, "tasks_empty"))

@dp.message(Command("claim"))
async def claim(m: Message):
    lang = get_user_lang(m.from_user.id)
    if not is_user_activated(m.from_user.id):
        await m.answer(activation_prompt(lang)); return
    raw = (m.text or m.caption or "").partition(" ")[2].strip()
    parts = raw.split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        examples = {
            "en": "Send /claim TASK_ID followed by text, or attach a screenshot/photo with caption /claim TASK_ID.",
            "fa": "دستور /claim شماره_وظیفه را همراه توضیح بفرستید؛ یا عکس/اسکرین‌شات را با زیرنویس /claim شماره_وظیفه ارسال کنید.",
            "ru": "Отправьте /claim ID_ЗАДАНИЯ с текстом или прикрепите фото/скриншот с подписью /claim ID_ЗАДАНИЯ."
        }
        await m.answer(examples[lang])
        return
    tid = int(parts[0])
    is_photo = bool(m.photo)
    evidence = (parts[1].strip() if len(parts) > 1 else "") or ("Photo evidence" if is_photo else "")
    if not evidence:
        await m.answer("Please add evidence text or attach a photo with the command in its caption.")
        return
    media_file_id = m.photo[-1].file_id if is_photo else None
    media_type = "photo" if is_photo else None
    with db() as c:
        task = c.execute("SELECT reward FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
        if not task:
            await m.answer(uct(lang, "task_missing"))
            return
        already_paid = c.execute("SELECT 1 FROM task_claims WHERE user_id=? AND task_id=?", (m.from_user.id, tid)).fetchone()
        if already_paid:
            await m.answer(uct(lang, "task_duplicate"))
            return
        pending = c.execute("SELECT id FROM task_submissions WHERE user_id=? AND task_id=? AND status='pending'", (m.from_user.id, tid)).fetchone()
        if pending:
            msgs = {"en": f"Your evidence is already waiting for review (submission #{pending[0]}).",
                    "fa": f"مدرک شما قبلاً ارسال شده و منتظر بررسی است (درخواست #{pending[0]}).",
                    "ru": f"Ваше доказательство уже ожидает проверки (заявка №{pending[0]})."}
            await m.answer(msgs[lang])
            return
        cur = c.execute(
            """INSERT INTO task_submissions(user_id,task_id,evidence,media_file_id,media_type,status,created_at)
               VALUES(?,?,?,?,?,'pending',?)""",
            (m.from_user.id, tid, evidence, media_file_id, media_type, now().isoformat())
        )
        submission_id = cur.lastrowid
    confirmations = {
        "en": f"Evidence submitted for task #{tid}. Reward: {task[0]} GRM. It will be credited only after admin approval. Submission #{submission_id}.",
        "fa": f"مدرک وظیفه #{tid} ارسال شد. پاداش: {task[0]} GRM. فقط پس از تأیید مدیر به موجودی افزوده می‌شود. درخواست #{submission_id}.",
        "ru": f"Доказательство для задания №{tid} отправлено. Награда: {task[0]} GRM. Она будет начислена только после одобрения администратора. Заявка №{submission_id}."
    }
    await m.answer(confirmations[lang])
    if ADMIN_ID:
        admin_caption = (
            f"Task submission #{submission_id}\\nUser: {m.from_user.id}\\nTask: #{tid}\\n"
            f"Reward: {task[0]} GRM\\nEvidence: {evidence}\\n"
            f"Approve: /task_approve {submission_id}\\nReject: /task_reject {submission_id}"
        )
        if media_file_id:
            await bot.send_photo(ADMIN_ID, media_file_id, caption=admin_caption)
        else:
            await bot.send_message(ADMIN_ID, admin_caption)

@dp.message(Command("task_pending"))
async def task_pending(m: Message):
    if not is_admin(m):
        return
    with db() as c:
        rows = c.execute(
            """SELECT s.id,s.user_id,s.task_id,t.reward,s.evidence,s.created_at,s.media_type
               FROM task_submissions s JOIN tasks t ON t.id=s.task_id
               WHERE s.status='pending' ORDER BY s.id"""
        ).fetchall()
    if not rows:
        await m.answer("No task submissions are waiting for review.")
        return
    lines = ["Pending task submissions:"]
    for sid, uid, tid, reward, evidence, created, media_type in rows:
        lines.append(f"#{sid} | user={uid} | task=#{tid} | reward={reward} GRM | {created}\nEvidence: {evidence}\nApprove: /task_approve {sid} | Reject: /task_reject {sid}")
    await m.answer("\n\n".join(lines))

@dp.message(Command("task_approve"))
async def task_approve(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("Usage: /task_approve SUBMISSION_ID")
        return
    sid = int(parts[1])
    with db() as c:
        row = c.execute(
            """SELECT s.user_id,s.task_id,t.reward,s.status
               FROM task_submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=?""", (sid,)
        ).fetchone()
        if not row or row[3] != "pending":
            await m.answer("Pending submission not found or already reviewed.")
            return
        uid, tid, requested_reward, _ = row
        already_paid = c.execute("SELECT 1 FROM task_claims WHERE user_id=? AND task_id=?", (uid, tid)).fetchone()
        pool_row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
        pool = int(pool_row[0]) if pool_row else 0
        if already_paid:
            c.execute("UPDATE task_submissions SET status='rejected',reviewed_at=? WHERE id=?", (now().isoformat(), sid))
            await m.answer("This user already received this task reward. Submission marked rejected.")
            return
        reward = min(int(requested_reward), pool)
        if reward <= 0:
            await m.answer("Mining pool is empty; submission remains pending.")
            return
        c.execute("INSERT INTO task_claims(user_id,task_id) VALUES(?,?)", (uid, tid))
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, uid))
        log_balance(c, uid, reward, "task_reward", tid)
        pool_change(c, -reward)
        c.execute("UPDATE task_submissions SET status='approved',reviewed_at=? WHERE id=?", (now().isoformat(), sid))
        user_row = c.execute("SELECT lang FROM users WHERE user_id=?", (uid,)).fetchone()
    await m.answer(f"Submission #{sid} approved. {reward} GRM credited to user {uid}.")
    lang = user_row[0] if user_row and user_row[0] in ("en","fa","ru") else "en"
    notices = {"en": f"Your evidence for task #{tid} was approved. {reward} GRM has been added to your balance.",
               "fa": f"مدرک وظیفه #{tid} تأیید شد و {reward} GRM به موجودی شما افزوده شد.",
               "ru": f"Ваше доказательство задания №{tid} одобрено. На баланс начислено {reward} GRM."}
    await bot.send_message(uid, notices[lang])

@dp.message(Command("task_reject"))
async def task_reject(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("Usage: /task_reject SUBMISSION_ID")
        return
    sid = int(parts[1])
    with db() as c:
        row = c.execute("SELECT user_id,task_id,status FROM task_submissions WHERE id=?", (sid,)).fetchone()
        if not row or row[2] != "pending":
            await m.answer("Pending submission not found or already reviewed.")
            return
        c.execute("UPDATE task_submissions SET status='rejected',reviewed_at=? WHERE id=?", (now().isoformat(), sid))
        user_row = c.execute("SELECT lang FROM users WHERE user_id=?", (row[0],)).fetchone()
    await m.answer(f"Submission #{sid} rejected.")
    lang = user_row[0] if user_row and user_row[0] in ("en","fa","ru") else "en"
    notices = {"en": f"Your evidence for task #{row[1]} was rejected. You may submit new evidence with /claim {row[1]}.",
               "fa": f"مدرک وظیفه #{row[1]} رد شد. می‌توانید مدرک تازه را با دستور /claim {row[1]} ارسال کنید.",
               "ru": f"Ваше доказательство задания №{row[1]} отклонено. Вы можете отправить новое командой /claim {row[1]}."}
    await bot.send_message(row[0], notices[lang])

@dp.message(Command("trade"))
@dp.message(Command("trade"))
async def trade(m: Message):
    p=(m.text or "").split(maxsplit=1)
    lang = get_user_lang(m.from_user.id)
    if not is_user_activated(m.from_user.id):
        await m.answer(activation_prompt(lang)); return
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
    if not is_user_activated(m.from_user.id):
        await m.answer(activation_prompt(lang)); return
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
        await m.answer("Usage: /activation_ok USER_ID")
        return
    uid=int(p[1]); start=now(); end=start+timedelta(days=WAIT_DAYS)
    with db() as c:
        row=c.execute("SELECT activation_tx,lang,referred_by,referral_rewarded,activation_at FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or not row[0]:
            await m.answer("No activation transaction found for this user."); return
        if row[4]:
            await m.answer("This user is already activated."); return
        c.execute("UPDATE users SET activation_at=?,withdraw_after=NULL WHERE user_id=?",(start.isoformat(),uid))
        inviter = row[2]
        pool_row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
        available_pool = int(pool_row[0]) if pool_row else 0
        reward_referral = bool(inviter and not row[3] and available_pool >= 500)
        if reward_referral:
            c.execute("UPDATE users SET balance=balance+500 WHERE user_id=?", (inviter,))
            log_balance(c, inviter, 500, "referral_reward", uid)
            pool_change(c, -500)
            c.execute("UPDATE users SET referral_rewarded=1 WHERE user_id=?", (uid,))
    await m.answer(f"Activation for user {uid} approved. 30 successful check-ins and a 17,000 GRM minimum balance are required for withdrawal.")
    lang = row[1] if row[1] in ("en","fa","ru") else "en"
    notices = {
        "en": "Your activation payment is confirmed. You may now mine and use the bot. Withdrawals require 30 successful daily check-ins and a minimum balance of 17,000 GRM.",
        "fa": "پرداخت فعال‌سازی شما تأیید شد. اکنون می‌توانید ماین و از ربات استفاده کنید. برداشت به ۳۰ نوبت دیلی‌چک‌این موفق و حداقل موجودی ۱۷٬۰۰۰ GRM نیاز دارد.",
        "ru": "Платёж за активацию подтверждён. Теперь доступен майнинг. Для вывода нужны 30 успешных ежедневных отметок и баланс не менее 17 000 GRM."
    }
    await bot.send_message(uid, notices[lang])
    if reward_referral:
        try:
            inviter_lang = get_user_lang(inviter)
            referral_notices = {"en": f"Your referral {uid} activated. 500 GRM was credited.",
                                "fa": f"دعوت‌شده شما ({uid}) فعال شد و ۵۰۰ GRM پاداش گرفتید.",
                                "ru": f"Ваш приглашённый пользователь {uid} активирован. Начислено 500 GRM."}
            await bot.send_message(inviter, referral_notices[inviter_lang])
        except Exception:
            pass

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
    if len(p)!=3 or not p[1].isdigit():
        await m.answer("Usage: /paid REQUEST_ID TX_HASH")
        return
    with db() as c:
        r=c.execute("SELECT user_id FROM withdrawals WHERE id=? AND status='approved'",(int(p[1]),)).fetchone()
        if not r: await m.answer("Approved withdrawal request not found."); return
        c.execute("UPDATE withdrawals SET status='paid',tx_hash=? WHERE id=?",(p[2],int(p[1])))
        user_row=c.execute("SELECT lang FROM users WHERE user_id=?",(r[0],)).fetchone()
    await m.answer("Payment marked as completed.")
    lang = user_row[0] if user_row and user_row[0] in ("en","fa","ru") else "en"
    notices = {
        "en": f"Your withdrawal has been paid. Transaction hash: {p[2]}",
        "fa": f"برداشت شما پرداخت شد. شناسه تراکنش: {p[2]}",
        "ru": f"Ваш вывод оплачен. Хеш транзакции: {p[2]}"
    }
    await bot.send_message(r[0], notices[lang])

@dp.message(Command("addtask"))
async def addtask(m: Message):
    if not is_admin(m):
        return
    raw = (m.text or "").partition(" ")[2].strip()
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) == 7 and parts[6].isdigit() and all(parts[:3]):
        en_title, fa_title, ru_title, en_desc, fa_desc, ru_desc = parts[:6]
        reward = int(parts[6])
    else:
        legacy = raw.rsplit(maxsplit=1)
        if len(legacy) != 2 or not legacy[1].isdigit() or not legacy[0].strip():
            await m.answer("Format: /addtask EN title | FA title | RU title | EN description | FA description | RU description | reward")
            return
        en_title = fa_title = ru_title = legacy[0].strip()
        en_desc = fa_desc = ru_desc = ""
        reward = int(legacy[1])
    with db() as c:
        c.execute("INSERT INTO tasks(title,reward,title_en,title_fa,title_ru,desc_en,desc_fa,desc_ru) VALUES(?,?,?,?,?,?,?,?)",
                  (en_title, reward, en_title, fa_title, ru_title, en_desc, fa_desc, ru_desc))
    await m.answer("Task added in English, Persian and Russian.")

@dp.message(Command("tasks_admin"))
async def tasks_admin(m: Message):
    if not is_admin(m):
        return
    with db() as c:
        rows = c.execute(
            "SELECT id, title_en, reward FROM tasks WHERE active=1 ORDER BY id"
        ).fetchall()
    if not rows:
        await m.answer("هیچ وظیفه فعالی وجود ندارد.")
        return
    lines = ["وظایف فعال (برای حذف: /deltask شناسه):"]
    lines.extend([f"#{task_id} — {title or 'بدون عنوان'} — {reward} GRM" for task_id, title, reward in rows])
    await m.answer("\n".join(lines))


@dp.message(Command("deltask"))
async def deltask(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("روش استفاده: /deltask TASK_ID\nبرای دیدن شناسه‌ها: /tasks_admin")
        return
    task_id = int(parts[1])
    with db() as c:
        row = c.execute("SELECT title_en FROM tasks WHERE id=? AND active=1", (task_id,)).fetchone()
        if not row:
            await m.answer("وظیفه فعال با این شناسه پیدا نشد.")
            return
        c.execute("UPDATE tasks SET active=0 WHERE id=? AND active=1", (task_id,))
    await m.answer(f"وظیفه #{task_id} غیرفعال شد و دیگر به کاربران نمایش داده نمی‌شود. سابقه آن در دیتابیس باقی ماند.")


@dp.message(Command("restoretask"))
async def restoretask(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("روش استفاده: /restoretask TASK_ID")
        return
    task_id = int(parts[1])
    with db() as c:
        cur = c.execute("UPDATE tasks SET active=1 WHERE id=? AND active=0", (task_id,))
    if cur.rowcount:
        await m.answer(f"وظیفه #{task_id} دوباره فعال شد و در فهرست کاربران نمایش داده می‌شود.")
    else:
        await m.answer("وظیفه غیرفعال با این شناسه پیدا نشد.")


@dp.message(Command("edittask"))
async def edittask(m: Message):
    if not is_admin(m):
        return
    raw = (m.text or "").partition(" ")[2].strip()
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 8 or not parts[0].isdigit() or not parts[7].isdigit() or int(parts[7]) <= 0 or not all(parts[1:4]):
        await m.answer(
            "روش استفاده:\\n/edittask ID | EN title | FA title | RU title | EN description | FA description | RU description | reward"
        )
        return
    task_id = int(parts[0])
    en_title, fa_title, ru_title, en_desc, fa_desc, ru_desc = parts[1:7]
    reward = int(parts[7])
    with db() as c:
        cur = c.execute(
            """UPDATE tasks SET title=?, title_en=?, title_fa=?, title_ru=?,
               desc_en=?, desc_fa=?, desc_ru=?, reward=?
               WHERE id=? AND active=1""",
            (en_title, en_title, fa_title, ru_title, en_desc, fa_desc, ru_desc, reward, task_id)
        )
    if cur.rowcount:
        await m.answer(f"وظیفه #{task_id} ویرایش شد. پاداش جدید فقط برای دریافت‌های بعدی اعمال می‌شود.")
    else:
        await m.answer("وظیفه فعال با این شناسه پیدا نشد. ابتدا /tasks_admin را بررسی کنید.")


@dp.message(Command("report"))
async def report(m: Message):
    if not is_admin(m):
        return
    with db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        balances = c.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0]
        pool = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0]
        tasks_count = c.execute("SELECT COUNT(*) FROM tasks WHERE active=1").fetchone()[0]
        pending_withdrawals = c.execute("SELECT COUNT(*),COALESCE(SUM(amount),0) FROM withdrawals WHERE status='pending'").fetchone()
        approved_withdrawals = c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='approved'").fetchone()[0]
        pending_trades = c.execute("SELECT COUNT(*) FROM trades WHERE status='pending'").fetchone()[0]
        open_lotteries = c.execute("SELECT COUNT(*) FROM lotteries WHERE status='open'").fetchone()[0]
    await m.answer(
        "گزارش کلی ربات\\n"
        f"کاربران ثبت‌شده: {users}\\n"
        f"مجموع موجودی کاربران: {balances} GRM\\n"
        f"باقی‌مانده استخر: {pool} GRM\\n"
        f"وظایف فعال: {tasks_count}\\n"
        f"برداشت‌های در انتظار: {pending_withdrawals[0]} (مجموع {pending_withdrawals[1]} GRM)\\n"
        f"برداشت‌های تأییدشده و پرداخت‌نشده: {approved_withdrawals}\\n"
        f"معاملات در انتظار: {pending_trades}\\n"
        f"قرعه‌کشی‌های باز: {open_lotteries}"
    )


@dp.message(Command("history"))
async def history(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("Usage: /history USER_ID")
        return
    uid = int(parts[1])
    with db() as c:
        exists = c.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone()
        rows = c.execute(
            "SELECT change_amount,reason,reference,created_at FROM balance_history WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (uid,)
        ).fetchall()
    if not exists:
        await m.answer("User not found.")
        return
    if not rows:
        await m.answer(f"No balance changes recorded yet for user {uid}.")
        return
    reason_names = {
        "hourly_mining": "Hourly mining",
        "task_reward": "Task reward",
        "withdrawal_request": "Withdrawal request",
        "lottery_prize": "Lottery prize"
    }
    lines = [f"Balance history for user {uid} (latest 20):"]
    for amount, reason, reference, created in rows:
        sign = "+" if amount > 0 else ""
        label = reason_names.get(reason, reason)
        ref_text = f" | Ref: {reference}" if reference else ""
        lines.append(f"{created} | {sign}{amount} GRM | {label}{ref_text}")
    await m.answer("\n".join(lines))


@dp.message(Command("user_info"))
async def user_info(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("روش استفاده: /user_info USER_ID")
        return
    uid = int(parts[1])
    with db() as c:
        row = c.execute(
            "SELECT username,balance,wallet,lang,activation_tx,activation_at,withdraw_after,last_mine FROM users WHERE user_id=?",
            (uid,)
        ).fetchone()
    if not row:
        await m.answer("کاربری با این شناسه پیدا نشد.")
        return
    username, balance, wallet, lang, activation_tx, activation_at, withdraw_after, last_mine = row
    lang_name = {"en": "English", "fa": "فارسی", "ru": "Русский"}.get(lang, "English")
    await m.answer(
        f"اطلاعات کاربر {uid}\\n"
        f"نام کاربری: @{username or 'ندارد'}\\n"
        f"موجودی: {balance} GRM\\n"
        f"کیف پول: {wallet or 'ثبت نشده'}\\n"
        f"زبان: {lang_name}\\n"
        f"شناسه تراکنش فعال‌سازی: {activation_tx or 'ثبت نشده'}\\n"
        f"زمان تأیید فعال‌سازی: {activation_at or 'تأیید نشده'}\\n"
        f"زمان مجاز برداشت: {withdraw_after or 'هنوز تعیین نشده'}\\n"
        f"آخرین استخراج: {last_mine or 'هنوز استخراج نکرده'}"
    )


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
        log_balance(c, winner, lot[0], "lottery_prize", p[1])
        pool_change(c,-lot[0])
    await m.answer(f"برنده قرعه‌کشی: {winner}؛ جایزه {lot[0]} GRM به موجودی داخلی افزوده شد.")

async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN را در فایل .env تنظیم کنید.")
    if not ADMIN_ID:
        raise RuntimeError("ADMIN_ID را در فایل .env تنظیم کنید.")
    init_db()
    # Commands visible to ordinary users
    await bot.set_my_commands([
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="balance", description="View your balance"),
        BotCommand(command="mine", description="Hourly GRM mining"),
        BotCommand(command="activate", description="Submit activation transaction"),
        BotCommand(command="setwallet", description="Set your wallet address"),
        BotCommand(command="withdraw", description="Request a withdrawal"),
        BotCommand(command="tasks", description="View available tasks"),
        BotCommand(command="claim", description="Submit task evidence for review"),
        BotCommand(command="trade", description="Request a trade"),
        BotCommand(command="lottery_join", description="Join the lottery"),
        BotCommand(command="checkin", description="Daily check-in"),
        BotCommand(command="referral", description="Get your referral link"),
    ])

    # Additional commands visible only in the administrator's command menu
    await bot.set_my_commands([
        BotCommand(command="pending", description="List pending withdrawals"),
        BotCommand(command="activation_ok", description="Confirm activation payment"),
        BotCommand(command="approve", description="Approve withdrawal"),
        BotCommand(command="reject", description="Reject withdrawal"),
        BotCommand(command="paid", description="Mark withdrawal as paid"),
        BotCommand(command="addtask", description="Add a multilingual task"),
        BotCommand(command="tasks_admin", description="List and manage tasks"),
        BotCommand(command="deltask", description="Deactivate a task"),
        BotCommand(command="restoretask", description="Restore a task"),
        BotCommand(command="edittask", description="Edit a task"),
        BotCommand(command="pool", description="View or set mining pool"),
        BotCommand(command="approve_trade", description="Approve a trade"),
        BotCommand(command="reject_trade", description="Reject a trade"),
        BotCommand(command="lottery_create", description="Create a lottery"),
        BotCommand(command="lottery_draw", description="Draw lottery winner"),
        BotCommand(command="report", description="View bot statistics report"),
        BotCommand(command="user_info", description="View a user's account details"),
        BotCommand(command="history", description="View a user balance history"),
        BotCommand(command="referrals", description="View referral records"),
        BotCommand(command="task_pending", description="Review task evidence"),
        BotCommand(command="task_approve", description="Approve task evidence"),
        BotCommand(command="task_reject", description="Reject task evidence"),
    ], scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
