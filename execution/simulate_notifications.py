"""
Simulate the student-notification cadence with made-up students. Nothing real is touched.

Ten made-up students (fake phones on the reserved 555-01xx range, fake @example.test emails) are approved on a fake clock that then runs forward in
5-minute ticks, exactly like the host cron does, for six days. Every channel is a recording dry run, every "email" to the approver / escalation
contact is captured in memory, the database is an in-memory SQLite one and the AI reading of replies is a keyword stub. No network, no GHL, no SMTP.

Each student plays a scenario (silent, replies YES, taps the email link, says yes on the call, STOPs, asks a question, cannot attend, has no phone,
is approved at night, cannot be found in GHL). The script prints every student's timeline in their OWN local time, then checks the rules:
one call per local day, calls only 8 AM-8 PM and texts only 8 AM-9 PM local, nothing sent after a confirmation or STOP, the day-1 pattern, the
approver's alerts, and that nothing was ever recorded as really sent.

    python execution/simulate_notifications.py            # timelines + checks, exit 1 if a check fails
    python execution/simulate_notifications.py --brief    # checks only
"""
import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


TICK = timedelta(minutes=5)
DAYS = 6
FAKE_ZONE = {"212": "America/New_York", "312": "America/Chicago", "303": "America/Denver", "213": "America/Los_Angeles"}


@dataclass
class Scenario:
    key: str
    title: str
    area: str                          # area code of the fake phone (decides the time zone)
    start: datetime                    # approval time, naive UTC
    phone: bool = True
    contact: bool = True                # False: no phone, no email, no Gmail at all
    actions: List[Tuple[timedelta, str, str]] = field(default_factory=list)   # (after approval, kind, text)
    unreachable: bool = False


MON_15_CT = datetime(2026, 10, 12, 20, 0)      # Monday 3:00 PM Central
SCENARIOS = [
    Scenario("S01", "Silent student: never responds", "312", MON_15_CT),
    Scenario("S02", "Replies YES by text 40 minutes after the first notice", "212", MON_15_CT, actions=[(timedelta(minutes=40), "reply", "YES")]),
    Scenario("S03", "Taps the email 'I got this' link 3 hours in", "303", MON_15_CT, actions=[(timedelta(hours=3), "click", "")]),
    Scenario("S04", "Says 'yes' on the call 10 minutes in", "213", MON_15_CT, actions=[(timedelta(minutes=10), "reply", "yes")]),
    Scenario("S05", "Replies STOP to the first text", "312", MON_15_CT, actions=[(timedelta(minutes=5), "reply", "STOP")]),
    Scenario("S06", "Asks a question an hour in", "212", MON_15_CT, actions=[(timedelta(hours=1), "reply", "Who do I call about this?")]),
    Scenario("S07", "Says they cannot attend", "312", MON_15_CT, actions=[(timedelta(minutes=30), "reply", "I can't make it that day")]),
    Scenario("S08", "Nothing on file: no phone, no email, no Gmail", "312", MON_15_CT, phone=False, contact=False),
    Scenario("S09", "Approved at 10 PM local (quiet hours)", "213", datetime(2026, 10, 13, 5, 0)),     # 10:00 PM Pacific on Monday
    Scenario("S10", "Cannot be found in GHL", "312", MON_15_CT, unreachable=True),
]


class Mail:
    """Stands in for the email sender of the approver and escalation alerts."""

    def __init__(self):
        self.sent: List[Dict[str, Any]] = []
        self.now: Optional[datetime] = None

    def __call__(self, **kw):
        self.sent.append({"at": self.now, **kw})
        return {"status": "sent"}


def fake_ai(messages) -> str:
    """Keyword stand-in for the model that reads a reply."""
    text = messages[-1]["content"].lower()
    if "can't" in text or "cannot" in text:
        return json.dumps({"outcome": "needs_help", "confidence": 0.9, "reason": "says they cannot attend"})
    if "?" in text:
        return json.dumps({"outcome": "needs_help", "confidence": 0.9, "reason": "asks a question"})
    return json.dumps({"outcome": "understood", "confidence": 0.95, "reason": "ok"})


