# VPS Deployment

Status: Sprint 21 controlled runtime loop guide

This repository does not execute deployment automatically.

## Requirements

- non-root `strategylab` user
- `/opt/strategylab-v2` working directory
- `/etc/strategylab/gaon.env` outside Git
- systemd service installed from `deploy/systemd/strategylab-gaon.service`

## Commands

```bash
python -m gaon.runtime.cli config-check
python -m gaon.runtime.cli db-check --db /opt/strategylab-v2/runtime.sqlite
python -m gaon.runtime.cli health --db /opt/strategylab-v2/runtime.sqlite
python -m gaon.runtime.cli run --db /opt/strategylab-v2/runtime.sqlite
python -m gaon.runtime.cli status --db /opt/strategylab-v2/runtime.sqlite
sudo systemctl daemon-reload
sudo systemctl enable strategylab-gaon.service
sudo systemctl start strategylab-gaon.service
sudo systemctl status strategylab-gaon.service
```

`run` starts the controlled runtime service path and performs a deterministic tick in this public repository phase. External Telegram, OpenAI, Notion, and broker loops are not claimed as live-verified here.

## Safety

Do not place secrets in Git. Do not run as root. Do not connect private trading systems from this public repository.
