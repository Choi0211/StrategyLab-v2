# Hotfix: Morning Briefing Research State Consistency

Status: Implemented

## Context

Production Telegram pre-market briefings rendered the news-local sentence
`추가로 필요한 연구가 없습니다.` when no important overnight news created a
follow-up research item. At the same time, the canonical Research Mission
could still be active with `promotion-ready: 0/3`, an active candidate, and
unresolved robustness blockers.

## Root Cause

`render_pre_market_briefing_ko()` only inspected the briefing's
news-derived `research_actions`. It did not read or render canonical
`ResearchMission` state, so a news-only "no follow-up" condition could be
read as a global autonomous-research completion statement.

## Design

- News follow-up state is now rendered under `[뉴스]` and scoped as
  `새 뉴스에서 파생된 추가 연구 항목은 없습니다.`
- Canonical ResearchMission state is rendered under a separate
  `[Research Mission]` section when available.
- The production daily briefing worker reads the latest persisted
  Telegram conversation `research_mission` from `conversation_sessions`
  metadata using a read-only helper.
- User-facing briefing timestamps are rendered in Asia/Seoul as
  `YYYY-MM-DD HH:MM KST`; persisted timestamps remain UTC.

## Read-Only Contract

The morning briefing never executes a research action. It only renders
already persisted canonical state:

- scope
- active candidate
- promotion-ready progress
- mission status
- next blocker-driven research action
- unresolved candidate blockers

No strategy mutation, order execution, Champion promotion, or approval
bypass is introduced.

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-morning-briefing-research-state-consistency-release-check
```

The check proves:

- no-news follow-up text is scoped to news only
- active `0/3` ResearchMission is shown as 진행 중
- active candidate and next action are visible
- `3/3` awaiting-human-approval state is displayed distinctly
- restart reads the canonical mission snapshot from SQLite
- UTC `2026-08-22T00:00:05Z` renders as `2026-08-22 09:00 KST`
- briefing rendering remains read-only and safety-preserving