def run() -> Dict[str, Any]:
    """Run the whole simulation. Leaves the process settings (database URL, logging) exactly as it found them."""
    saved = {k: os.environ.get(k) for k in ("DATABASE_URL", "NOTIFY_CHANNEL_EMAIL")}
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"       # never the real database
    os.environ.pop("NOTIFY_CHANNEL_EMAIL", None)
    logging.disable(logging.CRITICAL)
    try:
        return _run()
    finally:
        logging.disable(logging.NOTSET)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _run() -> Dict[str, Any]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models as M
    import escalation_engine as engine
    import notify_channels as nc

    eng = create_engine("sqlite://")
    M.Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    mail = Mail()
    for role, addr in (("approver", "approver@example.test"), ("callback_owner", "callback@example.test"), ("escalation_target", "escalation@example.test")):
        db.add(M.RoleAssignment(role=role, email=addr, active=True))
    db.commit()
    alerts = engine.RoleAlerts(db=db, send_fn=mail)

    class SimChannel:
        """The real wording and the real dry-run rules, plus 'not found in GHL' for one student. Records every message."""

        def __init__(self, name):
            self.name, self.inner, self.log = name, nc.DryRunChannel(name), []

        def send(self, ctx):
            student = ctx.student
            if student is not None and student.username in UNREACHABLE and self.name in ("call", "sms"):
                return nc.ChannelResult(nc.FAILED, detail=nc.UNREACHABLE + "no GHL contact matches this phone or email")
            result = self.inner.send(ctx)
            text = (nc.sms_text(ctx) if self.name == "sms" else nc.call_script(ctx) if self.name == "call" else nc.email_parts(ctx)[0])
            self.log.append((ctx.attempt.id, text))
            return result

    UNREACHABLE = {s.key.lower() for s in SCENARIOS if s.unreachable}
    channels = {name: SimChannel(name) for name in ("call", "sms", "email")}

    people: Dict[str, Dict[str, Any]] = {}
    for i, sc in enumerate(SCENARIOS, 1):
        phone = f"+1{sc.area}555{100 + i:04d}" if sc.phone else None
        student = M.Student(username=sc.key.lower(), full_name=f"Simulated Student {i:02d}", phone_number=phone,
                            personal_email=(f"sim{i:02d}@example.test" if sc.contact else None), is_active=True)
        db.add(student)
        db.flush()
        email = M.Email(email_id=str(i), message_id=f"<sim{i}@example.test>", subject="Interview", from_address="hr@example.test",
                        received_date=sc.start)
        db.add(email)
        db.flush()
        event = M.InterviewEvent(email_id=email.id, student_id=student.id, sub_type="Phone Screen", company_name="Simulated Co",
                                 position_title="Data Analyst", interview_date="2026-10-20", interview_time="11:00",
                                 interview_timezone="CT", interview_format="phone", confidence=0.95)
        db.add(event)
        db.flush()
        draft = M.NotificationDraft(interview_event_id=event.id, template_id="phone_screening_scheduled", email_subject="PHONE SCREENING: Interview Scheduled - Simulated Co",
                                    email_body="Congratulations! Your interview is scheduled.", recipient_email=(f"sim{i:02d}@example.test" if sc.contact else ""), email_status="approved")
        db.add(draft)
        db.commit()
        people[sc.key] = {"scenario": sc, "student": student, "draft": draft, "seq": None}

    t0 = min(s.start for s in SCENARIOS)
    now = t0
    end = max(s.start for s in SCENARIOS) + timedelta(days=DAYS)
    pending: List[Tuple[datetime, str, str, str]] = []
    while now <= end:
        mail.now = now
        for key, p in people.items():
            sc = p["scenario"]
            if p["seq"] is None and now >= sc.start:
                p["seq"] = engine.start_sequence(db, p["draft"], p["student"], sc.start, started_by="simulation")
                for after, kind, text in sc.actions:
                    pending.append((sc.start + after, key, kind, text))
        for item in [x for x in pending if x[0] <= now]:
            pending.remove(item)
            _, key, kind, text = item
            seq = people[key]["seq"]
            db.refresh(seq)
            if seq.status != "active":
                continue
            if kind == "reply":
                engine.handle_reply_for_sequences(db, [seq], text, "sms", now, alerts, completion_fn=fake_ai)
            elif kind == "click":
                engine.acknowledge_by_token(db, seq.ack_token, now)
        engine.tick(db, now, channels, alerts, "https://example.test/ack")
        now += TICK

    return {"db": db, "M": M, "people": people, "mail": mail, "channels": channels, "t0": t0}


def local(dt: datetime, tz: str) -> datetime:
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz))


