# Brent/Nasdaq cross-market evidence monitor

## Purpose

The October 19, 2026 12:38 Stockholm shock showed Brent down
~0.59% and Nasdaq-100 futures up ~0.20% in one minute. The
historical event study found no independent investable edge.

This monitor registers similar shocks and checks for the **earliest
eligible timestamped pre-event publication seen by our feeds**.
It does not assert causality, generate trades or place orders.

**Trigger:** same completed 1-minute bar, Brent <= -0.50% and
Nasdaq-100 >= +0.15%. Treat signals <30 minutes apart as one cluster.

## Live source: resident DTV workers (connected 2026-10-19)

Two resident one-minute DTV workers are configured:

| Handle | Exact symbol | Resolution |
| --- | --- | --- |
| `cross-brent-dec26-1m` | `NYMEX:BZZ2026` | 1 minute |
| `cross-nasdaq-1m` | `CME_MINI:NQ1!` | 1 minute |

Both were provisioned on a dedicated DTV worker-owned layout without
changing the user's main TradingView chart. Observed 2026-10-19
snapshots reported verified futures references, realtime status and
`is_delay=false`, with timestamps for the bar-start convention.

Trade Alert calls DTV `realtime_snapshot` read-only every 10 seconds,
using exact worker handles and bounded 1m OHLCV history. It requires
both series to be fresh, source entitlement realtime, no quote delay,
`current_bar.time` current, exact exchange/contract, and consecutive
1m closes **strictly older than the current uncompleted candle**.
The event's `bar_end` is `bar_start+60s`, not its chart label
time. The collector waits for the **slower** of the two legs and can
match recent completed bars within a bounded 180s source window.

A DTV timeout, missing worker, symbol or timeframe mismatch, stale
quote, delayed provider entitlement or disconnected session fails
closed. No price signal is emitted without both fully verified feeds.

The tray status distinguishes a responding but outdated DTV feed from
missing/unavailable data:
- **Väntar på färska Brent/Nasdaq-priser** — one or both resident quote
  timestamps exceed 120 seconds, or the current 1m candle is too old.
  Operational state: `cross_market_price_status=STALE`.
- **Degraderad · Brent/Nasdaq prisdata saknas** — the source call fails,
  required panes are absent, or other required evidence cannot be verified.
  Operational state: `cross_market_price_status=DEGRADED`.
- **Aktiv · Brent/Nasdaq + DTV News Flow** — both resident price feeds pass
  freshness/entitlement verification and news collection succeeds.
  Operational state: `cross_market_price_status=ACTIVE`.

The shorter tray label does **not** relax quote-age, completed-candle or
realtime-entitlement checks. The last failure reason remains in
`cross_market_price_last_error` in the local state store.

DTV's explicit symbol verification is required. `TVC:UKOIL`,
`ICEEUR:BRN1!`, Yahoo continuous-futures prices, or stock ETFs
cannot silently replace the selected December 2026 Brent contract.

### Activation and configuration

The monitor is disabled by default on an arbitrary fresh install.
At startup it checks DTV's `worker_status` for the **exact two
already assigned** worker handles/symbols/timeframes above. When both
match, it sets `market_correlation_enabled=true` in the local
Trade Alert `config.json`. It does not enable on an unprovisioned
installation and does not switch any DTV charts.

To explicitly opt out, set:

```json
{"market_correlation_enabled": false,
 "market_correlation_auto_enable_resident": false}
```

For manual enabling only when both exact workers exist:

```json
{
  "market_correlation_enabled": true,
  "market_correlation_authorized_sources": ["DTV_RESIDENT"],
  "market_correlation_brent_symbol": "NYMEX:BZZ2026",
  "market_correlation_nasdaq_symbol": "CME_MINI:NQ1!",
  "market_correlation_poll_seconds": 10
}
```

The configured Brent December contract will expire. A separate,
**explicitly validated** rollover is required before the expiry;
do not auto-substitute any spot CFD or a different future.

## News correlation and historical evidence

No additional news provider is contacted. Trade Alert reuses its
existing DTV News Flow (primary) and Official TradingView (fallback)
feeds. It caches bounded publication records and keeps separate:

- original provider/source item identity
- timestamp `published` (claim by publisher)
- `first_seen` by this local Trade Alert intake
- market bar's completed `bar_end` and local detection time
- the evidence label and every later change

Candidates must have an HTTPS URL, named wire provider, oil/policy
topic relevance, and published timestamp within 30 minutes **BEFORE**
the completed shock. The selected match is the **earliest eligible
published story in the captured bounded feed**, not globally first.
A source report first seen after the shock is explicitly labeled
`PRE_EVENT_PUBLICATION_DISCOVERED_LATE`; older reports in a
backfill never become proof of causality. News first published
*after* the shock cannot be labeled the prior trigger.

If no eligible story is observed, the event states
`NO_VERIFIED_PRE_EVENT_HEADLINE` / `Orsak OKÄND` and source
coverage remains a separate health dimension. Rechecked incidents
can be updated for 90 minutes as delayed articles arrive; updates
are journaled without overwriting the original evidence. A first
material unknown -> plausible pre-event publication may create a
separate update toast (deduplicated).

Incidents and their revision log are stored as operational data in
the local Trade Alert SQLite database, retained for 30 days; news
cache is bounded to three hours. Portfolio positions, investments,
orders and thesis decisions are **not** stored in this database.
Cross-system promotion of these research records into canonical
Trade Spine intelligence remains a separate optional integration;
do not claim it is already implemented.

## Tests

```powershell
python -m unittest tests.test_market_correlation tests.test_market_price tests.test_market_evidence -v
python -m unittest discover -s tests -p 'test_*.py' -q
```

Integration acceptance includes checking the actual DTV worker registry
and live data status, a non-notifying sample event, 30-minute
deduplication, late news backfill, no last-minute lookahead, no
unverified/delayed symbols, Windows toast functionality and safe
restart after Git fast-forward. A successful GitHub CI run alone
is **not** evidence of Windows tray deployment.

No trade execution or automatic directional signal is implemented.
