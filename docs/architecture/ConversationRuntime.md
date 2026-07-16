# Conversation Runtime

Status: Implemented Contract

Conversation Runtime receives source messages and returns deterministic responses.

## Supported Intents

- HELP
- STATUS
- TODAY_PLAN
- RECENT_RESEARCH
- SEARCH_MEMORY
- RESEARCH_STATUS
- CONFLICTS
- DUPLICATES
- REVALIDATION_DUE
- DAILY_REPORT
- WEEKLY_REVIEW
- SYNC_NOTION
- APPROVAL_STATUS
- UNKNOWN

## Safety

Conversation Runtime does not:

- approve knowledge
- apply policy
- change user preferences
- execute research automatically
- execute shell or arbitrary code
- place trades
- mutate GitHub or repositories

Approval commands return an approval-required response and remain candidates for a future approval runtime.
