import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "webapp"


def _db(path):
    return sqlite3.connect(path)


def _telegram_user(request, bot_token):
    raw = request.headers.get("Authorization", "")
    if not raw.startswith("Bearer "):
        raise web.HTTPUnauthorized(text="Telegram authorization is required")
    init_data = raw[7:]
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = pairs.pop("hash")
        auth_date = int(pairs["auth_date"])
        user = json.loads(pairs["user"])
    except Exception:
        raise web.HTTPUnauthorized(text="Invalid Telegram init data")
    if time.time() - auth_date > 86400 or auth_date > time.time() + 60:
        raise web.HTTPUnauthorized(text="Telegram session expired")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise web.HTTPUnauthorized(text="Telegram signature verification failed")
    if not isinstance(user, dict) or not user.get("id"):
        raise web.HTTPUnauthorized(text="Telegram user is missing")
    return user


def create_app(*, bot_token, db_path, hourly_reward, fee_percent, activation_fee, company_wallet, admin_id):
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app["bot_token"] = bot_token
    app["db_path"] = db_path
    app["hourly_reward"] = hourly_reward
    app["fee_percent"] = fee_percent
    app["activation_fee"] = activation_fee
    app["company_wallet"] = company_wallet
    app["admin_id"] = int(admin_id)

    async def index(request):
        return web.FileResponse(WEB_DIR / "index.html")

    async def health(request):
        return web.json_response({"ok": True, "service": "grm-mini-app"})

    async def dashboard(request):
        tg = _telegram_user(request, app["bot_token"])
        uid = int(tg["id"])
        with _db(app["db_path"]) as c:
            row = c.execute(
                "SELECT username,balance,wallet,activation_at,checkin_day,last_checkin_date,last_mine,lang,activation_tx "
                "FROM users WHERE user_id=?", (uid,)
            ).fetchone()
            if not row:
                c.execute("INSERT INTO users(user_id,username) VALUES(?,?)", (uid, tg.get("username", "")))
                row = (tg.get("username", ""), 0, None, None, 0, None, None, "en", None)
            referral_total = c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
        referral_activated = c.execute("SELECT COUNT(*) FROM users WHERE referred_by=? AND referral_rewarded=1", (uid,)).fetchone()[0]
        referral_pending = referral_total - referral_activated
        pool_row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
            tasks = c.execute(
                "SELECT id,title,title_en,title_fa,title_ru,reward,desc_en,desc_fa,desc_ru "
                "FROM tasks WHERE active=1 ORDER BY id DESC LIMIT 30"
            ).fetchall()
            claimed = {r[0] for r in c.execute("SELECT task_id FROM task_claims WHERE user_id=?", (uid,)).fetchall()}
            pending = {r[0] for r in c.execute(
                "SELECT task_id FROM task_submissions WHERE user_id=? AND status='pending'", (uid,)
            ).fetchall()}
        lang = row[7] if row[7] in ("en", "fa", "ru") else "en"
        task_items = []
        idx = {"en": 0, "fa": 1, "ru": 2}[lang]
        for t in tasks:
            title = t[2 + idx] or t[1] or t[2] or "Task"
            desc = t[6 + idx] or ""
            task_items.append({
                "id": t[0], "title": title, "description": desc, "reward": t[5],
                "status": "claimed" if t[0] in claimed else ("pending" if t[0] in pending else "available")
            })
        pool = int(pool_row[0]) if pool_row else 0
        last_mine = datetime.fromisoformat(row[6]) if row[6] else None
        now = datetime.now(timezone.utc)
        mine_ready = not last_mine or now - last_mine >= timedelta(hours=1)
        return web.json_response({
            "user": {"id": uid, "name": tg.get("first_name", row[0] or "User"), "username": tg.get("username", "")},
            "balance": int(row[1] or 0), "pool": pool, "wallet": row[2] or "",
            "activated": bool(row[3]), "activation_pending": bool(row[8]) and not bool(row[3]),
            "checkin_day": int(row[4] or 0), "last_checkin_date": row[5],
            "checkin_done_today": row[5] == now.date().isoformat(),
            "mine_ready": mine_ready, "mine_seconds_left": max(0, int(3600 - (now-last_mine).total_seconds())) if last_mine else 0,
            "hourly_reward": app["hourly_reward"], "minimum_withdrawal": 17000,
            "withdrawal_fee_percent": app["fee_percent"], "activation_fee": app["activation_fee"],
            "company_wallet": app["company_wallet"], "language": lang, "tasks": task_items,
            "referral": {
                "link": f"https://t.me/GRM_Mining_Reward_Bot?start=ref{uid}",
                "total": referral_total, "activated": referral_activated,
                "pending": referral_pending, "earned": referral_activated * 500,
                "reward_per_activation": 500
            }
        })

    def _user(request):
        return _telegram_user(request, app["bot_token"])

    async def checkin(request):
        tg = _user(request)
        uid = int(tg["id"])
        today = datetime.now(timezone.utc).date().isoformat()
        with _db(app["db_path"]) as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT activation_at,checkin_day,last_checkin_date FROM users WHERE user_id=?", (uid,)).fetchone()
            if not row or not row[0]:
                raise web.HTTPForbidden(text="Activation is required")
            if row[2] == today:
                raise web.HTTPConflict(text="Already checked in today")
            day = int(row[1] or 0)
            if day >= 30:
                raise web.HTTPConflict(text="All 30 check-ins are complete")
            day += 1
            pool_row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
            pool = int(pool_row[0]) if pool_row else 0
            reward = min(day * 50, pool)
            if reward <= 0:
                raise web.HTTPConflict(text="Reward pool is empty")
            c.execute("UPDATE users SET checkin_day=?,last_checkin_date=?,balance=balance+? WHERE user_id=?",
                      (day, today, reward, uid))
            c.execute("INSERT INTO balance_history(user_id,change_amount,reason,reference,created_at) VALUES(?,?,?,?,?)",
                      (uid, reward, "daily_checkin", str(day), datetime.now(timezone.utc).isoformat()))
            c.execute("UPDATE settings SET value=? WHERE key='pool'", (str(max(0, pool-reward)),))
        return web.json_response({"ok": True, "day": day, "reward": reward})

    async def mine(request):
        tg = _user(request)
        uid = int(tg["id"])
        now = datetime.now(timezone.utc)
        with _db(app["db_path"]) as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT activation_at,last_mine FROM users WHERE user_id=?", (uid,)).fetchone()
            if not row or not row[0]:
                raise web.HTTPForbidden(text="Activation is required")
            last = datetime.fromisoformat(row[1]) if row[1] else None
            if last and now - last < timedelta(hours=1):
                raise web.HTTPConflict(text="Hourly mining is not ready")
            pool_row = c.execute("SELECT value FROM settings WHERE key='pool'").fetchone()
            pool = int(pool_row[0]) if pool_row else 0
            reward = min(app["hourly_reward"], pool)
            if reward <= 0:
                raise web.HTTPConflict(text="Reward pool is empty")
            c.execute("UPDATE users SET balance=balance+?,last_mine=? WHERE user_id=?",
                      (reward, now.isoformat(), uid))
            c.execute("INSERT INTO balance_history(user_id,change_amount,reason,reference,created_at) VALUES(?,?,?,?,?)",
                      (uid, reward, "hourly_mining", None, now.isoformat()))
            c.execute("UPDATE settings SET value=? WHERE key='pool'", (str(max(0, pool-reward)),))
        return web.json_response({"ok": True, "reward": reward})

    async def withdraw_request(request):
        tg = _user(request)
        uid = int(tg["id"])
        try:
            body = await request.json()
            raw_amount = body.get("amount", 0)
            if type(raw_amount) is not int:
                raise ValueError("amount must be an integer")
            amount = raw_amount
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest(text="Enter a valid whole-number amount")
        if amount < 17000:
            raise web.HTTPBadRequest(text="Minimum withdrawal is 17,000 GRM")
        fee = amount * app["fee_percent"] // 100
        net = amount - fee
        with _db(app["db_path"]) as c:
            c.execute("BEGIN IMMEDIATE")
            user = c.execute(
                "SELECT balance,wallet,activation_at,checkin_day FROM users WHERE user_id=?", (uid,)
            ).fetchone()
            if not user or not user[2]:
                raise web.HTTPForbidden(text="Activation is required")
            if not user[1]:
                raise web.HTTPBadRequest(text="Register your TON wallet in the bot first")
            if int(user[3] or 0) < 30:
                raise web.HTTPForbidden(text="Complete 30 successful daily check-ins first")
            if amount > int(user[0] or 0):
                raise web.HTTPBadRequest(text="Insufficient GRM balance")
            cur = c.execute(
                "INSERT INTO withdrawals(user_id,amount,fee,net,wallet,created_at) VALUES(?,?,?,?,?,?)",
                (uid, amount, fee, net, user[1], datetime.now(timezone.utc).isoformat())
            )
            request_id = cur.lastrowid
            c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
            c.execute(
                "INSERT INTO balance_history(user_id,change_amount,reason,reference,created_at) VALUES(?,?,?,?,?)",
                (uid, -amount, "withdrawal_request", str(request_id), datetime.now(timezone.utc).isoformat())
            )
        try:
            admin_bot = Bot(token=app["bot_token"])
            try:
                await admin_bot.send_message(
                    app["admin_id"],
                    f"New Mini App withdrawal #{request_id}\nUser: {uid}\nGross: {amount} GRM\nFee ({app['fee_percent']}%): {fee} GRM\nNet to send: {net} GRM\nWallet: {user[1]}\nReview: /pending"
                )
            finally:
                await admin_bot.session.close()
        except Exception as exc:
            print(f"[webapp] Could not notify admin about withdrawal #{request_id}: {exc}")
        return web.json_response({"ok": True, "request_id": request_id, "amount": amount, "fee": fee, "net": net})

    async def save_language(request):
        tg = _user(request)
        body = await request.json()
        lang = body.get("language")
        if lang not in ("en", "fa", "ru"):
            raise web.HTTPBadRequest(text="Unsupported language")
        with _db(app["db_path"]) as c:
            c.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, int(tg["id"])))
        return web.json_response({"ok": True, "language": lang})

    app.router.add_get("/", index)
    app.router.add_get("/healthz", health)
    app.router.add_get("/api/dashboard", dashboard)
    app.router.add_post("/api/checkin", checkin)
    app.router.add_post("/api/mine", mine)
    app.router.add_post("/api/language", save_language)
    app.router.add_post("/api/withdraw", withdraw_request)
    return app


async def start_webapp_server(*, bot_token, db_path, hourly_reward, fee_percent, activation_fee, company_wallet, admin_id, host="0.0.0.0", port=8080):
    app = create_app(
        bot_token=bot_token, db_path=db_path, hourly_reward=hourly_reward,
        fee_percent=fee_percent, activation_fee=activation_fee, company_wallet=company_wallet, admin_id=admin_id
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"[webapp] Mini App server listening on {host}:{port}")
    try:
        import asyncio
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
