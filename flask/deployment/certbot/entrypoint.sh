#!/bin/sh

# Certbot Auto-Renewal Entrypoint
# Periodically checks and renews Let's Encrypt certificates.

if [ -z "$DOMAIN_NAME" ]; then
    echo "Error: DOMAIN_NAME environment variable is not set."
    exit 1
fi

echo "Starting Certbot Let's Encrypt auto-renewal service for $DOMAIN_NAME..."

chmod +x /opt/certbot/authenticator.sh

# Main renewal loop
while :; do
    echo "Checking certificate status for $DOMAIN_NAME..."

    # Obtain or renew certificate via DuckDNS DNS-01 challenge
    certbot certonly \
        --non-interactive \
        --agree-tos \
        -m "${CERTBOT_EMAIL:-admin@${DOMAIN_NAME}}" \
        --manual \
        --preferred-challenges dns \
        --manual-auth-hook /opt/certbot/authenticator.sh \
        -d "$DOMAIN_NAME" \
        --cert-name susi \
        --keep-until-expiring

    echo "Certbot check completed. Sleeping for 12 hours..."
    sleep 12h
done