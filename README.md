# Name classification API (HNG Stage 0)

Django + Django REST Framework service that proxies [Genderize.io](https://genderize.io/) and returns a normalized JSON payload with confidence rules.

## Endpoint

`GET /api/classify?name={name}`

- **200** — `status: success` with `data` (gender, probability, `sample_size` from API `count`, `is_confident`, `processed_at` in UTC ISO 8601 with `Z`).
- **400** — missing or empty `name`.
- **422** — invalid `name` (e.g. repeated query values), or Genderize has no prediction (`gender: null` or `count: 0`).
- **502** — upstream/network failure or invalid upstream payload.

Errors use: `{ "status": "error", "message": "..." }`.

CORS is open (`Access-Control-Allow-Origin: *`) for browser-based grading scripts.

## Confidence rule

`is_confident` is `true` only when **both** `probability >= 0.7` and `sample_size >= 100`.

## Local setup

This project does not use a database or models, so **you do not need to run `migrate`**.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000
```

## Quick test

```bash
curl -s "http://127.0.0.1:8000/api/classify?name=john"
```

Expect `"status":"success"` and fields matching the task spec.

## Deploy

Use any WSGI host (e.g. Railway, Heroku, Vercel with a Python runtime). Example:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

Set `DEBUG=False`, `SECRET_KEY`, and `ALLOWED_HOSTS` in production via environment variables (adjust `config/settings.py` as needed).
