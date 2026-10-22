#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:?Usage: restore_backup.sh <backup.tar.gz[.enc]> [target_root]}"
TARGET_ROOT="${2:-/var/www/babaei}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [[ "$ARCHIVE" == *.enc ]]; then
  : "${BACKUP_ENCRYPTION_KEY:?BACKUP_ENCRYPTION_KEY must be set for encrypted backups}"
  openssl enc -d -aes-256-cbc -pbkdf2 -in "$ARCHIVE" -out "$TMP_DIR/backup.tar.gz" -pass "pass:$BACKUP_ENCRYPTION_KEY"
  ARCHIVE_TO_EXTRACT="$TMP_DIR/backup.tar.gz"
else
  ARCHIVE_TO_EXTRACT="$ARCHIVE"
fi

tar -xzf "$ARCHIVE_TO_EXTRACT" -C "$TMP_DIR"
PAYLOAD="$TMP_DIR/backup"
PROJECT_DIR="$PAYLOAD/project"
DB_DUMP="$PAYLOAD/database/database.dump"

if [[ ! -f "$PAYLOAD/metadata.json" || ! -f "$DB_DUMP" ]]; then
  echo "Invalid BABAEI backup archive."
  exit 1
fi

mkdir -p "$TARGET_ROOT"
cp -a "$PROJECT_DIR/." "$TARGET_ROOT/"

DB_TYPE="$(python3 - "$PAYLOAD/metadata.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["database"])
PY
)"

if [[ "$DB_TYPE" == "sqlite-online-backup" ]]; then
  mkdir -p "$TARGET_ROOT/config/data/database"
  cp -f "$DB_DUMP" "$TARGET_ROOT/config/data/database/db.sqlite3"
elif [[ "$DB_TYPE" == "postgresql-pgdump" ]]; then
  : "${POSTGRES_DB:?POSTGRES_DB must be set}"
  : "${POSTGRES_USER:?POSTGRES_USER must be set}"
  : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
  export PGPASSWORD="$POSTGRES_PASSWORD"
  pg_restore     --clean --if-exists --exit-on-error     --no-owner --no-privileges     --host "${POSTGRES_HOST:-127.0.0.1}"     --port "${POSTGRES_PORT:-5432}"     --username "$POSTGRES_USER"     --dbname "$POSTGRES_DB"     "$DB_DUMP"
else
  echo "Unsupported database type: $DB_TYPE"
  exit 1
fi

if [[ -d "$PAYLOAD/media" ]]; then
  mkdir -p "$TARGET_ROOT/config/data/media"
  cp -a "$PAYLOAD/media/." "$TARGET_ROOT/config/data/media/"
fi

echo "BABAEI backup restored into: $TARGET_ROOT"
echo "Next: verify .env, run migrations/collectstatic, then start services."
