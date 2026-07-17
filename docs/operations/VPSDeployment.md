# VPS Deployment

Status: Sprint 17 deployment guide only

This repository does not execute deployment automatically.

## Requirements

- non-root `strategylab` user
- `/opt/strategylab-v2` working directory
- `/etc/strategylab/gaon.env` outside Git
- systemd service installed from `deploy/systemd/strategylab-gaon.service`

## Commands

```bash
sudo systemctl daemon-reload
sudo systemctl enable strategylab-gaon.service
sudo systemctl start strategylab-gaon.service
sudo systemctl status strategylab-gaon.service
```

## Safety

Do not place secrets in Git. Do not run as root. Do not connect private trading systems from this public repository.
