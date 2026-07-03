# Terra Meta Backend

Django REST Framework API for the Terra Meta mineral intelligence platform.

**Production URLs**
- API: https://api.terrameta.5ggeology.com
- Frontend: https://terrameta.5ggeology.com

## Quick start (development)

```bash
chmod +x start.sh
./start.sh
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
- `terra-meta-api` - Gunicorn on port 8085
- `terra-meta-celery` - background tasks (layer import, AI summaries)
- `terra-meta-celery-beat` - scheduled jobs (subscription expiry, reminders)

```bash
pm2 status
pm2 logs terra-meta-api
pm2 restart terra-meta-api
```

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

## AI Summaries

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

- MySQL 8 with database `tmdb` (see `.env.example` for credentials)
- Redis (for Celery background tasks)
- Node.js + PM2 (`npm install -g pm2`) for production deploy
