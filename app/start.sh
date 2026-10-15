#!/bin/sh
set -eu

# Gunicorn imports app.py without executing its __main__ setup.
python -c 'from db import initialize_database; initialize_database()'

exec gunicorn \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 90 \
    --access-logfile - \
    --error-logfile - \
    app:app
