# EmpireCoin (EMPC) Telegram Rewards Bot

A rebuild of the previous experimental GRM bot around EmpireCoin (EMPC), the fixed-supply TON Jetton.

## Token
- Name: EmpireCoin
- Symbol: EMPC
- Network: TON Mainnet
- Total supply: 313,000,000 EMPC
- Decimals: 9
- Mintable: No
- Jetton master: `EQA1Vk075IL1IVGlyGeOfgYKdDudLA3dCK9Nq2KhT1n-0dR`
- Official channel: https://t.me/empirecoinofficial

## Token Allocation & Transparency

See the [EMPC Token Allocation & Transparency Report](TOKEN_ALLOCATION.md) for the project's allocation breakdown, wallet references, transaction references, and liquidity-reserve details.

## Rebuild plan
The previous bot is an experimental codebase. Rebranding and feature changes are being staged; the existing runtime must not be treated as EMPC-ready until the code, database, payout flow, and server deployment have been reviewed and tested.

Planned features: hourly rewards, daily check-ins, task submissions/reviews, referrals, balance history, wallet registration, withdrawal requests, admin controls, and a Telegram Mini App.

## Safety and status
- Internal balances are not on-chain balances and are not proof of token payment.
- Rewards, market value, liquidity, and payouts are not guaranteed.
- No activation payment should be collected while the rebuild is being tested.
- Do not put bot tokens, passwords, private keys, or wallet recovery phrases in this repository.
- Keep backups of database files before any reset or migration.
- This project is not audited or production-ready.

## Development
Python 3.11+, aiogram 3, SQLite.
