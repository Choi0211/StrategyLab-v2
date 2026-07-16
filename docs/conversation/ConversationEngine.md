# Conversation Engine

Status: Planned for Sprint 17

The Conversation Engine will allow Gaon to converse through Telegram for research workflows.

Sprint 11 only defines the future boundary. It does not implement Telegram runtime behavior.

## Allowed Conversation Scope

- research request
- research status
- research report
- recent activity summary
- learning memory summary

## Forbidden Conversation Scope

- live trading command execution
- broker order execution
- secret display or mutation
- account data access
- automatic policy changes

## Shared State Rule

The Conversation Engine and Dashboard must share the same Learning State.

They must not maintain separate truth sources for memory, knowledge, research status, or policy approval.
