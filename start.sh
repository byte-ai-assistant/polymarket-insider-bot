#!/bin/bash

# Polymarket Insider Trading Bot - Quick Start Script

set -e

echo "🚀 Starting Polymarket Insider Trading Bot..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your credentials before running again."
    exit 1
fi

# Start services
echo "🐳 Starting Docker services..."
docker-compose up -d postgres redis

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL..."
sleep 5

# Initialize database
echo "📊 Initializing database..."
python -c "
import asyncio
from src.database.connection import init_db
asyncio.run(init_db())
print('✅ Database initialized')
"

# Start bot
echo "🤖 Starting bot..."
if [ "$1" = "docker" ]; then
    docker-compose up bot
else
    python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
fi
