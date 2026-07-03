# Terra Meta Backend

Django REST Framework API for the Terra Meta mineral intelligence platform.

**Production URLs**
- API: https://api.terrameta.5ggeology.com
- Frontend: https://terrameta.5ggeology.com

## Quick start (development)

```bash
cp .env.example .env   # edit DB credentials and secrets
chmod +x start.sh
./start.sh
```

`start.sh` creates a virtualenv, installs dependencies, runs migrations, and starts Gunicorn on port **8085**.

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data   # optional demo data
python manage.py runserver 8085
```

## Production deploy (PM2)

```bash
# 1. Copy and edit environment (never commit .env)
cp .env.example .env

# 2. Deploy
chmod +x deploy.sh
./deploy.sh
```

PM2 processes started:
- `terra-meta-api` — Gunicorn on port 8085
- `terra-meta-celery` — background tasks (layer import, invoices, AI summaries)
- `terra-meta-celery-beat` — scheduled jobs (subscription expiry, reminders)

```bash
pm2 status
pm2 logs terra-meta-api
pm2 restart terra-meta-api
```

### Celery: unknown task errors

If the worker logs `KeyError: 'some.app.tasks.task_name'`, the Redis queue still has messages from an older deployment (removed or renamed tasks). On the server:

```bash
cd /home/tm-api/htdocs/www.api.terrameta.5ggeology.com/tm-backend
source .venv/bin/activate
rm -f celerybeat-schedule celerybeat-schedule.db celerybeat-schedule.dat
celery -A config purge -f
pm2 restart terra-meta-celery terra-meta-celery-beat
```

`deploy.sh` runs the purge step automatically on each deploy.

## Payments (Snippe)

Live checkout uses [Snippe](https://docs.snippe.sh/docs/) for mobile money and card payments.

Add to `.env` for production:

```env
SNIPPE_API_KEY=snp_your_api_key
SNIPPE_WEBHOOK_SECRET=whsec_your_signing_key
BACKEND_URL=https://api.terrameta.5ggeology.com
PAYMENTS_SIMULATE=false
```

Webhook endpoint (register in the Snippe dashboard or pass per payment):

```
POST https://api.terrameta.5ggeology.com/api/v1/payments/webhooks/snippe/
```

For local development without Snippe credentials, keep `PAYMENTS_SIMULATE=true` in `.env` — checkouts auto-complete. **Never enable simulation when `DEBUG=False`.**

Checkout flow:
1. `POST /api/v1/payments/checkout/` — creates order and Snippe payment intent
2. Mobile money — USSD push to the customer’s phone
3. Card — redirect to Snippe secure checkout (`payment_url`)
4. Webhook or `GET /api/v1/payments/orders/{merchant_reference}/status/` — confirms completion and activates subscriptions / report purchases

## Default admin

- Email: `admin@5ggeology.com`
- Password: `admin123`

## Demo accounts

Created (or reset) by `python manage.py seed_data`. Sign in with **email + password** (username still works too).

| Role | Email | Password | Access |
|------|-------|----------|--------|
| Admin | `admin@5ggeology.com` | `admin123` | Full platform admin |
| Free | `testfree@5ggeology.com` | `test123` | Map preview, watermarked layers |
| Paid | `testpaid@5ggeology.com` | `test123` | Active subscriber, full map access |
| Manager | `testmanager@5ggeology.com` | `test123` | Mineral manager workspace (Gold assigned) |

```bash
python manage.py seed_data
```

## AI summaries

Configure in `.env` (provider: `ollama`, `groq`, or `gemini`):

```
AI_PROVIDER=groq
AI_PROVIDER_FALLBACK=groq,gemini,ollama
GROQ_API_KEY=your-key
GEMINI_API_KEY=your-key
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
```

## Prerequisites (native install)

- Python 3.11+
- MySQL 8 with database `tmdb` (see `.env.example` for credentials)
- Redis (for Celery background tasks)
- Node.js + PM2 (`npm install -g pm2`) for production deploy

## API overview

Base path: `/api/v1/`

| Area | Prefix |
|------|--------|
| Auth | `/auth/` |
| Maps & layers | `/maps/` |
| Minerals | `/minerals/` |
| Subscriptions | `/subscriptions/` |
| Payments | `/payments/` |
| Reports | `/reports/` |
| Analytics | `/analytics/` |
| Compliance | `/compliance/` |
