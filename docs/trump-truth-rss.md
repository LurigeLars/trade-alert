# Independent Trump statement RSS monitor

**Provider:** [Trump's Truth RSS](https://www.trumpstruth.org/feed), an independent archive
run by Defending Democracy Together. Its FAQ explicitly offers public RSS,
and says new posts are generally captured every few minutes. The RSS feed
is *not* a direct Truth Social source or a guarantee of first-in-market access.

## Architecture and source terms

Trade Alert polls the archive feed independently of the existing Desktop
TradingView/Trade Spine loops. This intentionally avoids waiting for the
hourly Portfolio Watch. Trade Alert does not scrape or call Truth Social.

- HTTPS-only fixed endpoint, redirect host/path allowlist and response cap.
- Conditional GET (ETag, Last-Modified), 8-second request deadline.
- 30-second poll interval by default; exponential failure backoff to 10 minutes.
- XML parsed without DTD/entities; invalid links or timestamps are ignored.
- First successful poll baselines history without notifying.
- Stable RSS GUID dedupe via local operational StateStore; only fresh, relevant
  posts trigger Windows notifications and unread local alert history.
- Show archive attribution, original RSS publication timestamp and
  publication-to-alert delay. Publisher clock and archive delay are not proven.
- Failures logged; no broker access or automatic orders.

## Settings (local config.json)

    "truth_rss_enabled": true,
    "truth_rss_poll_seconds": 30,
    "truth_rss_max_age_seconds": 900

The source is enabled by default after upgrading; this does NOT ensure that
it is reachable in the running environment. A startup baseline occurs only
after the first successful poll.

## Test and deployment

Run full Python unit tests in repo. Fetch one live sample with:

    uv run --python 3.12 python -m trade_alert --rss-once

This command returns a compact source status without dumping the full feed.
A normal restart is required to load the updated Python modules.

Run the above command once to verify source access from your Windows host
after updating and restarting the application.

## Faster option to consider

Follow Trump's Truth independently advertises paid push and webhook delivery,
including a Professional tier at USD 14.99/month and signed webhook payloads.
It has NOT been integrated, independently latency-benchmarked or purchased.
If tested in future, any webhook must verify HMAC, use HTTPS, persist only
validated events to the existing fast inbox, and avoid putting credentials
in the Git repository.

## Limits

Source may lag posts by minutes, contain retransmissions, omit media, and
report feed capture time rather than original publication time. The current
adapter strictly treats RSS dates as provider-declared, not independently
validated Truth Social publication times. First run/old posts are suppressed.
All timestamps must be measured against real posts before claiming a trading edge.
