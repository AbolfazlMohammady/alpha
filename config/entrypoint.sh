#!/bin/sh
set -e

# Wait for PostgreSQL using a lightweight TCP check.
# This keeps the image free of the PostgreSQL client package.
echo "Waiting for PostgreSQL..."
DB_HOST="${POSTGRES_HOST:-postgres}"
DB_PORT="${POSTGRES_PORT:-5432}"

until python -c "import socket; s=socket.create_connection(('$DB_HOST', int('$DB_PORT')), 2); s.close()" 2>/dev/null; do
  sleep 2
done

echo "PostgreSQL is up!"

# Run Django initialization only for the main gunicorn container.
# Celery workers skip migrations and static collection.
if echo "$@" | grep -q "gunicorn"; then
    echo "Running migrations..."
    python manage.py migrate --noinput || echo "Migrations failed or already applied"
    echo "Bootstrapping superuser..."
    python manage.py bootstrap_superuser

    echo "Collecting static files..."
    python manage.py collectstatic --noinput || echo "Static collection skipped"
fi

if echo "$@" | grep -q "celery"; then
    echo "Celery worker starting - waiting for Django to be ready..."
    sleep 10
fi

echo "Starting: $@"
exec "$@"
