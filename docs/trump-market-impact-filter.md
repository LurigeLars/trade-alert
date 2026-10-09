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

## Separate evidence and novelty triage

The Truth direct, Chrome and third-party RSS pipelines now call
`trade_alert.event_evidence.assess_truth_evidence` **after** the unchanged
source-scoped topic classifier. The result contains an `event_kind`, original
provenance, effective score/priority, a bounded reason and the explicit
`INDEPENDENT_CONFIRMATION_NOT_CHECKED` state.

This is **not** an external fact-check. Public-account identity authenticates
where the post came from, **not** the accuracy, timing or origin of a screenshot.
The third-party RSS feed is still not a primary-source authentication.

| Evidence state | Treatment |
| --- | --- |
| `ACTION_CLAIM` | Immediate delivery with normal priority; source-authored policy action claims are still **unverified** |
| `HYPOTHETICAL` | Narrow OCR-only counterfactual-policy report with no relevant account caption has its weak STANDARD alert suppressed; other claims retained |
| `RECAP` | Explicitly retrospective image claim cannot create a *new* HIGH by itself; otherwise retain contextual STANDARD |
| `DATA_CONTEXT` | Historical chart or statistical context still reaches its existing topic-based STANDARD alert, labelled as context rather than a fresh policy action |
| `UNRESOLVED` | Retain existing classification and clearly mark external corroboration unperformed |

The action detector does not use generic verbs such as `would` as proof that
a rule is enacted, nor does a post's recent publication date prove a screenshot
is recent. All new labels appear in alert bodies; no new API, credentials,
network request, blocking verification step or model inference is introduced.
External confirmation from reliable independent reporting is required before
treating a quoted claim as established fact. It is **not** automatically
performed by this release, and there is no automatic post-hoc upgrade.

The local no-network `scripts/replay_truth_evidence.py --input PATH` command
re-evaluates OCR text in a saved benchmark JSON. **The original 50-image
benchmark does not contain captions**; the replay therefore gives an OCR-only
upper/lower-bound diagnostic, not exact predictions of live post notifications.

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

Image-only posts with supported public image attachments can be classified via\nlocal OCR; video-only posts without text remain unassessed.

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
