#!/bin/sh

# DuckDNS Authenticator Hook for Certbot
# Called by Certbot during DNS-01 challenge to update DuckDNS TXT record.

if [ -z "$DUCKDNS_TOKEN" ]; then
    echo "Error: DUCKDNS_TOKEN environment variable is not set."
    exit 1
fi

# Extract the subdomain (e.g., 'susi' from 'susi.duckdns.org')
SUBDOMAIN=$(echo "$CERTBOT_DOMAIN" | sed 's/\.duckdns\.org//')

echo "Sending TXT record to DuckDNS for subdomain: $SUBDOMAIN"

# DuckDNS only supports GET requests, so the token must be in the URL.
# We cannot use a POST request body to hide it from intermediate logs.
RESPONSE=$(wget -qO- "https://www.duckdns.org/update?domains=${SUBDOMAIN}&token=${DUCKDNS_TOKEN}&txt=${CERTBOT_VALIDATION}")

if [ "$RESPONSE" = "OK" ]; then
    echo "Successfully updated DuckDNS TXT record."
else
    echo "Failed to update DuckDNS TXT record. Response: $RESPONSE"
    exit 1
fi

# Wait for DNS propagation
echo "Waiting 30 seconds for DNS propagation..."
sleep 30