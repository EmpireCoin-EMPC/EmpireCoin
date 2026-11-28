# EMPC Rebuild — functional test plan

Run against a disposable database and a test bot only. Never use the legacy bot token, legacy DB, or live user balances.

## Test setup
- Create a temporary SQLite database; confirm pool initializes to 172,000,000 EMPC.
- Configure a test bot token and numeric admin ID; do not expose secrets in logs or repository.
- Configure an HTTPS Mini App URL and verify the Telegram launch path.

## Telegram Web App auth
- Valid signed init data -> accepted.
- Modified signature or user field -> rejected.
- Missing/invalid auth header -> rejected.
- Stale auth_date (>24h) and excessively future auth_date -> rejected.
- Malformed JSON, missing user ID, and malformed query data -> rejected.

## Pool/accounting
- Mine once -> configured reward added and pool decremented exactly once.
- Mine again before one hour -> rejected with no balance/pool change.
- Pool below reward -> partial reward; pool reaches zero; no negative pool.
- Concurrent mining calls -> at most one reward per hour.
- Daily check-in duplicate -> conflict and no accounting changes.
- Check-in rewards progress 50,100,...,1500 EMPC through 30 days; check-in 31 rejected.
- Concurrent check-in requests -> only one accepted for the day.
- Check-in and hourly mining do not permit a negative pool or inconsistent balance history.

## Withdrawals
- Reject malformed, float, negative, below-minimum, and over-balance amount.
- Reject if no wallet or fewer than 30 check-ins.
- Valid request -> correct 10% fee/net, stored wallet snapshot, pending state, exact debit and history entry.
- Admin notification failure -> request rejected and balance fully refunded exactly once.
- Concurrent requests cannot overspend.
- Verify admin approve/reject/paid commands, state transitions and repeated-command behavior; check that rejecting returns the correct amount exactly once and paid status does not refund.

## Tasks
- Invalid task IDs, inactive tasks, missing evidence, oversized evidence and oversized photos rejected.
- Only one pending submission per user/task.
- Admin approve/reject paths work exactly once; rejected submission can be resubmitted according to policy.
- Ensure rewards are credited only on admin approval, with pool accounting and history.

## Configuration and deployment
- Confirm dedicated DB path, admin ID, port, HTTPS Mini App URL, pool/reward settings and bot username.
- Verify /healthz and Mini App assets.
- Confirm HOKAS is configured to the new repo/branch only.
- Do not deploy to production until test results are recorded and test-mode activation is removed or explicitly approved.
