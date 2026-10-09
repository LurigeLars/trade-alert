"""Deterministic multi-asset relevance for a *known Trump account*.

This is intentionally source-scoped: the broad TradingView oil-news filter
remains unchanged. Word boundaries avoid substring hits; high urgency
requires both policy context and a concrete action or consequence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .news import Headline, relevance_score


def _words(*phrases: str) -> re.Pattern[str]:
    return re.compile(
        r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b",
        re.IGNORECASE,
    )


@dataclass(frozen=True, slots=True)
class TrumpSignal:
    score: int
    priority: str     # HIGH | STANDARD | IGNORE
    category: str     # ENERGY | RATES | TRADE | FISCAL | DEFENSE | TECH | GEOPOLITICS | OTHER


# Keep the previous direct/Chrome policy watchlist. Match singular/plural
# inflections deliberately instead of matching inside unrelated words.
LEGACY_POLICY = re.compile(
    r"\b(?:iran|hormuz|venezuela|caracas|cuba|havana|russia|ukraine|israel|china|taiwan|"
    r"tariffs?|sanctions?|embargo|blockade|oil|gasoline|crude|energy|"
    r"nuclear|federal reserve|interest rates?|attack|strikes?|"
    r"war|military|opec|trade deal|ceasefire)\b", re.IGNORECASE
)

RATES = _words(
    "fed", "federal reserve", "fomc", "powell", "treasury",
    "treasury yields", "bond yields", "interest rate", "interest rates",
    "rate cuts", "rate cut", "rate hike", "rate hikes", "quantitative easing",
    "quantitative tightening", "central bank",
)
TRADE = _words(
    "tariff", "tariffs", "duties", "import duty", "import duties",
    "trade agreement", "trade deal", "trade war", "embargo", "sanction",
    "sanctions", "export control", "export controls", "export restrictions",
    "import ban", "import bans", "trade restrictions",
)
FISCAL = _words(
    "congress", "debt ceiling", "government shutdown", "federal shutdown",
    "us default", "national debt", "stimulus", "budget deal", "federal budget",
    "spending bill", "tax bill", "taxes", "tax cut", "tax cuts",
)
DEFENSE = _words(
    "nato", "pentagon", "missile", "missiles", "airstrike", "airstrikes",
    "troops", "troop", "invasion", "military", "nuclear weapon",
    "nuclear weapons", "defense spending", "defence spending",
)
TECH = _words(
    "semiconductor", "semiconductors", "chipmaker", "chipmakers",
    "advanced chips", "chip exports", "ai chips", "nvidia",
    "artificial intelligence", "export controls", "export restrictions",
)
CHIPS = _words("chips", "chip")
TECH_CONTEXT = _words(
    "export", "exports", "semiconductor", "semiconductors", "nvidia",
    "china", "taiwan", "ai", "artificial intelligence", "ban", "bans",
)
GEO = _words(
    "iran", "tehran", "hormuz", "russia", "ukraine", "israel",
    "taiwan", "venezuela", "caracas", "cuba", "havana", "north korea", "middle east",
    "china", "ceasefire", "blockade", "nuclear",
)
ENERGY = _words(
    "oil", "crude", "brent", "wti", "opec", "gasoline", "diesel", "energy",
    "refinery", "refineries", "lng", "natural gas", "pipeline",
)
# Concrete statements and changes, not generic "deal" / "great" / "bad".
POLICY_ACTION = re.compile(
    r"\b(?:impos(?:e|es|ed|ing)|announc(?:e|es|ed|ing)|"
    r"sign(?:s|ed|ing)?|approv(?:e|es|ed|ing)|"
    r"ban(?:s|ned|ning)?|block(?:s|ed|ing)?|restrict(?:s|ed|ing)?|"
    r"remov(?:e|es|ed|ing)|suspend(?:s|ed|ing)?|"
    r"rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|"
    r"reduc(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
    r"cut(?:s|ting)?|hike(?:s|d)?|"
    r"fire(?:s|d)?|dismiss(?:es|ed|ing)?|replace(?:s|d|ment)?|"
    r"resign(?:s|ed|ation)?|appoint(?:s|ed|ment)?|nomina(?:te|tes|ted|tion)|"
    r"withdraw(?:s|al|n)?|deploy(?:s|ed|ment)?|"
    r"attack(?:s|ed|ing)?|strik(?:e|es|ing)|"
    r"launch(?:es|ed|ing)?|halt(?:s|ed|ing)?|"
    r"end(?:s|ed|ing)?|cancel(?:s|led|ling)?|"
    r"default(?:s|ed|ing)?|shutdown|shut down|"
    r"emergency|executive order|effective immediately)\b",
    re.IGNORECASE,
)
# Rate/financial system actions should not require accidental generic phrases.
RATES_ACTION = re.compile(
    r"\b(?:rate (?:cut|cuts|hike|hikes|increase|reduction)|"
    r"interest rate(?:s)? (?:cut|cuts|hike|hikes|increase)|"
    r"(?:cut|cuts|cutting|reduce|reduces|reducing|"
    r"raise|raises|raising|hike|hikes|hiking|"
    r"lower|lowers|lowering|increase|increases|increasing)"
    r" (?:interest )?rates?|"
    r"fire(?:s|d)?|replace|remov(?:e|ing)|resign|"
    r"emergency|quantitative easing|quantitative tightening|"
    r"intervention|independence|nomina(?:te|ted|tion)|appoint(?:s|ed)?)\b",
    re.IGNORECASE,
)
TRADE_ACTION = re.compile(
    r"\b(?:impos(?:e|es|ed|ing)|new|hike(?:s|d)?|rais(?:e|es|ed|ing)|"
    r"expand(?:s|ed|ing)?|ban(?:s|ned|ning)?|restrict(?:s|ed|ing)?|"
    r"remov(?:e|es|ed|ing)|lift(?:s|ed|ing)?|"
    r"suspend(?:s|ed|ing)?|sign(?:s|ed|ing)?|"
    r"announc(?:e|es|ed|ing)|executive order|effective immediately)\b",
    re.IGNORECASE,
)
FISCAL_CRISIS = _words(
    "government shutdown", "federal shutdown", "us default",
    "debt default", "debt ceiling crisis",
)
DEFENSE_ACTION = re.compile(
    r"\b(?:withdraw(?:s|al|n)?|leav(?:e|ing)|exit|"
    r"deploy(?:s|ed|ing|ment)?|attack(?:s|ed|ing)?|"
    r"strike(?:s)?|striking|invad(?:e|es|ed|ing)|invasion|"
    r"defen(?:d|se)|mobiliz(?:e|es|ed|ing)|"
    r"cut(?:s|ting)?|raise|increase|end|halt|ceasefire|"
    r"launch(?:es|ed|ing)?|blockade)\b",
    re.IGNORECASE,
)


def classify_trump_statement(text: str) -> TrumpSignal:
    """Score a source-authenticated post. No market quote or LLM guesses.

    0–1 = IGNORE, 2–5 = STANDARD, 6–10 = HIGH.
    The category names the dominant market mechanism, not the author's tone.
    """
    excerpt = text[:3000]
    # Preserve legacy coverage, including Hormuz and oil-context cases,
    # without changing the generic TradingView score for third-party news.
    legacy = relevance_score(Headline(
        source="TRUTH_PUBLIC", item_id="candidate",
        title="Trump statement: " + excerpt[:1500], published=None,
    ))
    if LEGACY_POLICY.search(excerpt):
        legacy = max(legacy, 4)

    candidates: list[tuple[int, str]] = []
    if ENERGY.search(excerpt):
        candidates.append((max(4, legacy), "ENERGY"))
    if GEO.search(excerpt):
        geo_score = 6 if (POLICY_ACTION.search(excerpt)
                          and _words("attack", "attacks", "attacking",
                                     "strike", "strikes", "military", "blockade",
                                     "sanctions", "ceasefire").search(excerpt)) else 4
        candidates.append((geo_score, "GEOPOLITICS"))
    if RATES.search(excerpt):
        candidates.append((7 if RATES_ACTION.search(excerpt) else 2, "RATES"))
    if TECH.search(excerpt) or (CHIPS.search(excerpt) and TECH_CONTEXT.search(excerpt)):
        # "I love potato chips" must not generate a technology alert.
        tech_action = bool(TRADE_ACTION.search(excerpt))
        candidates.append((7 if tech_action else 2, "TECH"))
    if TRADE.search(excerpt):
        candidates.append((7 if TRADE_ACTION.search(excerpt) else 4, "TRADE"))
    if FISCAL.search(excerpt):
        candidates.append((7 if (FISCAL_CRISIS.search(excerpt) or
                                  POLICY_ACTION.search(excerpt)) else 2, "FISCAL"))
    if DEFENSE.search(excerpt):
        candidates.append((7 if DEFENSE_ACTION.search(excerpt) else 2, "DEFENSE"))

    # Avoid category inflation from overlapping keywords; HIGH requires a
    # concrete impact-bearing context in one category, not unrelated nouns.
    legacy_category = (
        "ENERGY" if ENERGY.search(excerpt) else
        "RATES" if RATES.search(excerpt) else
        "TRADE" if TRADE.search(excerpt) else
        "FISCAL" if FISCAL.search(excerpt) else
        "DEFENSE" if DEFENSE.search(excerpt) else
        "TECH" if TECH.search(excerpt) else "GEOPOLITICS"
    )
    candidates.append((legacy, legacy_category))
    score, category = max(candidates, key=lambda x: x[0])
    score = max(0, min(10, score))
    priority = "HIGH" if score >= 6 else "STANDARD" if score >= 2 else "IGNORE"
    return TrumpSignal(score=score, priority=priority,
                       category=category if score >= 2 else "OTHER")
