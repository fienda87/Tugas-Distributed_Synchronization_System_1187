#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$OUT_DIR"

openssl genrsa -out "$OUT_DIR/ca.key" 4096
openssl req -x509 -new -nodes -key "$OUT_DIR/ca.key" -sha256 -days 3650 -subj "/CN=dist-ca" -out "$OUT_DIR/ca.crt"

openssl genrsa -out "$OUT_DIR/server.key" 4096
openssl req -new -key "$OUT_DIR/server.key" -subj "/CN=dist-server" -out "$OUT_DIR/server.csr"
openssl x509 -req -in "$OUT_DIR/server.csr" -CA "$OUT_DIR/ca.crt" -CAkey "$OUT_DIR/ca.key" -CAcreateserial -out "$OUT_DIR/server.crt" -days 825 -sha256

openssl genrsa -out "$OUT_DIR/client.key" 4096
openssl req -new -key "$OUT_DIR/client.key" -subj "/CN=dist-client" -out "$OUT_DIR/client.csr"
openssl x509 -req -in "$OUT_DIR/client.csr" -CA "$OUT_DIR/ca.crt" -CAkey "$OUT_DIR/ca.key" -CAcreateserial -out "$OUT_DIR/client.crt" -days 825 -sha256

echo "Generated CA, server, and client certs in $OUT_DIR"
