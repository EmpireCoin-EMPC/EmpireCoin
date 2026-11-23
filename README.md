# GRM Mining Reward Bot (MVP)

Python Telegram bot using aiogram 3 and SQLite.

## Included
- Hourly mining and task rewards
- Internal GRM balance and pool accounting (initial pool: 172,000,000)
- TON-network wallet registration
- Activation: user registers a wallet, sends 0.5 GRAM to the company wallet, submits `/activate TX_HASH`; an admin manually verifies it and confirms using `/activation_ok USER_ID`.
- Withdrawals require 30 successful daily check-ins and at least 17,000 GRM; missed days pause progress without resetting it. A 10% fee applies; admin approval and manual payout are required, recorded via `/paid REQUEST_ID TX_HASH`
- Admin-reviewed trade requests and basic lottery

## Telegram Mini App (initial dashboard)
- Responsive three-language dashboard is served from `webapp/index.html`.
- Authenticated API validates Telegram Web App `initData` using the bot token; never trust a user ID sent by the browser.
- The first version displays balance, pool, activation status, wallet, check-in progress and tasks; it supports hourly mining and daily check-in. Admin payment confirmation remains manual in the Telegram bot.
- Set `WEBAPP_URL` to the public HTTPS URL routed to the server's `WEBAPP_PORT` (default 8080). Without a public HTTPS URL, Telegram cannot launch the Mini App.
- HOKAS must expose the configured web port through HTTPS. Confirm the hosting panel's port/domain mapping before enabling the menu button.

## Setup
1. Install Python 3.11+.
2. Copy `.env.example` to `.env`.
3. Set BOT_TOKEN and ADMIN_ID locally. Never commit `.env`.
4. Confirm GRAM_COMPANY_WALLET is the correct company receiving wallet.
5. Install dependencies: `pip install -r requirements.txt`
6. Set `WEBAPP_URL` to your public HTTPS domain and `WEBAPP_PORT` to the exposed app port. For local development, the web server listens on `0.0.0.0:8080` by default.
7. Run: `python -m app`

## Activation payment safety
- This MVP does **not** automatically verify TON blockchain transactions. Admin must verify the transaction hash on a trusted TON explorer, check the destination is GRAM_COMPANY_WALLET, amount is exactly 0.5 GRAM, and transaction is finalized before using `/activation_ok USER_ID`.
- A screenshot or unverified claim is not proof of payment.
- The withdrawal check-in requirement is 30 successful check-ins; missed calendar days pause progress and do not reset the count.
- Clearly disclose the 0.5 GRAM activation payment and 30-day withdrawal restriction to users before they pay. Do not imply guaranteed returns or investment profit.
- Withdrawals are manual: after approval, send net GRAM (the native TON-network coin, formerly Toncoin) from the treasury securely and record the transaction hash using `/paid REQUEST_ID TX_HASH`.
- Never store or share seed phrases/private keys in this bot or repository.

## MVP limitations / not production-ready
- Task completion is self-reported, not independently verified.
- Trade approval only records an internal decision; it does not settle a blockchain trade.
- Whole-token integer accounting only; token decimals and master contract integration still need validation.
- No automated on-chain payment verification, payout, rate limiting, backup automation, audit log, or complete bilingual interface.
- Test with a separate bot and small amounts before real users or funds.
