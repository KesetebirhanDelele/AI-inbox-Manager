"""
Re-label existing interview events with the interview sub-classifier.

Before 2026-10-01 the live pipeline never called the sub-classifier, so every
InterviewEvent carried its primary category as the sub-type. This script runs the
real sub-classifier over those events and updates `sub_type`.

Safe to rerun: events already tagged `sub_type_source = subclassifier` are skipped.
Reversible: the old value is kept in `raw_extraction.previous_sub_type`.
Dry-run by default; nothing is written without --apply. Never sends email.

Usage (on the server, inside the cron container):
    python execution/backfill_sub_types.py            # report only
    python execution/backfill_sub_types.py --apply    # write the new sub-types
"""

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger("backfill_sub_types")


def needs_backfill(event_raw: Optional[Dict[str, Any]], category: Optional[str]) -> bool:
    """True for interview-related events that never got the real sub-classifier."""
    from subclassify_interview import is_interview_related
    if (event_raw or {}).get("sub_type_source") == "subclassifier":
        return False
    return is_interview_related(category or "")


def relabel(raw: Optional[Dict[str, Any]], old_sub_type: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """New raw_extraction for an event: sub-classifier output plus an audit trail."""
    merged = dict(raw or {})
    merged.update({k: v for k, v in result.items() if v is not None})
    merged["previous_sub_type"] = old_sub_type
    merged["sub_type_source"] = "subclassifier"
    return merged


def run(apply: bool) -> Dict[str, Counter]:
    from sqlalchemy.orm.attributes import flag_modified
    from process_inbox_auto import get_db_session
    from models import Classification, Email, InterviewEvent
    from subclassify_interview import subclassify_interview, INTERVIEW_SUB_TYPES

    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")

    before, after, skipped = Counter(), Counter(), Counter()
    events = db.query(InterviewEvent).order_by(InterviewEvent.id).all()
    for event in events:
        before[event.sub_type] += 1
        email = db.query(Email).filter(Email.id == event.email_id).first()
        cls = (
            db.query(Classification)
            .filter(Classification.email_id == event.email_id)
            .order_by(Classification.classification_timestamp.desc())
            .first()
        )
        category = cls.category if cls else None
        if not email or not needs_backfill(event.raw_extraction, category):
            skipped["not_applicable"] += 1
            after[event.sub_type] += 1
            continue
        try:
            result = subclassify_interview({
                "subject": email.subject or "",
                "body_content": email.full_body or "",
                "sender_email": email.from_address or "",
                "email_date": str(email.received_date or ""),
            })
        except Exception as exc:
            logger.warning(f"event {event.id}: sub-classifier failed ({exc}); left unchanged")
            skipped["classifier_failed"] += 1
            after[event.sub_type] += 1
            continue
        new_type = result.get("interview_sub_type")
        if new_type not in INTERVIEW_SUB_TYPES:
            skipped["unusable_result"] += 1
            after[event.sub_type] += 1
            continue
        after[new_type] += 1
        logger.info(f"event {event.id}: {event.sub_type} -> {new_type} (conf {result.get('confidence')})")
        if apply:
            event.raw_extraction = relabel(event.raw_extraction, event.sub_type, result)
            flag_modified(event, "raw_extraction")
            event.sub_type = new_type
            event.is_job_machine = bool(result.get("is_job_machine", event.is_job_machine))
            event.is_next_round = bool(result.get("is_next_round", event.is_next_round))
            event.confidence = result.get("confidence", event.confidence)
    if apply:
        db.commit()
    return {"before": before, "after": after, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--apply", action="store_true", help="write changes (default: report only)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out = run(apply=args.apply)
    mode = "APPLIED" if args.apply else "DRY RUN (nothing written)"
    print(f"\n{mode}")
    for name in ("before", "after", "skipped"):
        print(f"{name:8}", dict(out[name]))


if __name__ == "__main__":
    main()
