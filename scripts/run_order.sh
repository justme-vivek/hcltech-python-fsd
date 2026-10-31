#!/usr/bin/env sh
cd "$(dirname "$0")/.."
exec uvicorn services.order_service:app --host 0.0.0.0 --port 8004
