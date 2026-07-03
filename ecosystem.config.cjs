/** @type {import('pm2').StartOptions} */
const path = require('path')

const ROOT = __dirname
const VENV_PYTHON = path.join(ROOT, '.venv', 'bin', 'python')
const GUNICORN_BIND = process.env.GUNICORN_BIND || '0.0.0.0:8085'
const GUNICORN_WORKERS = process.env.GUNICORN_WORKERS || '3'

module.exports = {
  apps: [
    {
      name: 'terra-meta-api',
      cwd: ROOT,
      script: path.join(ROOT, '.venv', 'bin', 'gunicorn'),
      args: `config.wsgi:application --bind ${GUNICORN_BIND} --workers ${GUNICORN_WORKERS} --timeout 120 --access-logfile logs/access.log --error-logfile logs/error.log`,
      interpreter: 'none',
      env: {
        NODE_ENV: 'production',
        DJANGO_SETTINGS_MODULE: 'config.settings',
      },
      max_restarts: 10,
      min_uptime: '10s',
    },
    {
      name: 'terra-meta-celery',
      cwd: ROOT,
      script: path.join(ROOT, '.venv', 'bin', 'celery'),
      args: '-A config worker -l info',
      interpreter: 'none',
      env: {
        DJANGO_SETTINGS_MODULE: 'config.settings',
      },
      max_restarts: 10,
    },
    {
      name: 'terra-meta-celery-beat',
      cwd: ROOT,
      script: path.join(ROOT, '.venv', 'bin', 'celery'),
      args: '-A config beat -l info',
      interpreter: 'none',
      env: {
        DJANGO_SETTINGS_MODULE: 'config.settings',
      },
      max_restarts: 10,
    },
  ],
}
