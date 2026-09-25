#!/bin/sh
# Generate a self-signed certificate unless one was provided in nginx/certs/
set -e
cd /etc/nginx/certs
[ -f cert.pem ] && [ -f key.pem ] && exit 0
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" -keyout key.pem -out cert.pem
