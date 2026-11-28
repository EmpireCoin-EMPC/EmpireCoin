# EMPC Mini App rebuild — pre-deployment review

## Current status
This branch is a test rebuild. Do not deploy it for real-value mining or withdrawals until the items below are resolved and tested.

## Findings / blockers
- **Test-mode activation bypass:** new users are inserted with `activation_at` set automatically in `app/__main__.py` and `app/webapp_server.py`. Activation payments are intentionally disabled. This is not a production activation flow.
- **Manual withdrawal review:** Mini App withdrawals require 30 check-ins and a registered TON wallet, debit the internal balance, and notify the administrator. The bot does not execute on-chain payouts or automatically verify payments.
- **Telegram Web App authentication:** the backend validates Telegram init-data HMAC and checks its age (24-hour window). Add automated tests for valid, tampered, missing, duplicate-key, expired and future-dated data before deployment.
- **Withdrawal and pool concurrency:** current code uses SQLite transactions; test race conditions for concurrent mining/check-in/withdrawal requests and ensure balance/pool cannot go negative.
- **Task evidence storage:** photos are forwarded to the admin and a Telegram file ID is saved; verify failures, duplicate submissions and review paths.
- **Configuration / deployment:** verify the actual HTTPS Mini App URL, bot username, DB path, admin numeric ID, port and environment secrets on the new HOKAS server. Never use the old deployment's database or credentials.

## Verified in this branch
- CI Python checks passed (GitHub Actions run 7).
- Dedicated default DB filename is `empcoin_newbot.db`.
- Regular user command menu is limited to `/start`; the Telegram menu button opens the Mini App when `WEBAPP_URL` is configured.
- Referral link points to `@EmpireCoin_EMPC_Bot`.
- Withdrawal schema includes `reviewed_at`.

## Required before production
1. Automated unit/integration tests for authentication, mining/check-in pool accounting, withdrawals/refunds, task review, and admin-only handlers.
2. Remove or replace test-mode activation bypass; implement the actual policy only after it is specified.
3. Verify all admin command handlers are admin-gated and review the withdrawal approval/refund lifecycle.
4. Deploy to the isolated new server only after configuration and smoke tests.
5. Keep old bot, credentials and database untouched.
