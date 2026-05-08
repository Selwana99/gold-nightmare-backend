# Changelog

## v3.0.0 (2026-05-05) — Personal Edition

نسخة شخصية كاملة من الصفر. لا multi-user, لا tiers, لا activation codes.

### Architecture (Single-user)

- **Auth**: مالك واحد بـ `PERSONAL_PASSCODE` في `.env` + JWT cookie. لا users table.
- **Telegram**: البوت يرد فقط على `OWNER_TELEGRAM_ID`. غيرو يحصل رسالة رفض.
- **Analyses**: بدون `user_id` — كلها للمالك.
- **Audit log**: حقل `actor` بدلاً من user_id (owner / system / telegram_bot / scheduler).

### Removed (vs v2.x)

- ❌ User tiers (FREE/VIP/PREMIUM/LEGENDARY)
- ❌ Activation codes
- ❌ Email/password registration
- ❌ Telegram OAuth widget login
- ❌ Rate limiting + monthly quotas
- ❌ Admin user management
- ❌ Multiple-user tracking

### Kept (full feature parity للـ training)

✅ Chart analyzer (single + MTF)
✅ History + PDF export + Share links
✅ Telegram bot (owner-only)
✅ كل training subsystem:
  - Outcome tracker
  - Few-shot learning (ChromaDB + sentence-transformers)
  - ML pattern classifier (XGBoost)
  - Backtest engine
  - Auto-promote
  - Dataset export (JSONL/CSV)
  - Background scheduler (APScheduler, 4 jobs)
  - Training dashboard (6 tabs)
  - Feedback widget
  - ML quality score badges

### Stats

- 7 جداول (analyses, audit_logs, share_links, analysis_outcomes, feedbacks, backtest_runs, few_shot_examples)
- 1 migration (single initial schema)
- 28 endpoint
- 35 test passing
- ~10K LOC
