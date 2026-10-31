# FastAPI-Based Microservices for E-Commerce Backend

Project 67 | Python / FastAPI | Docker | PostgreSQL | Redis | RabbitMQ | Nginx

## Overview

This project is a containerised e-commerce backend composed of five independently
runnable FastAPI services. It demonstrates service ownership, protected APIs,
inter-service mTLS, resilient communication, asynchronous notifications, and
deployment validation.

### Services

| Service | Responsibility | Compose port |
|---|---|---:|
| Auth | Registration, login, password hashing, JWT access tokens | 8001 |
| Product | Product CRUD, search, pagination, Redis cache, stock reservation | 8002 |
| Cart | Per-user cart and protected product validation | 8003 |
| Order | Idempotent orders, server-side totals, stock reservation, outbox | 8004 |
| Notification | Notification history and duplicate-safe event handling | 8005 |
| Nginx gateway | Public HTTPS entry point and routing/rate limiting | 8443 |

PostgreSQL databases, Redis, RabbitMQ, an outbox relay, and a notification
consumer are included in the Docker Compose deployment.

## Repository layout

```text
services/       FastAPI service applications
shared/         Security, storage, cache, mTLS, AMQP, and resilience helpers
scripts/        Service launchers, certificate generation, seed utility, workers
gateway/        Nginx TLS and routing configuration
infra/          PostgreSQL and RabbitMQ infrastructure configuration
tests/          Unit, integration, resilience, security, and load tests
data/           Data dictionary; raw datasets are intentionally local-only
```

## Requirements

### Docker deployment

- Docker Desktop with Linux containers and Compose v2
- Git
- PowerShell on Windows, or Bash on macOS/Linux
- OpenSSL (Git Bash or WSL on Windows)

### Local Python development

- Python 3.12
- `pip`
- A virtual environment is strongly recommended

Python 3.12 is the supported development version because the pinned scientific
dependencies have not been certified on every newer Python release.

## First-time setup on a new device

### 1. Get the project

```powershell
git clone <repository-url>
Set-Location hcltech
```

If you received the source as an archive, extract it and open the project root.
Do not open only a service subdirectory.

### 2. Create local secrets

```powershell
Copy-Item .env.example .env
```

Replace every `replace_with_...` value in `.env` with a unique random secret.
Never commit `.env`. `.env.example` is intentionally tracked and is the safe
configuration template for new developers.

Generate values with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 3. Generate development certificates

From Git Bash:

```bash
bash scripts/generate_certs.sh
```

The generated `certs/` directory contains local development CA, gateway,
service, and RabbitMQ certificates. It is ignored by Git. Do not use these
development certificates as production PKI.

### 4. Validate and start Docker

```powershell
docker version
docker compose config
docker compose build
docker compose up -d
docker compose ps
```

Wait until PostgreSQL, Redis, RabbitMQ, and all services show healthy status.
If service containers were recreated, recreate the gateway too so Nginx
refreshes upstream container addresses:

```powershell
docker compose up -d --force-recreate
```

### 5. Seed an administrator

Use a unique password of at least 12 characters:

```powershell
docker compose exec `
  -e ADMIN_EMAIL=admin@example.local `
  -e ADMIN_PASSWORD="Use-A-Unique-Password-Here!" `
  auth-service python scripts/seed_admin.py
```

### 6. Verify the gateway

The local gateway is available at `https://localhost:8443`.
Because the local CA is not normally trusted by the operating system, use
`-k` for a development-only check:

```powershell
curl.exe -k -i https://localhost:8443/auth/me
```

HTTP 401 is expected without an access token and confirms gateway routing.

## Local Python-only development

