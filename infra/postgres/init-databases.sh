#!/bin/sh
set -eu
create_service_db() {
  user="$1"; db="$2"; password="$3"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    --set=user="$user" --set=db="$db" --set=password="$password" <<'SQL'
SELECT format('CREATE USER %I WITH PASSWORD %L', :'user', :'password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'user') \gexec
SQL
}
create_service_db auth_user auth_db "$AUTH_DB_PASSWORD"
create_service_db product_user product_db "$PRODUCT_DB_PASSWORD"
create_service_db cart_user cart_db "$CART_DB_PASSWORD"
create_service_db order_user order_db "$ORDER_DB_PASSWORD"
create_service_db notification_user notification_db "$NOTIFICATION_DB_PASSWORD"
