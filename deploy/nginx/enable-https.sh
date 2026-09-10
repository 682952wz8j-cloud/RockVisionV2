#!/usr/bin/env bash
# Shortest post-ICP enablement. Do not run until api.cragpal.com resolves
# publicly to this host and ICP is active.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DOMAIN=api.cragpal.com
LIVE=/etc/letsencrypt/live/${DOMAIN}

echo "1. HTTP hostname origin check"
curl -fsS -m 20 -H "Host: ${DOMAIN}" http://127.0.0.1/health
echo

echo "2. Issue TLS certificate (HTTP-01)"
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d "${DOMAIN}" --agree-tos --non-interactive

echo "3. Enable Nginx HTTPS"
test -f "${LIVE}/fullchain.pem"
test -f "${LIVE}/privkey.pem"
sudo cp "${ROOT}/api.cragpal.com.ssl.conf.template" /etc/nginx/sites-available/api.cragpal.com-ssl
sudo ln -sfn /etc/nginx/sites-available/api.cragpal.com-ssl /etc/nginx/sites-enabled/api.cragpal.com-ssl
sudo nginx -t
sudo systemctl reload nginx

echo "4. HTTPS health and catalog"
curl -fsS -m 20 "https://${DOMAIN}/health"
echo
curl -fsS -m 20 "https://${DOMAIN}/v1/walls"
echo
curl -fsS -m 20 "https://${DOMAIN}/v1/walls/wall_jinshidong_01/releases/r000001/manifest"
echo
echo "Then verify 4 assets and Release production discovery from the app."
