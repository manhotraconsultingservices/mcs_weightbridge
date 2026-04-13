#!/bin/bash
# Docker entrypoint init script: creates weighbridge_master database
# This runs only on first container init (when data volume is empty).
set -e

echo "=== Weighbridge Multi-Tenant DB Init ==="

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create master database if it doesn't exist
    SELECT 'CREATE DATABASE weighbridge_master OWNER ${POSTGRES_USER}'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'weighbridge_master')\gexec
EOSQL

echo "=== weighbridge_master database ensured ==="
