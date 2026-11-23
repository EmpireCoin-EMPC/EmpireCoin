import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "bot.db")
COMPANY_WALLET = os.getenv("TON_COMPANY_WALLET", "")
HOURLY_REWARD = int(os.getenv("HOURLY_REWARD", "10"))
POOL_START = int(os.getenv("MINING_POOL", "172000000"))
FEE_PERCENT = int(os.getenv("WITHDRAWAL_FEE_PERCENT", "10"))
ACTIVATION_FEE = os.getenv("ACTIVATION_FEE_TON", "0.5")
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
            withdraw_after TEXT)""")
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

@dp.message(CommandStart())
async def start(m: Message):
    user_upsert(m)
    await m.answer(
        "سلام! به ربات GRM Mining خوش آمدید.\n"
        "/balance موجودی\n/mine استخراج ساعتی\n"
        "/activate TX_HASH ثبت تراکنش فعال‌سازی\n"
        "/setwallet آدرس_کیف_پول\n/withdraw مقدار درخواست برداشت\n"
        "/tasks مشاهده وظایف\n/claim شماره_وظیفه\n/trade توضیحات معامله\n/lottery_join ورود به قرعه‌کشی"
    )

@dp.message(Command("balance"))
async def balance(m: Message):
    user_upsert(m)
    with db() as c:
        row = c.execute("SELECT balance,withdraw_after FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
        pool = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0]
    status = f"زمان مجاز برداشت: {row[1]}" if row[1] else "فعال‌سازی 0.5 TON هنوز تأیید نشده است."
    await m.answer(f"موجودی: {row[0]} GRM\nاستخر باقی‌مانده: {pool} GRM\n{status}")

@dp.message(Command("mine"))
async def mine(m: Message):
    user_upsert(m)
    t = now()
    with db() as c:
        row = c.execute("SELECT last_mine FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
        pool = int(c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0])
        if row[0] and t - datetime.fromisoformat(row[0]) < timedelta(hours=1):
            left = timedelta(hours=1) - (t - datetime.fromisoformat(row[0]))
            await m.answer(f"هنوز یک ساعت کامل نشده است. زمان باقی‌مانده: {str(left).split('.')[0]}")
            return
        reward = min(HOURLY_REWARD, pool)
        if reward <= 0:
            await m.answer("استخر استخراج موجودی ندارد.")
            return
        c.execute("UPDATE users SET balance=balance+?,last_mine=? WHERE user_id=?",
                  (reward, t.isoformat(), m.from_user.id))
        pool_change(c, -reward)
    await m.answer(f"{reward} GRM به موجودی شما اضافه شد.")

@dp.message(Command("activate"))
async def activate(m: Message):
    user_upsert(m)
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) != 2 or len(parts[1].strip()) < 8:
        await m.answer("روش استفاده: /activate TX_HASH\nابتدا دقیقاً 0.5 TON به کیف پول شرکت بفرستید؛ سپس شناسه تراکنش را ثبت کنید. برداشت فقط 30 روز پس از تأیید تراکنش فعال می‌شود.")
        return
    tx = parts[1].strip()
    with db() as c:
        c.execute("UPDATE users SET activation_tx=?,activation_at=NULL,withdraw_after=NULL WHERE user_id=?", (tx, m.from_user.id))
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"درخواست بررسی فعال‌سازی\nکاربر: {m.from_user.id}\nTX: {tx}\nمبلغ مورد انتظار: {ACTIVATION_FEE} TON\nکیف پول مقصد: {COMPANY_WALLET}\nپس از بررسی در TON explorer: /activation_ok {m.from_user.id}")
    await m.answer("شناسه تراکنش ثبت شد و در انتظار بررسی مدیر است. زمان 30 روزه فقط پس از تأیید واقعی پرداخت شروع می‌شود.")

@dp.message(Command("setwallet"))
async def setwallet(m: Message):
    p = (m.text or "").split(maxsplit=1)
    if len(p) != 2:
        await m.answer("روش استفاده: /setwallet آدرس_کیف_پول_TON")
        return
    with db() as c:
        c.execute("UPDATE users SET wallet=? WHERE user_id=?", (p[1].strip(), m.from_user.id))
    await m.answer("آدرس کیف پول ذخیره شد. قبل از برداشت، آن را با دقت بررسی کنید.")

@dp.message(Command("withdraw"))
async def withdraw(m: Message):
    p = (m.text or "").split()
    if len(p) != 2 or not p[1].isdigit() or int(p[1]) <= 0:
        await m.answer("روش استفاده: /withdraw مقدار_GRM")
        return
    amount = int(p[1])
    with db() as c:
        u = c.execute("SELECT balance,wallet,withdraw_after FROM users WHERE user_id=?", (m.from_user.id,)).fetchone()
        if not u or not u[1]:
            await m.answer("ابتدا کیف پول TON خود را با /setwallet ثبت کنید.")
            return
        if not u[2] or now() < datetime.fromisoformat(u[2]):
            await m.answer(f"برداشت هنوز فعال نیست. ابتدا 0.5 TON را پرداخت و فعال‌سازی را تأیید کنید؛ سپس باید {WAIT_DAYS} روز از زمان تأیید بگذرد.")
            return
        if amount > u[0]:
            await m.answer("موجودی کافی نیست.")
            return
        fee = amount * FEE_PERCENT // 100
        net = amount - fee
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, m.from_user.id))
        cur = c.execute("INSERT INTO withdrawals(user_id,amount,fee,net,wallet,created_at) VALUES(?,?,?,?,?,?)",
                        (m.from_user.id, amount, fee, net, u[1], now().isoformat()))
        req_id = cur.lastrowid
    await m.answer(f"درخواست برداشت شماره {req_id} ثبت شد. مبلغ ناخالص: {amount} GRM؛ کارمزد {FEE_PERCENT}%: {fee}؛ مبلغ خالص: {net} GRM. پرداخت پس از تأیید مدیر به‌صورت دستی انجام می‌شود.")
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"برداشت #{req_id}\nکاربر: {m.from_user.id}\nمبلغ: {amount}\nخالص: {net}\nکیف پول: {u[1]}\nبرای بررسی: /pending")

@dp.message(Command("tasks"))
async def tasks(m: Message):
    with db() as c:
        rows = c.execute("SELECT id,title,reward FROM tasks WHERE active=1").fetchall()
    await m.answer("\n".join([f"{i}. {title} — {reward} GRM" for i,title,reward in rows]) or "فعلاً وظیفه‌ای ثبت نشده است.")

@dp.message(Command("claim"))
async def claim(m: Message):
    p = (m.text or "").split()
    if len(p) != 2 or not p[1].isdigit():
        await m.answer("روش استفاده: /claim شماره_وظیفه")
        return
    tid = int(p[1])
    with db() as c:
        task = c.execute("SELECT reward FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
        if not task:
            await m.answer("وظیفه پیدا نشد.")
            return
        try:
            c.execute("INSERT INTO task_claims(user_id,task_id) VALUES(?,?)", (m.from_user.id,tid))
        except sqlite3.IntegrityError:
            await m.answer("این وظیفه قبلاً ثبت شده است.")
            return
        pool = int(c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()[0])
        reward = min(task[0], pool)
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward,m.from_user.id))
        pool_change(c,-reward)
    await m.answer(f"{reward} GRM اضافه شد. توجه: ادعای انجام وظیفه در نسخه فعلی به‌صورت خوداظهاری است.")

@dp.message(Command("trade"))
async def trade(m: Message):
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2:
        await m.answer("روش استفاده: /trade توضیحات معامله")
        return
    with db() as c:
        cur=c.execute("INSERT INTO trades(user_id,details) VALUES(?,?)",(m.from_user.id,p[1]))
        tid=cur.lastrowid
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID,f"معامله جدید #{tid} از کاربر {m.from_user.id}: {p[1]}\n/approve_trade {tid} یا /reject_trade {tid}")
    await m.answer("درخواست معامله برای بررسی مدیر ارسال شد.")

@dp.message(Command("lottery_join"))
async def lottery_join(m: Message):
    with db() as c:
        lot=c.execute("SELECT id FROM lotteries WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
        if not lot:
            await m.answer("قرعه‌کشی فعالی وجود ندارد.")
            return
        try:
            c.execute("INSERT INTO lottery_entries(lottery_id,user_id) VALUES(?,?)",(lot[0],m.from_user.id))
        except sqlite3.IntegrityError:
            await m.answer("قبلاً در این قرعه‌کشی ثبت شده‌اید.")
            return
    await m.answer("در قرعه‌کشی ثبت شدید.")

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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
