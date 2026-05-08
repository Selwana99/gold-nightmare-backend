#!/usr/bin/env bash
# PostgreSQL backup script — designed for Render or any pg-compatible host
# Usage: ./scripts/backup_db.sh [output_dir]
# Reads DATABASE_URL from .env or environment

set -e

OUTPUT_DIR="${1:-./backups}"
mkdir -p "$OUTPUT_DIR"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

if [ -z "$DATABASE_URL" ]; then
    echo "❌ DATABASE_URL not set"
    exit 1
fi

CLEAN_URL=$(echo "$DATABASE_URL" | sed 's/postgresql+asyncpg/postgresql/' | sed 's/postgres+asyncpg/postgres/')

if [[ ! "$CLEAN_URL" =~ ^postgres ]]; then
    echo "❌ Backup script only supports PostgreSQL databases"
    exit 1
fi

TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
OUTFILE="$OUTPUT_DIR/gn_vision_${TIMESTAMP}.sql.gz"

echo "📦 Backing up to $OUTFILE..."
pg_dump "$CLEAN_URL" --no-owner --no-acl --clean --if-exists | gzip > "$OUTFILE"

SIZE=$(du -h "$OUTFILE" | cut -f1)
echo "✓ Backup complete: $OUTFILE ($SIZE)"

find "$OUTPUT_DIR" -name "gn_vision_*.sql.gz" -type f | sort | head -n -30 | xargs -r rm
echo "✓ Old backups pruned (keeping last 30)"
