#!/usr/bin/env sh
cd "$(dirname "$0")/.."
exec uvicorn services.product_service:app --host 0.0.0.0 --port 8002
