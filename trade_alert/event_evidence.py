"""Conservative, source-scoped evidence triage after Trump topic classification.

A *fresh post* can contain an old graph, a quoted third-party claim or a
counterfactual policy report. This module never asserts independent verification.
No network, LLM, broker or slow background operation is invoked in the hot path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .trump_filter import TrumpSignal, classify_trump_statement


# Specific counterfactual report constructions only: generic 'could' or
# 'would' is insufficient, because conditional policy guidance can move markets.
COUNTERFACTUAL_REPORT = re.compile(
    r"\b(?:if (?:the |those |these )?(?:polic(?:y|ies)|proposals?|plans?|"
    r"measures?) (?:were|was) (?:adopted|enacted|implemented)|"
    r"(?:polic(?:y|ies)|proposals?|plans?) would cost|"
    r"hypothetical (?:scenario|policy|plan)|"
    r"under (?:a|the) hypothetical scenario)\b",
    re.IGNORECASE,
)
RETROSPECTIVE_RECAP = re.compile(
    r"\b(?:historic operations|previously (?:announced|reported|deployed)|"
    r"in (?:the )?previous (?:administration|decade)|"
    r"back in 20\d{2}|"
    r"last (?:year|month)'s (?:military|policy) operations)\b",
    re.IGNORECASE,
)
HISTORICAL_GRAPH = re.compile(
    r"\b(?:days with crude oil above|"
    r"(?:historical|historic) (?:data|chart|trend|comparison)|"
    r"previous elections|"
    r"since (?:20\d{2}|the election) (?:average|record|total))\b",
    re.IGNORECASE,
)
DATA_CONTEXT = re.compile(
    r"\b(?:production hits (?:a )?record high|"
    r"natural gas production|"
    r"pre-war levels|"
    r"recruiting (?:records?|for every branch)|"
    r"enrollment more than double)\b",
    re.IGNORECASE,
)
# Indicates an apparent immediate policy claim from the account caption,
# not proof that the claim is true or its contents have taken effect.
CAPTION_ACTION = re.compile(
    r"\b(?:we (?:are|will|have)|i (?:am|will|have)|"
    r"i signed|we signed|"
    r"effective immediately)\b.{0,160}\b(?:"
    r"impos\w*|ban\w*|restrict\w*|deploy\w*|"
    r"attack\w*|strike\w*|bomb\w*|"
    r"cut\w*|rais\w*|fire\w*|remov\w*|"
    r"withdraw\w*|sign\w*|approv\w*|"
    r"halt\w*|end\w*|sanction\w*|"
    r"tariff\w*|rate\w*)\b",
    re.IGNORECASE | re.DOTALL,
)
THIRD_PARTY_CAPTURE = re.compile(
    r"\b(?:DOW Rapid Response|Laura Loomer|Donald Trump Jr\.|"
    r"@DOWResponse|@LauraLoomer|@netanyahu)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TruthEvidence:
    """Evidence label + the score after narrowly scoped novelty safeguards."""

    event_kind: str  # ACTION_CLAIM | HYPOTHETICAL | RECAP | DATA_CONTEXT | UNRESOLVED
    verification: str  # INDEPENDENT_CONFIRMATION_NOT_CHECKED
    provenance: str  # ACCOUNT_TEXT | IMAGE_TEXT | ACCOUNT_TEXT_AND_IMAGE | ARCHIVE_TEXT
    reason: str
    signal: TrumpSignal
    corroboration_required: bool

    @property
    def label(self) -> str:
        return (
            f"evidens {self.event_kind}; "
            f"{self.verification.lower().replace('_', ' ')}"
        )


def assess_truth_evidence(
    *, caption: str, image_text: str = "", source: str = "DIRECT",
    signal: TrumpSignal | None = None,
) -> TruthEvidence:
    """Assess *claim type*, not truth. Never make a blocking corroboration call.

    A report-only hypothetical in OCR is not a live change in policy. Suppress
    its weak image-only topic alert, unless the original account caption
    independently carries a market signal. A retrospective high-impact quote
    is downgraded to STANDARD only with an explicit recap marker and no
    immediate policy statement in the caption. Unknown/action claims keep
    their original urgency to avoid hiding real surprises.
    """
    if source not in ("DIRECT", "CHROME", "RSS"):
        raise ValueError("Unsupported Truth source")
    caption = caption[:3000]
    image_text = image_text[:4000]
    full_text = " ".join(part for part in (caption, image_text) if part)
    signal = signal if signal is not None else classify_trump_statement(full_text)
    caption_signal = classify_trump_statement(caption) if caption else None
    direct_action = bool(CAPTION_ACTION.search(caption))
    corroboration = "INDEPENDENT_CONFIRMATION_NOT_CHECKED"
    if source == "RSS":
        provenance = "ARCHIVE_TEXT"
    elif caption and image_text:
        provenance = "ACCOUNT_TEXT_AND_IMAGE"
    elif image_text:
        provenance = "IMAGE_TEXT"
    else:
        provenance = "ACCOUNT_TEXT"

    event_kind = "UNRESOLVED"
    reason = "Freshness of the post does not establish freshness of its claims"
    score = signal.score
    image_report = bool(image_text and COUNTERFACTUAL_REPORT.search(image_text))
    caption_relevant = bool(caption_signal and caption_signal.score >= 2)

    if direct_action and signal.score >= 2:
        event_kind = "ACTION_CLAIM"
        reason = "Immediate policy/action language in account caption; claim unverified"
    elif image_report:
        event_kind = "HYPOTHETICAL"
        reason = "OCR describes a counterfactual report, not enacted policy"
        if not caption_relevant and 2 <= score <= 5:
            score = 0
    elif RETROSPECTIVE_RECAP.search(full_text):
        event_kind = "RECAP"
        reason = "Historical/retrospective context is not a new action"
        if image_text and not direct_action and score >= 6:
            score = 4
    elif HISTORICAL_GRAPH.search(full_text) or DATA_CONTEXT.search(full_text):
        event_kind = "DATA_CONTEXT"
        reason = "Statistical/historical context; market novelty is unverified"

    # One copied third-party screenshot cannot be verified just because the
    # Truth account reposted it. No source is ever upgraded automatically.
    if image_text and THIRD_PARTY_CAPTURE.search(image_text) and not direct_action:
        reason += "; image contains a third-party attribution"

    priority = "HIGH" if score >= 6 else "STANDARD" if score >= 2 else "IGNORE"
    adjusted = TrumpSignal(score=score, priority=priority,
                           category=signal.category if score >= 2 else "OTHER")
    return TruthEvidence(
        event_kind=event_kind,
        verification=corroboration,
        provenance=provenance,
        reason=reason,
        signal=adjusted,
        corroboration_required=score >= 2,
    )
