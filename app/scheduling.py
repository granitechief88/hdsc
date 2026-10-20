"""Core board logic: capacity, waiting-list promotion, and the email stub.

The central rule (mirroring Click n' Glide): instructors ("providers") each
open a number of student slots. Students ("consumers") fill those slots; once
full, further sign-ups land on the group's waiting list and are promoted
automatically (oldest first) as capacity grows or active students leave.
"""
from datetime import date, timedelta

from .extensions import db
from .models import FieldDef, Signup, Member, EmailOutbox


def day_type_for(d: date) -> str:
    return "weekend" if d.weekday() >= 5 else "weekday"


def fields_for_day(club_id, d):
    dt = day_type_for(d)
    fields = (
        FieldDef.query.filter_by(club_id=club_id)
        .order_by(FieldDef.column, FieldDef.position)
        .all()
    )
    return [f for f in fields if f.shows_on(dt)]


def group_capacity(club_id, d, group_key):
    """Total student slots opened by all providers in a group on a day."""
    providers = (
        Signup.query.join(FieldDef, FieldDef.key == Signup.field_key)
        .filter(
            Signup.club_id == club_id,
            Signup.day == d,
            FieldDef.group_key == group_key,
            FieldDef.kind == "PROVIDER",
        )
        .all()
    )
    return sum((s.offered or 0) for s in providers)


def _consumer_and_waiting_fields(club_id, group_key):
    fields = FieldDef.query.filter_by(club_id=club_id, group_key=group_key).all()
    consumer = next((f for f in fields if f.kind == "CONSUMER"), None)
    waiting = next((f for f in fields if f.kind == "WAITING"), None)
    return consumer, waiting


def rebalance_group(club_id, d, group_key):
    """Promote/demote consumers between the active list and waiting list so the
    active count matches the current group capacity. Oldest sign-ups win slots."""
    consumer, waiting = _consumer_and_waiting_fields(club_id, group_key)
    if not consumer or not waiting:
        return
    capacity = group_capacity(club_id, d, group_key)

    active = (
        Signup.query.filter_by(
            club_id=club_id, day=d, field_key=consumer.key, status="active"
        )
        .order_by(Signup.created_at)
        .all()
    )
    waiters = (
        Signup.query.filter_by(
            club_id=club_id, day=d, field_key=consumer.key, status="waiting"
        )
        .order_by(Signup.created_at)
        .all()
    )

    # Promote while there's room.
    while len(active) < capacity and waiters:
        promoted = waiters.pop(0)
        promoted.status = "active"
        promoted.field_key = consumer.key
        active.append(promoted)

    # Demote newest actives if capacity shrank (e.g. an instructor left).
    while len(active) > capacity:
        demoted = active.pop()  # newest (list is oldest-first)
        demoted.status = "waiting"

    db.session.flush()


# --------------------------------------------------------------------------
# Email stub + automatic notifications
# --------------------------------------------------------------------------
def queue_email(club_id, to_email, subject, body, kind):
    db.session.add(
        EmailOutbox(
            club_id=club_id, to_email=to_email, subject=subject, body=body, kind=kind
        )
    )


def check_staffing_alerts(club_id, d):
    """If students are waiting for an instructor on a day, email instructors to
    ask for volunteers (mirrors Click n' Glide's automatic alert emails)."""
    waiting_groups = []
    for f in fields_for_day(club_id, d):
        if f.kind != "WAITING":
            continue
        consumer, _ = _consumer_and_waiting_fields(club_id, f.group_key)
        key = consumer.key if consumer else f.key
        waiting_count = Signup.query.filter_by(
            club_id=club_id, day=d, field_key=key, status="waiting"
        ).count()
        if waiting_count:
            waiting_groups.append((f.label, waiting_count))

    if not waiting_groups:
        return 0

    instructors = (
        Member.query.filter_by(club_id=club_id, activated=True)
        .filter(Member.roles.any(name="Instructor"))
        .all()
    )
    lines = "\n".join(f"  - {label}: {n} waiting" for label, n in waiting_groups)
    body = (
        f"There are members waiting for an instructor on {d:%A %d %B %Y}:\n"
        f"{lines}\n\nPlease sign up if you can help."
    )
    for ins in instructors:
        queue_email(
            club_id, ins.email, f"Instructor needed on {d:%d %b}", body, "staffing_alert"
        )
    return len(instructors)


def generate_reminders(club_id, lead_days=2):
    """Queue reminder emails for members signed up `lead_days` from today.
    Idempotent per (member, day): skips if a reminder already exists."""
    target = date.today() + timedelta(days=lead_days)
    signups = Signup.query.filter_by(club_id=club_id, day=target).all()
    queued = 0
    seen = set()
    for s in signups:
        m = s.member
        if not (m and m.wants_reminders and m.activated) or m.id in seen:
            continue
        seen.add(m.id)
        subject = f"Reminder: you're signed up for {target:%a %d %b}"
        already = EmailOutbox.query.filter_by(
            club_id=club_id, to_email=m.email, subject=subject, kind="reminder"
        ).first()
        if already:
            continue
        queue_email(
            club_id,
            m.email,
            subject,
            f"Hi {m.first_name}, this is a reminder that you are signed up for "
            f"activities on {target:%A %d %B %Y}. See you at the airfield!",
            "reminder",
        )
        queued += 1
    db.session.commit()
    return queued
