# Gold Nightmare · Personal Edition

محلّل XAUUSD احترافي للاستخدام الشخصي. مبني على Claude Vision + ICT/SMC + ML training loop.

**v3.0** — single-user / personal edition. لا multi-user، لا tiers، لا activation codes. مالك واحد بـ passcode + JWT cookie.

---

## ✨ المميزات

- **تحليل شارت ذكي** — Claude Opus 4 + structured JSON output (ICT/SMC/Wyckoff/Fibonacci)
- **MTF analysis** — حتى 4 صور في تحليل واحد
- **Telegram bot** — مالك واحد فقط (محدد بـ `OWNER_TELEGRAM_ID`)
- **PDF export + Share links**
- **🧠 نظام تدريب كامل**:
  - Outcome tracker تلقائي (كل 5 دقائق)
  - Few-shot learning (ChromaDB + sentence-transformers)
  - ML pattern classifier (XGBoost) — second opinion لكل setup
  - Backtest engine على بيانات تاريخية
  - Auto-promote (تحاليل ناجحة → few-shot bank)
  - Dataset export (JSONL/CSV)

---

## 🚀 التشغيل المحلي

```bash
# 1. كلون
git clone ... && cd gold_nightmare_personal

# 2. virtualenv
python -m venv venv
.\venv\Scripts\activate     # Windows
# source venv/bin/activate  # Linux/Mac

# 3. installation (heavy — ~3GB من الـ wheels)
pip install -r requirements.txt

# 4. config
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"  # SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(16))"  # PERSONAL_PASSCODE
# عدّل .env: SECRET_KEY, PERSONAL_PASSCODE, ANTHROPIC_API_KEY

# 5. database
alembic upgrade head

# 6. تشغيل
uvicorn app.main:app --reload --port 8000

# افتح http://localhost:8000/login
# ادخل بـ PERSONAL_PASSCODE
```

---

## 📦 النشر على Render

```bash
# 1. ادفع الكود لـ GitHub
git push origin main

# 2. في Render dashboard:
#    - أنشئ Web Service من المستودع
#    - استخدم render.yaml الجاهز (auto-deploy)
#    - حدّد بيانات env في Dashboard:
#      • PERSONAL_PASSCODE
#      • ANTHROPIC_API_KEY
#      • OWNER_TELEGRAM_ID (إن أردت)
#      • TELEGRAM_BOT_TOKEN (إن أردت)
#      • TWELVEDATA_KEY (للـ backtest)

# 3. ⚠️ ملاحظة: الـ ML stack ثقيل (~3GB).
#    Render starter plan ما يكفي. استخدم Standard على الأقل.
```

### Webhook لـ Telegram (اختياري)
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://your-app.onrender.com/api/v1/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

---

## 🧠 نظام التدريب

النظام يتعلم من نفسه ويتحسن مع الوقت بدون fine-tuning تقليدي.

### Background Jobs (APScheduler)

| Job | كل | الغرض |
|-----|------|-------|
| Outcome Tracker | 5 دقائق | فحص أسعار XAUUSD وتحديث setups |
| Auto-promote | ساعة | ترقية الناجحين (R:R ≥ 1.5) لـ few-shot bank |
| Classifier Training | يومياً 03:00 UTC | إعادة تدريب XGBoost |
| DB Maintenance | يومياً 04:00 UTC | تنظيف audit logs >90 يوم |

### CLI

```bash
# تدريب الـ ML classifier
python -m scripts.train_classifier
python -m scripts.train_classifier --info

# Backtest على بيانات تاريخية (يحتاج TWELVEDATA_KEY)
python -m scripts.run_backtest --tf H1 --start 2026-01-01 --end 2026-04-30 --samples 30

# تصدير datasets
python -m scripts.export_dataset --type quality --min-rr 1.5
python -m scripts.export_dataset --type training --limit 5000
python -m scripts.export_dataset --type csv

# Bulk-seed few-shot bank
python -m scripts.seed_few_shot --min-rr 1.5 --max 100
```

### Dashboard

- `/dashboard` — Owner overview (إحصائيات شخصية)
- `/training` — نظام التدريب (6 tabs: overview, outcomes, fewshot, classifier, backtest, export)
- `/history` — سجل كل التحاليل + feedback widget لكل واحد
- `/` — صفحة التحليل الرئيسية

---

## 🤖 Telegram Bot

البوت يرد **فقط** على المستخدم اللي ID رقمه في `OWNER_TELEGRAM_ID`. أي حد آخر يحاول، يحصل رسالة "ليس مصرحًا لك".

**الأوامر:**
- `/start` — رسالة ترحيب
- `/help` — قائمة الأوامر
- `/stats` — إحصائياتك
- `/last` — آخر تحليل
- إرسال صورة شارت → تحليل فوري

---

## 🛠 Stack

- Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · Alembic
- PostgreSQL (prod) أو SQLite (dev)
- Anthropic Claude (Opus 4 / Sonnet 4)
- python-jose (JWT) — لا bcrypt، لا OAuth
- Pillow + WeasyPrint (PDF)
- APScheduler (background)
- pandas + polars + scikit-learn + xgboost + lightgbm + optuna
- pytorch + transformers + sentence-transformers
- chromadb (vector store) — embedded mode
- matplotlib + mplfinance + plotly (charts)

---

## ⚠️ ملاحظات أمان

- `PERSONAL_PASSCODE` حساس — عاملو زي API key
- الـ JWT في HTTP-only cookie + `Secure` flag في production
- لا تنشر `.env` على GitHub
- استخدم HTTPS دايماً (Render تقدمه مجاناً)
- `OWNER_TELEGRAM_ID` يحدد من يستخدم البوت — مش مجرد filter، بل rejection فعلي

---

## 📜 License

Private — للاستخدام الشخصي لـ @Odai_xau فقط.
