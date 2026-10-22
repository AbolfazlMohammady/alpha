# Babaei - Commands

python manage.py cleanup_media --delete --empty-dirs
python manage.py cleanup_media

docker compose exec django python manage.py seed_static_products --count 30 --with-comments

## Local Docker Desktop

### 1. Check Docker Desktop

Docker Desktop must be installed and running.

Check Docker and Compose:

```powershell
docker --version
docker compose version
```

### 2. Go to project root

Run these commands from the Babaei project root (the folder containing `docker-compose.yml`):

```powershell
cd A:\Develop\project\Babaei
```

### 3. Download the Docker service images

```powershell
docker compose pull postgres redis pgadmin
```

### 4. Build the Django and Celery images

```powershell
docker compose build
```

For a completely fresh dependency/image rebuild:

```powershell
docker compose build --no-cache
```

### 6. Start the whole project

```powershell
docker compose up -d
```

Build and start in one command:

```powershell
docker compose up -d --build
```

### 7. Check container status

```powershell
docker compose ps
```

You should see the main services running:

- django
- celery
- postgres
- redis
- pgadmin

### 8. Check Django logs

```powershell
docker compose logs -f django
```

### 9. Run migrations manually

The Django entrypoint already runs migrations at startup. Run this only when you need to apply them manually:

```powershell
docker compose exec django python manage.py migrate
```

### 10. Create an admin user

```powershell
docker compose exec django python manage.py createsuperuser
```

### 11. Collect static files

The entrypoint already runs this at startup. Run manually when needed:

```powershell
docker compose exec django python manage.py collectstatic --noinput
```

### 12. Open the project

Django:

```text
http://localhost:8000
```

pgAdmin:

```text
http://localhost:5050
```

PostgreSQL is exposed locally on:

```text
127.0.0.1:5432
```

Redis is exposed locally on:

```text
127.0.0.1:6379
```

Inside Docker, Django/Celery connect to the Docker services using:

```text
postgres:5432
redis:6379
```

### 13. Open a shell inside Django

```powershell
docker compose exec django sh
```

### 14. Stop the project

```powershell
docker compose down
```

Delete PostgreSQL data too (DANGER):

```powershell
docker compose down -v
```

### 15. Restart after code changes

For normal Python/template/static changes with the project volume mounted:

```powershell
docker compose restart django
```

When Dockerfile or requirements change:

```powershell
docker compose build --no-cache
docker compose up -d
```

---

# FastAPI

Run locally:

```powershell
uvicorn main:app --reload
```

Find uvicorn:

```powershell
tasklist | findstr uvicorn
```

If a process named `uvicorn.exe` is running:

```powershell
taskkill /F /IM uvicorn.exe
```

Run FastAPI on port 8001:

```powershell
uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

---

# Django Maintenance

Clean orphan media files:

```powershell
python manage.py cleanup_media
```

Delete orphan media files and empty directories:

```powershell
python manage.py cleanup_media --delete --empty-dirs
```

Run tests with coverage:

```powershell
pytest --cov=apps --cov-report=term-missing
```

Inside Docker:

```powershell
docker compose exec django python manage.py cleanup_media
docker compose exec django python manage.py cleanup_media --delete --empty-dirs
```

---

# Translations

Create Persian messages:

```powershell
docker compose exec django python manage.py makemessages -l fa --ignore=*.txt --ignore=*.md --ignore=venv --ignore=env
```

Create Persian and Arabic messages:

```powershell
docker compose exec django python manage.py makemessages -l fa -l ar --ignore=*.txt --ignore=*.md --ignore=venv --ignore=env
```

Compile translations:

```powershell
docker compose exec django python manage.py compilemessages
```

Backfill translations:

```powershell
docker compose exec django python manage.py backfill_translations
```

---

# Django Axes

Reset all Axes lockouts:

```powershell
python manage.py axes_reset
```

Reset one username:

```powershell
python manage.py axes_reset_username admin
```

Inside Docker:

```powershell
docker compose exec django python manage.py axes_reset
docker compose exec django python manage.py axes_reset_username admin
```

---

# Celery

Run Celery locally:

```powershell
celery -A config.celery_config:app worker -l INFO -Q tasks
```

Check Celery logs in Docker:

```powershell
docker compose logs -f celery
```

Restart Celery:

```powershell
docker compose restart celery
```
