# EmpireCoin New Bot Launch Checklist

Target bot: @EmpireCoin_EMPC_Bot
Mini App: existing HOKAS service URL (confirm deployment before publishing)
Mining allocation: 172,000,000 EMPC

## Isolation and reset
- Set a separate deployment environment for the new bot token and a dedicated fresh database path (for example, empc_new.db).
- Do not reuse the old bot token or old database file.
- Keep the previous bot/deployment as a rollback copy until the new version has been tested.
- A fresh SQLite database initializes the pool setting from MINING_POOL (default 172000000). Verify it in admin report before launch.

## User-facing experience
- Keep user entry through /start and the Telegram Mini App launch button only.
- Remove user-facing command menu entries and reply keyboards that expose legacy commands.
- Keep admin-only command handlers and admin panel available to ADMIN_ID.
- Ensure bot's default command list is minimal (Start only); admin command list is scoped to admin chat.
- Keep Mini App task submissions, check-in, mining, wallet and manual withdrawal-review features, if enabled.

## Required code review before deployment
- Remove legacy activation gates for new users consistently in both bot handlers and Mini App API.
- Verify check-in, hourly mining, task reward, and withdrawal paths use the new DB and pool.
- Verify user referral URLs use the new bot username, or temporarily hide referrals if disabled.
- Ensure user command/menu visibility does not interfere with admin commands.
- Verify Mini App URL and WEBAPP_PORT/PORT configuration in the new deployment.
- Run CI and test in a separate HOKAS instance/config before switching users.

## Safety
- Never commit BOT_TOKEN or other secrets.
- Back up the new database before any production reset.
- Manual payout review only; no claim of automatic on-chain verification or payout.
