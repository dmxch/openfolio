#!/bin/bash
set -e

echo "=== OpenFolio Entrypoint ==="

# Wait for PostgreSQL to be reachable (belt-and-suspenders on top of healthcheck)
echo "Waiting for database..."
for i in $(seq 1 30); do
    if python -c "
from sqlalchemy import create_engine, text
from config import settings
url = settings.database_url.replace('postgresql+asyncpg://', 'postgresql://')
engine = create_engine(url, pool_pre_ping=True)
with engine.connect() as conn:
    conn.execute(text('SELECT 1'))
engine.dispose()
" 2>/dev/null; then
        echo "Database is ready."
        break
    fi
    echo "  Attempt $i/30 — waiting 2s..."
    sleep 2
done

# Check if database has any tables (fresh install vs. existing)
TABLE_COUNT=$(python -c "
from sqlalchemy import create_engine, text
from config import settings
url = settings.database_url.replace('postgresql+asyncpg://', 'postgresql://')
engine = create_engine(url)
with engine.connect() as conn:
    result = conn.execute(text(
        \"SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'\"
    ))
    print(result.scalar())
engine.dispose()
")

if [ "$TABLE_COUNT" = "0" ]; then
    echo "Fresh database detected (0 tables). Creating schema..."
    python -c "
from models import Base
from db import sync_engine
Base.metadata.create_all(sync_engine)
sync_engine.dispose()
print('All tables created via Base.metadata.create_all().')
"
    alembic stamp head
    echo "Alembic stamped to head."
else
    echo "Existing database ($TABLE_COUNT tables). Running migrations..."
    alembic upgrade head
    echo "Migrations complete."
fi

echo "=== Starting: $@ ==="
exec "$@"
