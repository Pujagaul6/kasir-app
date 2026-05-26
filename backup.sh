#!/bin/bash
# Auto-backup kasir.db — keep last 7 days
BACKUP_DIR="/home/ubuntu/kasir-app/backups"
DB="/home/ubuntu/kasir-app/kasir.db"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

if [ -f "$DB" ]; then
    cp "$DB" "$BACKUP_DIR/kasir_$DATE.db"
    echo "✅ Backup created: kasir_$DATE.db"
    
    # Keep only last 7 days of backups
    find "$BACKUP_DIR" -name "kasir_*.db" -mtime +7 -delete
    echo "🧹 Old backups cleaned (kept last 7 days)"
else
    echo "❌ Database not found: $DB"
fi
