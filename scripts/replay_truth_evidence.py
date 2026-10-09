"""Replay the local OCR benchmark through current classifier and evidence triage.

Does not fetch images, access accounts, write app state or send notifications.
Historical benchmark contains OCR text only (no post captions), so this is an
OCR-only diagnostic; it is not proof of live end-to-end decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trade_alert.event_evidence import assess_truth_evidence
from trade_alert.trump_filter import classify_trump_statement


def replay(payload: dict) -> dict:
    records = payload.get("results")
    if not isinstance(records, list):
        raise ValueError("OCR report must contain a results list")
    before: Counter = Counter()
    after: Counter = Counter()
    kinds: Counter = Counter()
    changes: list[dict] = []
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "OCR_OK":
            continue
        text = record.get("ocr_text")
        if not isinstance(text, str):
            raise ValueError("OCR_OK row has no text")
        current = classify_trump_statement(text)
        evidence = assess_truth_evidence(
            caption="", image_text=text, signal=current,
        )
        old = (record.get("priority"), record.get("category"), record.get("score"))
        new = (evidence.signal.priority, evidence.signal.category, evidence.signal.score)
        before[str(record.get("priority"))] += 1
        after[evidence.signal.priority] += 1
        kinds[evidence.event_kind] += 1
        if old != new:
            changes.append({
                "status_id": str(record.get("status_id")),
                "old": old,
                "new": new,
                "event_kind": evidence.event_kind,
                "reason": evidence.reason,
            })
    return {
        "ocr_only": True,
        "images": sum(before.values()),
        "before": dict(before),
        "after": dict(after),
        "evidence_kinds": dict(kinds),
        "changes": changes,
        "warning": (
            "OCR-only replay: the original benchmark has no account captions. "
            "Neither OCR text nor this rule engine proves event freshness or "
            "independent corroboration."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="absolute path of locally saved OCR report JSON")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        report = replay(data)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"Cannot read benchmark report: {type(error).__name__}")
        return  # Explicitly terminate this branch for static dataflow analysis.
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
