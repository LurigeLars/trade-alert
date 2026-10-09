# Trump Monitor: multi-asset market impact filter

This is the source-scoped classifier used by the Chrome Downloads bridge,
anonymous direct Truth Social adapter (where reachable), and third-party
Trump's Truth RSS fallback. All three use
`trade_alert.trump_filter.classify_trump_statement`. The general DTV and
TradingView news logic in `trade_alert.news.relevance_score` is NOT changed.

## Why

A statement about the Fed, Powell, export controls, NATO, debt ceiling,
Congressional budget votes or semiconductors may materially affect markets
without ever mentioning crude oil. This Trump-account-specific filter
expands coverage while avoiding the transfer of broad political keywords to
unrelated TradingView provider headlines.

## Deterministic categories

| Category | Typical match | HIGH requires |
| --- | --- | --- |
| ENERGY | oil, Brent, OPEC, LNG, pipelines | Relevant existing geopolitics/energy scoring; bare oil remains STANDARD |
| RATES | Fed, Federal Reserve, FOMC, Powell, Treasury, bond yields | Explicit rate or Fed governance intervention, removal/appointment, emergency policy |
| TRADE | tariffs, sanctions, trade deal, export controls, duties | Imposition, removal, expansion, agreement, announcement or effective restriction |
| FISCAL | Congress, debt ceiling, government shutdown, budgets, taxes | Shutdown/default or a concrete fiscal policy action |
| DEFENSE | NATO, Pentagon, troops, missiles, invasion | Concrete troop/military posture or action |
| TECH | semiconductors, chipmakers, Nvidia, advanced chips, AI | Chip/semiconductor trade controls, bans or security restrictions |
| GEOPOLITICS | Iran, Hormuz, Cuba/Havana, Venezuela/Caracas, China, Russia, Ukraine, Israel, Taiwan | Meaningful conflict/blockade/sanctions/ceasefire statement |

Legacy direct-watch trigger words (oil, Iran, Venezuela, tariffs,
nuclear and related terms) continue to count as relevant at STANDARD level
unless a clearly actionable high-impact statement is present.

Ordinary proper-name mentions such as "met Powell" or "met NATO leaders"
are STANDARD, not HIGH. Generic social posts without a market term and
phrases such as "potato chips" are IGNORE.

## Priority and delivery

- **HIGH**: score 6–10; explicit subject-specific action/consequence.
- **STANDARD**: score 2–5; relevant policy/market context without a strong
  action signal.
- **IGNORE**: score 0–1, no toast under the standard minimum score 2.

The existing `notification_min_score` applies to all three Trump
adapters and remains configurable (default 2). The notifier's Windows
toast *title and body* identify HIGH/STANDARD and category; this does not
change Windows notification priority API settings, play a special sound, or
place a trade. There is no portfolio- or price-based inference in this
keyword classifier. No additional polling or requests are introduced.

All classifications are heuristic. They do not verify Truth Social claims
or prove that a statement will move a market. Source attribution, freshness,
baseline and post-ID deduplication still run independently of this filter.

The RSS archive is a third-party source: applying the same wording-based
filter does not upgrade it to verified primary-source evidence. Cross-source
duplicate risk (RSS vs direct/Chrome) remains a separate outstanding issue.

Media-only posts cannot be classified from their image/video content and are
skipped by the existing ingestion pipeline.

## Examples

- "Fed to replace Powell immediately" -> **HIGH / RATES**
- "100% tariffs on China effective tomorrow" -> **HIGH / TRADE**
- "Government shutdown begins" -> **HIGH / FISCAL**
- "Ban exports of advanced chips to China" -> **HIGH / TECH**
- "Met NATO leaders today" -> **STANDARD / DEFENSE**
- "Happy birthday" -> **IGNORE**

Test coverage: `tests/test_trump_filter.py`, alongside existing
`tests/test_truth_direct.py`, `tests/test_chrome_feed.py`,
`tests/test_truth_rss.py`, and `tests/test_news.py`.
