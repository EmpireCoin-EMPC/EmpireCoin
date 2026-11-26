# Empire Support Telegram Bot

A multilingual Telegram support inbox for EmpireCoin users (English, Persian, Russian).

## Features
- Start and language selection; no commands required to submit a support request.
- Accepts text, photos, screenshots, documents, videos, audio, voice notes and stickers.
- Attaches user ID, username, display name, language and ticket number to support notifications.
- Team replies by replying to the ticket summary message in the configured support inbox.

## Setup
1. Create the bot in Telegram BotFather and obtain its token.
2. Copy `.env.example` to `.env`; set `BOT_TOKEN` and `ADMIN_CHAT_ID`.
3. Install: `pip install -r requirements.txt`
4. Run: `python main.py`

The admin inbox can be an individual admin chat or a private support group. For a group, add the bot and configure its numeric chat ID; ensure reply messages are visible to the bot (privacy mode may need adjustment).

Never commit real bot tokens or user data. This is a starter implementation and should be tested before production deployment.
