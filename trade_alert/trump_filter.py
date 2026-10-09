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
    r"tariffs?|sanctions?|embargo|blockade|oil|gasoline|crude|"
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
    # Armed services, formations and equipment. Names alone are STANDARD.
    "navy", "naval", "fleet", "fleets", "warship", "warships",
    "air force", "air forces", "airforce", "army", "armies",
    "armed forces", "ground forces", "fighter jet", "fighter jets",
    "aircraft carrier", "aircraft carriers",
    # Include literal English equivalents of bomb, bomber and war.
    "bomb", "bombs", "bombed", "bombing", "bomber", "bombers",
    "bombard", "bombards", "bombarded", "bombarding", "bombardment",
    "air strike", "air strikes", "war", "wars", "warfare",
    "military operation", "military operations",
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
# Demonyms alone are often incidental. Pair an Iran reference with unrest
# language; a social-media screenshot is relevance evidence, not confirmation.
IRAN_UNREST = re.compile(
    r"\biranian(?:s)?\b.{0,120}\b(?:protest(?:s|ers|ing)?|unrest|"
    r"on the streets|take back their country|uprising)\b|"
    r"\b(?:protest(?:s|ers|ing)?|unrest|uprising)\b.{0,120}\biranian(?:s)?\b",
    re.IGNORECASE,
)
ENERGY = _words(
    "oil", "crude", "brent", "wti", "opec", "gasoline", "diesel",
    "refinery", "refineries", "lng", "natural gas", "pipeline",
)
# Require a sector meaning for the ambiguous bare word 'energy'.
ENERGY_CONTEXT = _words(
    "energy industry", "energy sector", "energy policy", "energy prices",
    "energy price", "energy supply", "energy security", "energy crisis",
    "energy production", "energy exports", "energy imports",
    "energy infrastructure", "energy companies", "energy markets",
    "energy investment", "energy transition", "energy costs",
)
# "Carrier" / "carriers" are ambiguous (aircraft carriers, telecom,
# shipping and insurance). Match naval references, not the bare words.
CARRIER_TERMS = _words("carrier", "carriers")
CARRIER_MILITARY_CONTEXT = _words(
    "aircraft", "navy", "naval", "fleet", "warship", "warships",
    "fighter jets", "fighter aircraft", "task force", "battle group",
    "strike group", "carrier group", "carrier groups", "warplanes",
    "military", "pentagon", "supercarrier", "supercarriers",
)
CARRIER_COMMERCIAL_CONTEXT = _words(
    "mobile", "cellular", "wireless", "phone", "telecom", "insurance",
    "health insurance", "shipping", "container", "containers", "cargo",
    "freight", "parcel", "packages", "postal", "airline", "5g",
)
CARRIER_MOVEMENT = _words(
    "deploy", "deploys", "deployed", "deploying", "deployment",
    "sail", "sails", "sailed", "sailing", "move", "moves", "moved",
    "moving", "head", "heads", "headed", "heading", "approach",
    "approaches", "approached", "approaching", "dispatch", "dispatched",
    "dispatching", "reposition", "repositioned", "repositioning",
    "send", "sends", "sending", "sent", "arrive", "arrived", "arriving",
    "enter", "enters", "entered", "entering", "stationed", "stationing",
)
CARRIER_LOCATION = _words(
    "iran", "tehran", "hormuz", "venezuela", "caracas", "cuba", "havana",
    "taiwan", "china", "red sea", "persian gulf", "caribbean",
    "middle east",
)


def _military_carrier_reference(text: str) -> bool:
    """Require naval context, or deployment in a geopolitical location."""
    for match in CARRIER_TERMS.finditer(text):
        nearby = text[max(0, match.start() - 100):match.end() + 100]
        if CARRIER_COMMERCIAL_CONTEXT.search(nearby):
            continue
        if CARRIER_MILITARY_CONTEXT.search(nearby):
            return True
        if CARRIER_LOCATION.search(nearby) and CARRIER_MOVEMENT.search(nearby):
            return True
    return False


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
    r"defend(?:s|ed|ing)?|mobiliz(?:e|es|ed|ing)|"
    r"cut(?:s|ting)?|raise|increase|halt|ceasefire|"
    r"launch(?:es|ed|ing)?|blockade|"
    r"bomb(?:ed|ing)|bombard(?:s|ed|ing|ment)?|"
    r"air\s?strikes?|air\s?raids?|"
    r"dispatch(?:es|ed|ing)?|mobilis(?:e|es|ed|ing)|"
    r"declar(?:e|es|ed|ing)\s+war|"
    r"end(?:s|ed|ing)?\s+(?:the\s+)?(?:war|hostilities|blockade|"
    r"military operations?)|"
    r"enter(?:s|ed|ing)?\s+(?:a\s+)?war|"
    r"war\s+(?:begins|began|has\s+begun))\b",
    re.IGNORECASE,
)


# Bare nouns such as "a bomb", "bombers" or "war" trigger STANDARD.
# Explicit intent (will bomb), a bombing action, or a war declaration is HIGH.
BOMB_INTENT = re.compile(
    r"\b(?:will|to|going to|plan to|plans to|intend to|intends to|may|"
    r"might|could)(?:\s+not)?\s+bomb\b", re.IGNORECASE,
)
BOMBING_VERB = re.compile(
    r"\b(?:bombs|bombed|bombing)\b", re.IGNORECASE,
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
    energy_context = bool(ENERGY.search(excerpt) or ENERGY_CONTEXT.search(excerpt))
    if energy_context:
        candidates.append((max(4, legacy), "ENERGY"))
    if GEO.search(excerpt) or IRAN_UNREST.search(excerpt):
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
    # The OCR corpus contained a figurative "army of lions" on a civil
    # aviation screenshot. Treat that idiom as figurative, not armed forces.
    defense_excerpt = re.sub(
        r"\barmy of (?:lions|fans|supporters|volunteers|followers)\b",
        "", excerpt, flags=re.IGNORECASE,
    )
    carrier_military = _military_carrier_reference(defense_excerpt)
    if DEFENSE.search(defense_excerpt) or carrier_military:
        # "Carrier strike group" is a naval formation, not an actual
        # military strike. Don't upgrade it to HIGH on that noun alone.
        defense_action_text = re.sub(
            r"\bcarrier\s+strike\s+groups?\b",
            "carrier group", excerpt, flags=re.IGNORECASE,
        )
        military_action = bool(
            DEFENSE_ACTION.search(defense_action_text)
            or BOMB_INTENT.search(excerpt)
            or BOMBING_VERB.search(excerpt)
            or (carrier_military and CARRIER_MOVEMENT.search(excerpt))
        )
        candidates.append((7 if military_action else 2, "DEFENSE"))

    # Avoid category inflation from overlapping keywords; HIGH requires a
    # concrete impact-bearing context in one category, not unrelated nouns.
    legacy_category = (
        "ENERGY" if energy_context else
        "RATES" if RATES.search(excerpt) else
        "TRADE" if TRADE.search(excerpt) else
        "FISCAL" if FISCAL.search(excerpt) else
        "DEFENSE" if DEFENSE.search(excerpt) or carrier_military else
        "TECH" if TECH.search(excerpt) else "GEOPOLITICS"
    )
    candidates.append((legacy, legacy_category))
    score, category = max(candidates, key=lambda x: x[0])
    score = max(0, min(10, score))
    priority = "HIGH" if score >= 6 else "STANDARD" if score >= 2 else "IGNORE"
    return TrumpSignal(score=score, priority=priority,
                       category=category if score >= 2 else "OTHER")
