#!/bin/sh
set -eu
SERVICE="${SERVICE_NAME:?SERVICE_NAME is required}"
PORT="${SERVICE_PORT:?SERVICE_PORT is required}"
if [ "${REQUIRE_MTLS:-false}" = "true" ]; then
  exec uvicorn "services.${SERVICE}_service:app" --host 0.0.0.0 --port "$PORT" \
    --ssl-certfile "/certs/${SERVICE}.crt" --ssl-keyfile "/certs/${SERVICE}.key" \
    --ssl-ca-certs /certs/ca.crt --ssl-cert-reqs 2
else
  exec uvicorn "services.${SERVICE}_service:app" --host 0.0.0.0 --port "$PORT"
fi
