# Fast policy alerts

Trade Alert now has an independent, one-second local inbox consumer.
The existing DTV/Official TradingView news fetch cycle is separate.
Validated inbound stories are saved to local unread alert history and
shown through Windows notifications without waiting for Trade Spine.

## Availability and permissions

No new external feed is connected. The default source allowlist is empty.
The implementation does not scrape or connect to Truth Social.
The platform's terms restrict automated access; only independently
authorized data providers should submit events.

## Local transport

Input folder: %LOCALAPPDATA%/TradeAlert/breaking-inbox/
A licensed adapter writes a temporary file then atomically renames it
to a unique .json file containing these required JSON fields:

- source_id: identifier approved in local Trade Alert configuration
- event_id: stable originating provider post or story identifier
- acquisition: LICENSED or AUTHORIZED_RELAY
- published_at: ISO-8601 with explicit timezone
- headline: source's statement or short accurate description
- url: HTTPS link to original source

The config keys are breaking_inbox_enabled, breaking_poll_seconds,
breaking_max_age_seconds and breaking_authorized_sources. Default values
are true, 1.0, 300, and [] respectively.

An empty allowlist means no new policy source is currently live.
Setting a source allowlist does not grant provider collection rights.
For a Truth Social primary source, the origin URL, account and post ID
must match the declared event. Input is treated as untrusted text.

## Safeguards

- Reject unapproved sources, malformed or oversized payloads and forged links
- Suppress stale payloads and duplicate event IDs
- Keep an unread history entry when a Windows notification API fails
- Do not automatically place orders or treat statements as verified events
- No provider credentials or personal portfolio state in this repository

One-second polling describes only the latency between arrival in the
local inbox and its processing. Acquisition/relay latency is separate.
Production readiness requires a genuinely authorized source and end-to-end
latency measurement; adding this inbox alone does not create a live feed.
