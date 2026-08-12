# Hotfix 192.2 - Relevant Academic Discovery and Safe DOI Redirect

Status: COMPLETE

## Root Causes

Production Telegram Autonomous Learning V2 exposed two separate blockers after
Hotfix 192.1.

First, academic discovery queries were too generic. The production question was
effectively `005930 breakout strategy robustness evidence`, so Crossref could
return unrelated computer-science records that happened to contain words such as
`strategy` or `robustness`.

Second, DOI resolution used the generic content URL validator for every
redirect hop. Some DOI resolver chains can include a temporary HTTP
intermediate redirect before reaching a final HTTPS publisher/resource URL, so
the resolver blocked the chain before recording enough diagnostic context.

Fixing only DOI redirects would have made the system more likely to acquire
irrelevant documents. Hotfix 192.2 therefore adds relevance screening before
content acquisition and keeps DOI redirect relaxation isolated to the DOI
resolution transport.

## Query Design

For `strategy.breakout.robustness`, discovery now uses deterministic
strategy-specific academic terms:

- financial markets
- breakout
- trend following
- moving average
- volume confirmation
- technical trading rules
- stop-loss / trailing exit
- out-of-sample robustness
- transaction costs

The KRX symbol remains part of runtime context, but it is not treated as the
primary academic search term.

## Relevance Screening

Discovery results are screened before content acquisition. The deterministic
screen uses returned metadata only:

- title
- abstract
- subjects
- publisher
- container title

Accepted results must include both a financial/trading domain signal and a
strategy/mechanism signal. Negative non-financial domains such as distributed
systems, tuple recovery, networking, database recovery, and software
architecture are fail-closed unless the source also clearly identifies a
financial/trading domain.

Relevance states are:

- `relevant`
- `insufficient_relevance`
- `wrong_domain`
- `insufficient_metadata`

Rejected results are never fetched and cannot create grounded evidence.

## DOI Redirect Safety

Generic content acquisition remains HTTPS-only. The only relaxation is inside
dedicated DOI resolution:

- initial DOI URL must be HTTPS
- DOI resolver host remains explicitly allowed
- redirect hops may use `http` or `https`
- every hop must avoid credentials, unsafe ports, private, loopback, link-local,
  multicast, reserved, and unspecified destinations
- redirect count remains bounded
- final content URL must be HTTPS
- final content URL must pass the normal content host allowlist

HTTP final destinations, unauthorized publisher hosts, credentials, unsafe
schemes, private/local hosts, and redirect-limit failures remain blocked.

## Observability

Production structured payloads now expose:

- generated academic queries
- result title, provider, DOI, and locator
- relevance status, score, matched terms, rejected reason, and selected flag
- locator kind and content resolution status
- redirect chain and final host
- acquisition status, final URL, MIME type, content hash, and source ID
- grounded evidence count

Normal Telegram responses remain concise. If all academic results are
irrelevant, Korean output distinguishes that state from generic content fetch
failure.

## Safety

- no live trading
- no KIS/Broker order
- no automatic Champion promotion
- no automatic config apply
- no approval bypass
- no strategy mutation during research
- no fixture-backed promotion
- no metadata-only evidence promotion
- no irrelevant-source evidence promotion
- no fabricated evidence or metrics

Schema remains v36. No runtime DB migration was added.

## Release Checks

- `gaon-production-relevant-academic-discovery-release-check`
- `gaon-production-safe-doi-redirect-release-check`
- `gaon-production-relevant-academic-content-loop-release-check`

