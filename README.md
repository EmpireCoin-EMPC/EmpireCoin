# GRM Mining Reward Bot (MVP)

Python Telegram bot using aiogram 3 and SQLite.

## Included
- Hourly mining and task rewards
- Internal GRM balance and pool accounting (initial pool: 172,000,000)
- TON wallet registration
- Activation: user sends 0.5 TON to the company wallet, submits transaction hash with `/activate TX_HASH`; an admin verifies it and confirms using `/activation_ok USER_ID`. The 30-day withdrawal waiting period starts only after confirmation.
- Withdrawals only after the 30-day lock; 10% fee; admin approval; manual payout and recording via `/paid REQUEST_ID TX_HASH`
- Admin-reviewed trade requests and basic lottery

## Setup
1. Install Python 3.11+.
2. Copy `.env.example` to `.env`.
3. Set BOT_TOKEN and ADMIN_ID locally. Never commit `.env`.
4. Confirm TON_COMPANY_WALLET is the correct company receiving wallet.
5. Install dependencies: `pip install -r requirements.txt`
6. Run: `python -m app`

## Activation payment safety
- This MVP does **not** automatically verify TON blockchain transactions. Admin must verify the transaction hash on a trusted TON explorer, check the destination is TON_COMPANY_WALLET, amount is exactly 0.5 TON, and transaction is finalized before using `/activation_ok USER_ID`.
- A screenshot or unverified claim is not proof of payment.
- The 30-day waiting period is measured from the admin confirmation timestamp in UTC.
- Clearly disclose the 0.5 TON activation payment and 30-day withdrawal restriction to users before they pay. Do not imply guaranteed returns or investment profit.
- Withdrawals are manual: after approval, send net GRM from the treasury securely and record the transaction hash using `/paid REQUEST_ID TX_HASH`.
- Never store or share seed phrases/private keys in this bot or repository.

## MVP limitations / not production-ready
- Task completion is self-reported, not independently verified.
- Trade approval only records an internal decision; it does not settle a blockchain trade.
- Whole-token integer accounting only; token decimals and master contract integration still need validation.
- No automated on-chain payment verification, payout, rate limiting, backup automation, audit log, or complete bilingual interface.
- Test with a separate bot and small amounts before real users or funds.
