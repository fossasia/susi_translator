#!/bin/sh
set -e

# Directory and file paths for the SSL certificates inside the container
CERT_DIR="/etc/nginx/ssl"
CERT_KEY="${CERT_DIR}/nginx-selfsigned.key"
CERT_CRT="${CERT_DIR}/nginx-selfsigned.crt"

# Create the directory for the SSL certificates if it doesn't exist
mkdir -p "$CERT_DIR"


# Check if the SSL certificate and key already exist
if [ ! -f "$CERT_CRT" ] || [ ! -f "$CERT_KEY" ]; then
    echo "Generating self-signed SSL certificate..."
    # Generate a new 2048-bit RSA self-signed certificate valid for 365 days
    # without prompting for subject information (-nodes and -subj are used)
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$CERT_KEY" \
        -out "$CERT_CRT" \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"
    echo "SSL certificate successfully generated!"
else
    echo "SSL certificate already exists. Skipping generation."
fi