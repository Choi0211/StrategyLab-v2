# HTTPS setup (nginx + Let's Encrypt)

This is a runbook for a human to follow manually. Nothing here is executed
automatically by any script in this repo.

## Prerequisites

- A domain name pointed (A/AAAA record) at the VPS's public IP.
- Port 80 and 443 open on the VPS firewall.
- nginx installed (`apt install nginx` on Debian/Ubuntu).

## Steps

1. Copy the example config and fill in your real domain:
   ```
   cp deploy/nginx/strategylab-binance.conf.example /etc/nginx/sites-available/strategylab-binance.conf
   # edit the file, replace every <YOUR_DOMAIN> with your real domain
   ln -s /etc/nginx/sites-available/strategylab-binance.conf /etc/nginx/sites-enabled/
   nginx -t
   systemctl reload nginx
   ```

2. Install certbot and obtain a certificate (the nginx plugin edits the
   config in place to add the ACME challenge location and redirect, and
   fills in the real cert paths - review the diff it makes before reloading
   if you want to keep the example file's structure otherwise intact):
   ```
   apt install certbot python3-certbot-nginx
   certbot --nginx -d <YOUR_DOMAIN>
   ```

3. Confirm auto-renewal is set up (certbot installs a systemd timer or cron
   job on most distros by default):
   ```
   systemctl list-timers | grep certbot
   certbot renew --dry-run
   ```

## Access control (do this before relying on the reverse proxy alone)

The example nginx config only rate-limits; it does not authenticate anyone.
Before exposing this publicly, add ONE of:

- HTTP basic auth on the `location /gaon/` block (`htpasswd` + `auth_basic`
  directives) for a minimal single-operator gate.
- An IP allowlist (`allow <your-ip>; deny all;`) if you only ever access
  this from known networks.
- A proper auth layer in front of the Binance dashboard if it doesn't
  already have one - check `binance_ai_bot`'s own deploy docs.

Never rely on "the URL is hard to guess" as your only protection - this
service can read Binance account/position data and Gaon's research state
(all read-only per the code's own safety invariants, but still not meant
for public/anonymous access).

## Verifying end to end

```
curl -sf https://<YOUR_DOMAIN>/gaon/health
```
should return `{"schema_version": 1, "status": "ok"}` once gaon-web.service
is running and the proxy is configured correctly.
