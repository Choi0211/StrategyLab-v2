# Gaon Binance Conversation Dashboard Integration

Status: IMPLEMENTED

This integration pass keeps Telegram and Web on the same Gaon
conversation brain while tightening production-facing dashboard contracts.

## Response Path

- Telegram: `TelegramConversationAgent.handle()` builds an
  `LLMConversationRequest` and calls `LLMConversationBrain.respond()`.
- Web: `GaonWebChatAdapter.handle()` receives `POST /gaon/chat` and calls
  the same `LLMConversationBrain.respond()` path.
- Transport adapters format the result, but the research routing,
  context, safety gates, and renderer remain shared.

## API Root

The Gaon Web API now answers `GET /` with read-only service discovery:

- service name
- status
- health endpoint
- chat endpoint
- research mission endpoint
- storage status endpoint

The root route does not execute chat, research, approvals, storage cleanup,
orders, strategy mutation, Champion promotion, or approval bypass.

## Safety

Schema remains v36. No live trading, KIS/Broker order, automatic Champion
promotion, approval bypass, strategy mutation, service restart, or
production deployment is added.

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-web-api-root-release-check
```
