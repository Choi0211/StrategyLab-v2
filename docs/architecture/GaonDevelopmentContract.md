# Gaon Development Contract v1.0

Project Name: Gaon Platform  
Repository: StrategyLab-v2  
Branch: develop-v2  
Project Owner: Choi Youngha  
Chief Architect: ChatGPT  
AI Name: Gaon  
Status: Sprint 11 Development Start  

## 1. Project Goal

Gaon Platform's first objective is not automated trading.

The first objective is an AI Quant Research Platform.

StrategyLab is the first Research Lab operated by Gaon.

## 2. Highest Current Priority

Do not develop Plugin, Audio, Unreal, JUCE, or unrelated program-development projects now.

Current scope:

```text
Gaon Platform
  -> StrategyLab
  -> MyMoneyGuard V1 Integration
```

## 3. Sprint 11 to Sprint 20 Goals

- Sprint 11: Research Brain
- Sprint 12: Learning Memory
- Sprint 13: Strategy Generator
- Sprint 14: V1 Adapter
- Sprint 15: Validation
- Sprint 16: Knowledge Research
- Sprint 17: Telegram Conversation
- Sprint 18: Dashboard
- Sprint 19: Autonomous Research
- Sprint 20: Research RC

## 4. Research Memory Rename

Existing planning terminology must use `Learning Memory`, not `Research Memory`.

Learning Memory is not a simple storage layer. It is the system where Gaon accumulates AI experience.

## 5. Learning Engine Package

Sprint 11 introduces this package boundary:

```text
gaon/
  learning/
    memory/
    evidence/
    knowledge/
    experience/
    policy/
    confidence/
```

## 6. Learning Memory

Gaon must store:

- Research Goal
- Research Plan
- Experiment
- Backtest Result
- Validation Result
- Failure Reason
- Success Pattern
- User Preference
- Knowledge
- Citation
- Conversation Summary

## 7. Evidence Engine

All important information must have evidence.

Evidence sources include:

- Source
- URL
- Document
- Research
- Paper
- Official Documentation
- Backtest
- Experiment

Information without evidence must not be promoted to Knowledge.

## 8. Knowledge Engine

Knowledge lifecycle:

```text
Collected
  -> Reviewed
  -> Need Validation
  -> Validated
  -> Deprecated
```

Knowledge must not automatically become `Validated`.

## 9. Autonomous Learning Boundary

Gaon may learn autonomously, but must not autonomously:

- modify source code
- change prompts
- operate champions
- change secrets
- change trading rules
- delete user preferences

## 10. Learning Loop

```text
Question
  -> Research
  -> Evidence
  -> Knowledge
  -> Experiment
  -> Validation
  -> Learning Memory
  -> Policy Update Candidate
  -> User Approval
```

Policy changes only after approval.

## 11. User Preference

Gaon learns the user's working style, including:

- documentation first
- Blueprint first
- evidence first
- V1 reuse
- test first
- Korean documentation preference

## 12. Conversation Engine

Sprint 17 adds Telegram conversation capability.

It must support research conversation and status reporting without trading.

## 13. Dashboard

Dashboard state must show:

- Running
- Queue
- Research
- Champion
- Rejected
- Learning
- Memory
- Knowledge
- Recent Conversation

## 14. V1 Adapter

Do not redevelop MyMoneyGuard V1 backtest capability.

Only these ports are public:

- BacktestPort
- OptimizerPort
- WalkForwardPort
- MonteCarloPort

Actual implementation belongs in the private repository.

## 15. AI Personality

Gaon is not a search engine. Gaon is a partner.

Gaon thinks, develops, researches, and learns together with the user. Gaon admits uncertainty and provides evidence.

## 16. Engineering Standard

```text
Blueprint
  -> ADR
  -> Implementation
  -> Unit Test
  -> Integration Test
  -> Documentation
  -> Review
  -> PR
```

## 17. Documentation Set

Required document areas:

- `docs/adr/`
- `docs/rfc/`
- `docs/learning/`
- `docs/research/`
- `docs/conversation/`
- `docs/architecture/`

The repository keeps lowercase directory names for cross-platform consistency with the existing docs tree.

## 18. Test Rule

Every sprint requires passing:

- Unit
- Integration
- Regression
- Golden Fixture where applicable
- GitHub Actions

## 19. Sprint 20 Target

At Sprint 20, Gaon should support this research MVP flow:

```text
Youngha
  -> "Gaon, research Korean stock intraday strategies."
  -> Research Goal
  -> Research Plan
  -> V1 Backtest
  -> Validation
  -> Champion
  -> Dashboard
  -> Telegram Report
```

## 20. After Sprint 20

After Sprint 20, new projects may begin:

- PluginLab
- AudioLab
- DevLab
- LearningLab

All projects are managed through Gaon.

## 21. Project Motto

Good strategies are not discovered by accident.

They are born from good research systems.

## 22. Most Important Rule

Gaon learns autonomously, but does not change itself without validation.

All learning must preserve:

- Evidence
- Version
- Approval
- Rollback

## Final Directive

During Sprint 11 through Sprint 20:

- Do not prioritize features over architecture.
- Do not redevelop MyMoneyGuard V1.
- Implement Learning Memory as the project core.
- Design Dashboard and Telegram to share the same Learning State.
- Add tests and documentation with every new feature.
- Do not complete a sprint unless GitHub Actions passes.
- Do not add secrets, brokers, or API keys to the public repository.
- Record important design decisions as ADRs.
- Support user approval and rollback for all policy changes.
- Target Research MVP stability by Sprint 20 before expanding to PluginLab, AudioLab, and DevLab.

Gaon is not an automated trading AI. Gaon is Youngha's AI Engineering Partner for research, development, learning, and creation, and StrategyLab is the first research lab.

가온은 자동매매 AI가 아니다. 영하님의 연구, 개발, 학습, 창작을 함께하는 AI Engineering Partner이며, StrategyLab는 그 첫 번째 연구실이다.
