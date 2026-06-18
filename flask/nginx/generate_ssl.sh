#!/bin/sh
set -e

CERT_DIR="/etc/nginx/ssl"
CERT_KEY="${CERT_DIR}/nginx-selfsigned.key"
CERT_CRT="${CERT_DIR}/nginx-selfsigned.crt"

mkdir -p "$CERT_DIR"


if [ ! -f "$CERT_CRT" ] || [ ! -f "$CERT_KEY" ]; then
    echo "Generating self-signed SSL certificate..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$CERT_KEY" \
        -out "$CERT_CRT" \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"
    echo "SSL certificate successfully generated!"
else
    echo "SSL certificate already exists. Skipping generation."
fi