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
| DEFENSE | NATO, Pentagon, bomb/bombed/bombing, bomber(s), war, Navy/naval fleet/warships, aircraft carrier(s), carrier(s) in naval context, Air Force, Army | Bombing/airstrike, declared war, carrier deployment/repositioning or other concrete military action |
| TECH | semiconductors, chipmakers, Nvidia, advanced chips, AI | Chip/semiconductor trade controls, bans or security restrictions |
| GEOPOLITICS | Iran, Hormuz, Cuba/Havana, Venezuela/Caracas, China, Russia, Ukraine, Israel, Taiwan | Meaningful conflict/blockade/sanctions/ceasefire statement |

Words such as `carrier` and `carriers` are ambiguous. The classifier
requires nearby naval language (Navy, aircraft, fleet, warships, strike group,
etc.) or geopolitical movement, and filters local commercial terms (mobile,
insurance, shipping, container, freight and airline). It does not treat
generic logistics or telecommunications carriers as military signals.
A carrier strike group's name alone is STANDARD, not a HIGH military strike.

Legacy direct-watch trigger words (oil, Iran, Venezuela, tariffs,
nuclear and related terms) continue to count as relevant at STANDARD level
unless a clearly actionable high-impact statement is present.

Ordinary proper-name mentions such as "met Powell" or "met NATO leaders"
are STANDARD, not HIGH. Generic social posts without a market term and
phrases such as "potato chips" are IGNORE.

## Calibration from 50 real public-image OCR outputs (2026-10-09)

The non-alerting benchmark successfully processed 50 distinct image contents,
but `OCR_OK` confirms process completion, **not text accuracy**. In this
unlabelled set, 2 HIGH and 6 STANDARD classifications require substantive
review before being treated as market alerts. Text-only inspection of the
image outputs exposed three deterministic false-positive patterns:

- The bare word `energy` in a campaign-rally article is not a commodity
  signal. Bare `energy` now requires sector context (`energy industry`,
  `energy prices`, etc.); explicit oil/gas terms remain covered.
- The noun `defense` in `air defense systems`, and the verb/noun `end` in
  `at the end of this video`, no longer count as a new military action.
  Explicit attacks, deployments and ending a war retain their HIGH path.
- Figurative `army of lions` no longer creates military relevance.
  Iranian unrest language can reach STANDARD without exact standalone
  `Iran`, but a demonym such as `Iranian artists` alone remains irrelevant.

Some otherwise readable images discuss past events, hypothetical economic
reports or repeated commentary. Neither OCR success nor these keyword rules
establish that an image depicts a new event. Date/source validation and manual
ground-truth image review remain necessary; no alert is proof of market impact.

## Public image text

The Chrome public-account bridge and the verified direct public account
adapter can classify locally recognized **text in images** (Tesseract OCR)
together with the post's original caption. The source text and OCR-derived
text are separately labelled; extracted words are not verified claims.
For example "DAYS WITH CRUDE OIL ABOVE $100" in an attached chart
qualifies as **STANDARD / ENERGY**, even if the accompanying political
caption has no market terms. No image is sent to a paid/cloud AI service.

Images without approved media URLs, uninstalled/unavailable OCR, embedded
text too stylized to recognize, and videos remain unassessed; the filter does
not infer a chart's causal meaning, present-day prices, accuracy or visual
semantics. Refer to [local image OCR setup](chrome-bridge.md#local-public-image-ocr-extension-v050).

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
- "I admire our Navy and Air Force" -> **STANDARD / DEFENSE**
- "We will bomb Cuba tomorrow" -> **HIGH / DEFENSE**
- "Our Army has deployed to Venezuela" -> **HIGH / DEFENSE**
- "Our aircraft carriers are impressive" -> **STANDARD / DEFENSE**
- "Our carriers are heading to Cuba" -> **HIGH / DEFENSE**
- "War is terrible" -> **STANDARD / DEFENSE**
- "Happy birthday" -> **IGNORE**

Test coverage: `tests/test_trump_filter.py`, alongside existing
`tests/test_truth_direct.py`, `tests/test_chrome_feed.py`,
`tests/test_truth_rss.py`, and `tests/test_news.py`.