This mode uses SQLite fallback and plain HTTP between locally started services.
It is useful for unit and service tests, not a substitute for Docker validation.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:DATABASE_DIR="./var"
$env:JWT_SECRET="local-development-secret-change-me"
pytest -q
python -m compileall -q .
```

Start each service from the repository root in a separate terminal:

```powershell
.\scripts\run_auth.sh
.\scripts\run_product.sh
.\scripts\run_cart.sh
.\scripts\run_order.sh
.\scripts\run_notification.sh
```

On Windows, run shell scripts from Git Bash or WSL. Swagger documentation is
available at `http://127.0.0.1:8001/docs` through `8005/docs`.

## API workflow

1. Register a customer: `POST /auth/register`.
2. Log in: `POST /auth/login`.
3. Use the returned bearer token for customer requests.
4. Seed or log in as an administrator.
5. Create a product: `POST /products`.
6. Add it to the cart: `POST /cart/items`.
7. Create an order: `POST /orders` with a unique `Idempotency-Key`.
8. Read notifications: `GET /notifications`.
9. Repeat the order request with the same idempotency key and verify the same
   order is returned.

The gateway exposes these versioned service APIs:

| Gateway route | Main operations |
|---|---|
| `/auth/*` | Register, login, current user |
| `/products/*` | List, search, create, update, delete, reserve stock |
| `/cart/*` | Read, add, update, remove, clear |
| `/orders/*` | Create idempotent orders, list, retrieve |
| `/notifications/*` | Notification history and retrieval |

FastAPI Swagger pages are also available at each local service's `/docs`
endpoint when running the local Python profile.

## Testing and validation

### Local tests

```powershell
pytest -q
python -m compileall -q .
```

### Docker-backed tests

```powershell
docker compose exec -T auth-service pytest -q tests/test_core.py tests/test_services.py
docker compose exec -T auth-service pytest -q tests/test_live_system.py
docker compose exec -T auth-service pytest -q tests/test_resilience_and_security.py
docker compose exec -T auth-service python tests/load_test.py
```

The RabbitMQ integration test requires explicit TLS environment variables. The
validation commands are intended to be run against the current Docker
environment; generated reports and logs are intentionally excluded from Git.

## Configuration and data policy

- `.env.example` is tracked; `.env` is ignored.
- `certs/` is generated locally and ignored.
- `docs/`, `logs/`, `reports/`, `var/`, Python caches, coverage output, and PID
  files are local-only and excluded from Git.
  are ignored.
- Raw datasets belong in `data/raw/` and are ignored because they may be
  supplied separately. The tracked data dictionary remains available.
- Do not commit credentials, private keys, local databases, generated reports,
  or production customer data.

## Operations

```powershell
docker compose logs --tail=100 auth-service product-service cart-service order-service notification-service
docker compose logs --tail=100 outbox-relay notification-consumer gateway
docker compose down
```

`docker compose down -v` deletes development database, cache, and broker
volumes. Use it only when intentionally resetting local development data.

## Security and production guidance

The implementation includes scrypt password hashing, JWT issuer/audience and
expiry validation, role checks, Redis-backed rate limiting, circuit breaking,
transactional outbox storage, duplicate-safe notifications, mTLS for internal
HTTP, and TLS client authentication for RabbitMQ.

Before public production deployment, replace local secrets and certificates
with managed secret/PKI systems, configure backups and restore drills,
monitoring and alerting, centralized log retention, high availability, a
sustained target-scale load test, and an independent security review.

## Project summary

The architecture uses Nginx as the only externally published application
endpoint. Auth issues JWTs, Product owns catalogue and stock data, Cart calls
Product through a circuit breaker, Order reserves stock and writes an
outbox event transactionally, and Notification consumes `order.placed`
events idempotently. PostgreSQL databases are service-owned, Redis provides
cache and distributed rate limiting, and RabbitMQ uses TLS with client
certificate verification.

The repository includes source code, tests, infrastructure configuration,
deployment configuration, the environment template, and this self-contained
setup guide. Local IDE state, operator notes, generated reports, logs,
certificates, and supplementary `docs/` working files are intentionally
excluded from version control.
