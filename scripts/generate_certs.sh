#!/bin/sh
set -eu
OUT="${1:-certs}"
mkdir -p "$OUT"
chmod 700 "$OUT"
openssl genrsa -out "$OUT/ca.key" 4096
openssl req -x509 -new -nodes -key "$OUT/ca.key" -sha256 -days 3650 \
  -subj "/CN=Ecommerce Development CA" -out "$OUT/ca.crt"
for name in auth product cart order notification gateway rabbitmq; do
  openssl genrsa -out "$OUT/$name.key" 2048
  openssl req -new -key "$OUT/$name.key" -subj "/CN=$name-service" -out "$OUT/$name.csr"
  printf "subjectAltName=DNS:%s,DNS:%s-service,DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth,clientAuth\n" "$name" "$name" > "$OUT/$name.ext"
  openssl x509 -req -in "$OUT/$name.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" \
    -CAcreateserial -out "$OUT/$name.crt" -days 825 -sha256 -extfile "$OUT/$name.ext"
  rm "$OUT/$name.csr" "$OUT/$name.ext"
done
chmod 600 "$OUT"/*.key
echo "Development CA and service certificates generated in $OUT. Never commit private keys."