def attempts_of(sim, key) -> List[Any]:
    seq = sim["people"][key]["seq"]
    return sorted(seq.attempts, key=lambda a: (a.sent_at or a.scheduled_for, a.id))


def delivered(sim, key) -> List[Any]:
    return [a for a in attempts_of(sim, key) if a.sent_at is not None]


def checks(sim) -> List[Tuple[str, bool, str]]:
    out: List[Tuple[str, bool, str]] = []
    people, mail = sim["people"], sim["mail"]

    def add(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    all_delivered = [(k, a) for k in people for a in delivered(sim, k)]
    add("Nothing was ever recorded as really sent (all dry runs)", all(a.status == "dry_run" for _, a in all_delivered),
        f"{len(all_delivered)} simulated messages")

    bad_calls, bad_texts, double_calls = [], [], []
    for k in people:
        tz = people[k]["seq"].timezone
        per_day: Dict[Any, int] = {}
        for a in delivered(sim, k):
            lt = local(a.sent_at, tz)
            if a.channel == "call":
                per_day[lt.date()] = per_day.get(lt.date(), 0) + 1
                if not (8 <= lt.hour < 20):
                    bad_calls.append((k, lt))
            if a.channel == "sms" and not (8 <= lt.hour < 21):
                bad_texts.append((k, lt))
        double_calls += [(k, d) for d, n in per_day.items() if n > 1]
    add("Never more than one call per student per local day", not double_calls, str(double_calls))
    add("Calls only between 8 AM and 8 PM student-local", not bad_calls, str(bad_calls))
    add("Texts only between 8 AM and 9 PM student-local", not bad_texts, str(bad_texts))

    s1 = delivered(sim, "S01")
    counts = {c: sum(1 for a in s1 if a.channel == c) for c in ("call", "sms", "email")}
    add("Silent student gets 4 calls, 5 texts and 6 emails over four days", counts == {"call": 4, "sms": 5, "email": 6}, str(counts))
    day1 = [a for a in s1 if a.sent_at < people["S01"]["scenario"].start + timedelta(hours=5)]
    add("Day 1 is call+text+email, then email at +2h, then text+email at +4h (6 messages)", len(day1) == 6, str([(a.channel, a.step) for a in day1]))
    seq1 = people["S01"]["seq"]
    add("Silent student's sequence ends as 'exhausted'", seq1.status == "exhausted", seq1.status)

    def stopped_after(key, status_expected, when_attr="ack_at"):
        seq = people[key]["seq"]
        stop_time = getattr(seq, when_attr, None) or seq.closed_at
        late = [a for a in delivered(sim, key) if stop_time and a.sent_at > stop_time]
        return seq.status == status_expected and not late, f"status={seq.status}, sent after stop={len(late)}"

    for key, expected in (("S02", "acknowledged"), ("S03", "acknowledged"), ("S04", "acknowledged")):
        ok, detail = stopped_after(key, expected)
        add(f"{key}: confirmation stops the sequence and nothing is sent after it", ok, detail)
    s3 = delivered(sim, "S03")
    add("S03: tapping the link at +3h means the +4h round is never sent", not any(a.step == "d1_4h" for a in s3), str([a.step for a in s3]))
    ok, detail = stopped_after("S05", "opted_out", "closed_at")
    add("S05: STOP ends all contact and records the opt-out", ok and sim["db"].query(sim["M"].NotificationOptOut).count() >= 1, detail)

    s6 = people["S06"]["seq"]
    add("S06: a question does not stop the follow-ups", s6.status in ("exhausted", "active") and len(delivered(sim, "S06")) == 15, f"{s6.status}, {len(delivered(sim, 'S06'))} messages")
    add("S07: 'I can't make it' does not stop the follow-ups either (the AI only records until its shadow period ends)", people["S07"]["seq"].status == "exhausted", people["S07"]["seq"].status)
    subjects = [m["subject"] for m in mail.sent]
    add("S06 and S07: the approver is told about each reply that needs help", sum("replied and may need help" in s for s in subjects) == 2,
        str([s for s in subjects if "replied" in s]))

    s8 = attempts_of(sim, "S08")
    s8_alerts = [m for m in mail.sent if "Cannot reach Simulated Student 08" in m["subject"]]
    add("S08: nothing on file: every attempt is recorded as skipped, nothing is sent and the approver is told at once, once",
        all(a.status == "skipped" for a in s8) and not any(a.sent_at for a in s8) and len(s8_alerts) == 1
        and s8_alerts[0]["at"] <= people["S08"]["scenario"].start + timedelta(minutes=10),
        f"{len(s8_alerts)} alert(s); statuses {sorted({a.status for a in s8})}")

    s9 = delivered(sim, "S09")
    first_phone = min((local(a.sent_at, "America/Los_Angeles") for a in s9 if a.channel in ("call", "sms")), default=None)
    first_email = min((local(a.sent_at, "America/Los_Angeles") for a in s9 if a.channel == "email"), default=None)
    add("S09: approved at 10 PM, the first call and text wait for the morning (8 to 9 AM, never at night); the email goes at once",
        first_phone is not None and 8 <= first_phone.hour <= 9 and first_email is not None and first_email.hour == 22,
        f"first phone attempt {first_phone}, first email {first_email}")

    s10 = attempts_of(sim, "S10")
    unreachable_alerts = [s for s in subjects if "Cannot reach" in s and "Simulated Student 10" in s]
    add("S10: not found in GHL: the approver is told once, the email still goes", len(unreachable_alerts) == 1 and any(a.channel == "email" and a.sent_at for a in s10),
        f"{len(unreachable_alerts)} alert(s)")

    unanswered = {f"Simulated Student {k[1:]}" for k in people if people[k]["seq"].status == "exhausted"}
    no_resp = [m["subject"].split("] ")[-1].split(" has not")[0] for m in mail.sent if "has not responded" in m["subject"]]
    add("'No response' reaches the approver once for each student who had not confirmed 6 hours in (and for nobody else)",
        len(no_resp) == len(set(no_resp)) and set(no_resp) <= unanswered and "Simulated Student 01" in no_resp and
        not any(n in no_resp for n in ("Simulated Student 02", "Simulated Student 03", "Simulated Student 04", "Simulated Student 05")),
        f"{sorted(set(no_resp))}")
    ended = [m["subject"].split("Follow-ups ended: ")[-1].split(" never")[0] for m in mail.sent if "Follow-ups ended" in m["subject"]]
    add("'Follow-ups ended' goes out once for each student whose sequence ran out unanswered",
        len(ended) == len(set(ended)) and set(ended) == unanswered, f"ended {sorted(set(ended))} vs unanswered {sorted(unanswered)}")
    to = {m["recipient_email"] for m in mail.sent}
    add("Every alert went to the approver address, none to anyone else", to <= {"approver@example.test"}, str(to))
    return out


def report(sim, brief: bool = False) -> int:
    people = sim["people"]
    if not brief:
        for key, p in people.items():
            sc, seq = p["scenario"], p["seq"]
            tz = seq.timezone
            print(f"\n{key}  {sc.title}   [{tz}, phone {p['student'].phone_number or 'none'}]")
            print(f"    approved {local(sc.start, tz).strftime('%a %I:%M %p')} local; final status: {seq.status}")
            for a in attempts_of(sim, key):
                when = local(a.sent_at or a.scheduled_for, tz).strftime("%a %I:%M %p")
                state = a.status if a.status != "dry_run" else "simulated"
                note = f"  ({a.detail})" if a.detail and a.status not in ("dry_run", "cancelled") else ""
                print(f"    {when:>13}  {a.channel:<5} {a.step:<7} {state}{note}")
            cancelled = sum(1 for a in seq.attempts if a.status == "cancelled")
            if cancelled:
                print(f"    ({cancelled} planned attempt(s) cancelled when the sequence stopped)")
        print("\nWording of the first notice (S01):")
        for name in ("call", "sms", "email"):
            entry = next((t for _, t in sim["channels"][name].log), "")
            print(f"    {name:<5} {entry}")
        print("\nAlerts emailed to the approver during the simulation:")
        for m in sim["mail"].sent:
            print(f"    {m['at'].strftime('%a %b %d %H:%M')} UTC  {m['subject']}")
    print("\nChecks:")
    failed = 0
    for name, ok, detail in checks(sim):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok or not detail else f"\n         {detail}"))
        failed += 0 if ok else 1
    print(f"\n{len(people)} simulated students, {sum(len(delivered(sim, k)) for k in people)} simulated messages, "
          f"{len(sim['mail'].sent)} alerts captured, {failed} check(s) failed. Nothing real was contacted.")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--brief", action="store_true")
    args = ap.parse_args(argv)
    return report(run(), brief=args.brief)


if __name__ == "__main__":
    sys.exit(main())
