#!/bin/sh
set -e

# Nginx SSL Bootstrap Script
# Generates temporary dummy certificates if real ones are missing on startup.
# Also handles periodic Nginx reloads to pick up renewed certificates.

if [ -z "$DOMAIN_NAME" ]; then
    echo "Error: DOMAIN_NAME environment variable is not set."
    exit 1
fi

# Cert name matches DOMAIN_NAME 
CERT_DIR="/etc/letsencrypt/live/${DOMAIN_NAME}"
CERT_KEY="${CERT_DIR}/privkey.pem"
CERT_CRT="${CERT_DIR}/fullchain.pem"

mkdir -p "$CERT_DIR"

# Generate dummy certificates if missing
if [ ! -f "$CERT_CRT" ] || [ ! -f "$CERT_KEY" ]; then
    echo "Certificates not found. Generating dummy certificates to bootstrap Nginx..."
    openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
        -keyout "$CERT_KEY" \
        -out "$CERT_CRT" \
        -subj "/CN=${DOMAIN_NAME}"
    echo "Dummy certificates generated successfully."
else
    echo "Certificates found at ${CERT_DIR}. Skipping bootstrap."
fi

# Process nginx.conf.template -> nginx.conf using DOMAIN_NAME
echo "Generating /etc/nginx/nginx.conf from template..."
envsubst '$DOMAIN_NAME' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
echo "nginx.conf generated successfully."

# Background process to gracefully reload Nginx every 6 hours
(
    while :; do
        sleep 6h
        echo "Auto-reloading Nginx to pick up renewed SSL certificates..."
        nginx -s reload
    done
) &