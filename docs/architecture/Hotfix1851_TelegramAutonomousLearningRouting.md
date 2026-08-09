# Hotfix 185.1 - Telegram Autonomous Learning Routing

Status: COMPLETE

## Problem

Autonomous Learning V2 release checks could reach `requires_human_approval`,
but Telegram natural-language research requests were not routed into that
orchestration. Long Korean requests that combined "research again", "find
evidence", "use learned evidence", "test improved candidates", and "ask for
approval if eligible" could fall back to a generic unknown/help answer.

## Design

Hotfix 185.1 adds a read-only `autonomous_learning_research` safe tool wrapper
around the existing Autonomous Learning V2 E2E orchestration. The Telegram
conversation brain now recognizes natural autonomous-learning research intents
before generic real-research routing, resolves the current KRX symbol from the
message or same-chat context, executes the existing authoritative KRX baseline,
then invokes the existing V2 learning gate.

Continuation requests such as "계속 연구해줘" reuse the current chat target.
When no target or same-chat research context exists, Gaon asks for the target
instead of guessing.

## Invariants

- The route is read-only.
- Strategy configuration is not mutated.
- Champion promotion is not automatic.
- KIS/Broker orders are not called.
- Approval-sounding language stops at the human approval boundary and does not
  infer approval.
- The response is rendered from structured authoritative payloads.

## Release Check

```bash
python -m gaon.runtime.cli gaon-telegram-autonomous-learning-routing-release-check --db :memory:
```

The check proves natural Korean routing, `symbol=005930` resolution,
continuation target preservation, Autonomous Learning V2 selection, no
fallback/help response, human approval boundary preservation, no strategy
mutation, and no broker/KIS order.
