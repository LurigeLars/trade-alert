# Brent/Nasdaq cross-market event correlation (optional, fail closed)

Research motivation: 2026-10-19 at 12:38 Stockholm time, Brent crude
fell about 0.59% in one minute while the Nasdaq-100 future gained about
0.20%. The historical research rule used **Brent <= -0.50%** and
**NQ >= +0.15%** for the **same completed minute**, with a 30-minute
deduplication interval. Neither a causal mechanism nor an investable
edge was demonstrated. This is an **evidence-gathering notifier**, not
an executable trading strategy.

## Current status: producer NOT connected

The Trade Alert app already obtains news from DTV News Flow and its
existing Official TradingView fallback. It **does not currently provide
a verified two-symbol, one-minute, live price stream**. This feature is
disabled by default. Do not claim it is active just because the code is
deployed. The local market-data producer must be independently
implemented, validated and explicitly enabled before production.

The existing price/news ingestion architecture must supply synchronous
**realtime, completed 1-minute candles** from an explicitly verified
Brent futures contract and Nasdaq-100 future. No delayed quotes,
synthetic spot CFD substituted for Brent futures, missing minute, or
unverified contract rolls are permitted.

## Local handoff contract

Configure the application's local `config.json` (never Git):

```json
{
  "market_correlation_enabled": true,
  "market_correlation_brent_symbol": "NYMEX:BZZ2026",
  "market_correlation_nasdaq_symbol": "CME_MINI:NQ1!",
  "market_correlation_authorized_sources": ["TRADE_SPINE_LOCAL"]
}
```

The symbols above are **illustrative as of 19 October 2026**, not
evergreen instrument identifiers. The source must validate exactly which
underlying and futures month it supplies. Explicitly change the local
configuration at contract roll. Do not silently substitute CFD prices.

The authenticated/approved local producer writes a JSON file **atomically**
(temp file + rename) to
`%LOCALAPPDATA%/TradeAlert/cross-market-inbox/*.json`:

```json
{
  "event_id": "2026-10-19T10:38:00Z-Brent-NQ",
  "provider": "TRADE_SPINE_LOCAL",
  "bar_seconds": 60,
  "realtime": true,
  "delayed": false,
  "brent": {
    "symbol": "NYMEX:BZZ2026",
    "bar_end": "2026-10-19T10:39:00Z",
    "previous_close": 108.73,
    "close": 108.09
  },
  "nasdaq": {
    "symbol": "CME_MINI:NQ1!",
    "bar_end": "2026-10-19T10:39:00Z",
    "previous_close": 29688.25,
    "close": 29746.75
  }
}
```

One-minute chart bars are commonly labeled by their **opening minute**.
The candle labeled 10:38 UTC finishes at **10:39 UTC**, so the contract
requires its completed **bar_end** (10:39), not its opening timestamp.
Publishing that minute's close at 10:38 would introduce look-ahead bias.

**Historical sample only; do not replay it into an active inbox.**
Both exact source symbols, timestamps, prior completed closes and
current completed closes are mandatory. The event must arrive within
`market_correlation_max_age_seconds` (180s by default), never in the
future, and must be explicitly realtime. Source allowlisting plus
localhost/NTFS access control are required: source ID *alone* is not
authentication. An untrusted file writer could claim to be an
allowlisted producer, so only use an access-controlled directory on
the user's machine.

## Classification

The market event is stored in the app's existing bounded local alert
history (30 newest alerts); durable thesis/evaluation records remain
Trade Spine's responsibility.

On ingestion, the app examines the **headlines present in the current
DTV/Official fetch**. It retains only materially oil-relevant headlines
from a short list of named wire providers with a valid HTTPS URL and a
verified published timestamp in the 30 minutes **before** the market
shock. The first of those by timestamp is labeled
`TIMESTAMP_MATCH_ONLY`. This means **the earliest eligible published
headline observed in the supplied bounded news snapshot**, *not* the
global first publication or a verified cause.

If none is found, the alert explicitly says `Orsak OKÄND`.
Reports published after the shock cannot be causal triggers. News
source degradation must remain visible independently of this feature.
The market shock alert is distinct from ordinary oil-news alerts, so
no previously registered market alert is sent again.

Follow-up enhancement (not activated here): have Trade Spine store a
canonical incident record and re-run the linkage when late/backfilled
news arrives, preserving `published_at`, `first_seen_at`, original
provider ID and revisions. This first iteration matches the headlines
actually supplied on the shock cycle; it does **not** claim exhaustive
historical backfill matching.

## Acceptance tests

```powershell
python -m unittest tests.test_market_correlation -v
python -m unittest discover -s tests -p 'test_*.py'
```

Required deployment gates: authorized producer, realtime entitlement,
correct reference mapping, clock synchronization, no time-gap filling,
news-source health, dedupe under rapid repeats, no order routing,
verified Windows toast behavior, and a manually triggered synthetic
test **without** production notification.
