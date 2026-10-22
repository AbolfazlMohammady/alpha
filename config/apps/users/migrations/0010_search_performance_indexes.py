from django.db import migrations


INDEXES = (
    (
        "users_user_first_name_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS users_user_first_name_trgm_idx "
        "ON users_user USING gin (first_name gin_trgm_ops)",
    ),
    (
        "users_user_last_name_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS users_user_last_name_trgm_idx "
        "ON users_user USING gin (last_name gin_trgm_ops)",
    ),
    (
        "users_user_email_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS users_user_email_trgm_idx "
        "ON users_user USING gin (email gin_trgm_ops)",
    ),
    (
        "users_user_phone_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS users_user_phone_trgm_idx "
        "ON users_user USING gin (phone gin_trgm_ops)",
    ),
)


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for _name, sql in INDEXES:
            cursor.execute(sql)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        for name, _sql in reversed(INDEXES):
            cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("users", "0009_remove_address_users_address_other_recipient_name_required"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
