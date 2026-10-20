"""Seed a demo club so the app is usable immediately after setup."""
from datetime import date, datetime, timedelta

from .extensions import db
from .models import (
    Club, Role, Member, FieldDef, Signup, Event, EventSignup, ForumPost, Message,
)

DEMO_PASSWORD = "glide1234"

ROLE_NAMES = [
    "Tug Driver", "Winch Driver", "Licensed pilot", "Dual student",
    "Instructor", "Solo pilot", "Introductory pilot",
]

# key, label, kind, group, day_types, allowed_roles, column, position, max_slots, default_offer
FIELD_DEFS = [
    # --- Column 1: instructors / providers + solo & own ---
    ("booked_instructors", "Booked-Flying Instructors", "PROVIDER", "booked",
     "weekday", "Instructor", 1, 0, 3, 1),
    ("fullday_instructors", "Full Day Group Instructors", "PROVIDER", "fullday",
     "weekend", "Instructor", 1, 1, 2, 4),
    ("flying_instructors", "Flying List Instructors", "PROVIDER", "flying",
     "weekday,weekend", "Instructor", 1, 2, 4, 2),
    ("fly_solo", "Fly club glider (solo)", "LIST", None,
     "weekday,weekend", "Solo pilot,Licensed pilot", 1, 3, None, 1),
    ("fly_own", "Fly own glider", "LIST", None,
     "weekday,weekend", "Licensed pilot,Solo pilot", 1, 4, None, 1),

    # --- Column 2: students / consumers + waiting lists ---
    ("booked_students", "Booked-Flying Students", "CONSUMER", "booked",
     "weekday", "Dual student", 2, 0, None, 1),
    ("booked_waiting", "Booked-Flying Waiting List", "WAITING", "booked",
     "weekday", "Dual student", 2, 1, None, 1),
    ("fullday_students", "Full Day Group", "CONSUMER", "fullday",
     "weekend", "Dual student", 2, 2, None, 1),
    ("fullday_waiting", "Full Day Group Waiting List", "WAITING", "fullday",
     "weekend", "Dual student", 2, 3, None, 1),
    ("flying_list", "Flying List (check flights etc)", "CONSUMER", "flying",
     "weekday,weekend", "Dual student,Licensed pilot", 2, 4, None, 1),
    ("flying_waiting", "Waiting List for Flying List", "WAITING", "flying",
     "weekday,weekend", "Dual student,Licensed pilot", 2, 5, None, 1),

    # --- Column 3: ground roles & catch-all ---
    ("winch", "Winch Driver", "LIST", None,
     "weekday,weekend", "Winch Driver", 3, 0, None, 1),
    ("tug", "Tug Driver", "LIST", None,
     "weekday,weekend", "Tug Driver", 3, 1, None, 1),
    ("air_exp", "Air Experience team", "LIST", None,
     "weekday,weekend", "Introductory pilot", 3, 2, None, 1),
    ("other", "On airfield for other reason", "LIST", None,
     "weekday,weekend", "", 3, 3, None, 1),
]

# first, last, number, is_admin, [roles]
MEMBERS = [
    ("Alex", "Admin", "A0001", True, ["Instructor", "Licensed pilot"]),
    ("Ivy", "Instructor", "I0010", False, ["Instructor", "Licensed pilot"]),
    ("Ian", "Instructor", "I0011", False, ["Instructor", "Licensed pilot"]),
    ("Sam", "Student", "S0020", False, ["Dual student"]),
    ("Sue", "Student", "S0021", False, ["Dual student"]),
    ("Sid", "Student", "S0022", False, ["Dual student"]),
    ("Sarah", "Student", "S0023", False, ["Dual student"]),
    ("Pete", "Pilot", "P0030", False, ["Licensed pilot", "Solo pilot"]),
    ("Tom", "Towpilot", "T0040", False, ["Tug Driver", "Licensed pilot"]),
    ("Wendy", "Winch", "W0050", False, ["Winch Driver"]),
    ("Iris", "Intro", "N0060", False, ["Introductory pilot", "Licensed pilot"]),
]


def _next_weekday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def seed_demo():
    club = Club(name="Soaring Demo Club", slug="demo")
    db.session.add(club)
    db.session.flush()

    roles = {name: Role(club_id=club.id, name=name) for name in ROLE_NAMES}
    db.session.add_all(roles.values())
    db.session.flush()

    for key, label, kind, group, days, aroles, col, pos, maxs, offer in FIELD_DEFS:
        db.session.add(FieldDef(
            club_id=club.id, key=key, label=label, kind=kind, group_key=group,
            day_types=days, allowed_roles=aroles, column=col, position=pos,
            max_slots=maxs, default_offer=offer,
        ))

    members = {}
    for first, last, num, is_admin, role_list in MEMBERS:
        email = f"{first.lower()}@soardemo.club"
        m = Member(
            club_id=club.id, email=email, first_name=first, last_name=last,
            membership_number=num, is_admin=is_admin, activated=True,
        )
        m.set_password(DEMO_PASSWORD)
        m.roles = [roles[r] for r in role_list]
        db.session.add(m)
        members[first] = m
    db.session.flush()

    # --- A sample weekday with a waiting list, to demonstrate the behaviour ---
    d = _next_weekday(date.today())
    base = datetime.utcnow()
    seq = [0]

    def add_signup(member, field_key, status="active", offered=0, comment=None):
        seq[0] += 1
        db.session.add(Signup(
            club_id=club.id, day=d, field_key=field_key, member_id=member.id,
            status=status, offered=offered, comment=comment,
            created_at=base + timedelta(seconds=seq[0]),
        ))

    # One instructor opens a single booked-flying slot...
    add_signup(members["Ivy"], "booked_instructors", offered=1,
               comment="Happy to take one student this morning")
    # ...three students want it: one gets the slot, two wait.
    add_signup(members["Sam"], "booked_students", status="active",
               comment="Working on circuits")
    add_signup(members["Sue"], "booked_students", status="waiting")
    add_signup(members["Sid"], "booked_students", status="waiting")
    # Ground crew & others.
    add_signup(members["Tom"], "tug", comment="Available all day")
    add_signup(members["Wendy"], "winch")
    add_signup(members["Pete"], "fly_own", comment="Cross-country attempt if soarable")

    # A forum post for the day.
    db.session.add(ForumPost(
        club_id=club.id, day=d, member_id=members["Alex"].id,
        body="Forecast looks good — light NW, cloudbase ~3500ft. Briefing at 9:30.",
        created_at=base,
    ))

    # An upcoming event.
    ev = Event(
        club_id=club.id, day=d + timedelta(days=7),
        title="Winter maintenance day",
        description="Help wanted cleaning and inspecting the club fleet. Lunch provided.",
        capacity=12, created_by_id=members["Alex"].id,
    )
    db.session.add(ev)
    db.session.flush()
    db.session.add(EventSignup(event_id=ev.id, member_id=members["Pete"].id))

    # A welcome message in everyone's mailbox from the admin.
    for m in members.values():
        db.session.add(Message(
            club_id=club.id, sender_id=members["Alex"].id, recipient_id=m.id,
            audience="All members", subject="Welcome to the new scheduler",
            body="Please sign up for the days you plan to fly. Add a comment so "
                 "instructors and tuggies know your plans. Blue skies!",
        ))

    db.session.commit()

    print(f"  Club: {club.name}")
    print(f"  Demo login password for all members: {DEMO_PASSWORD}")
    print(f"  Admin login:  alex@soardemo.club")
    print(f"  Sample day with waiting list: {d.isoformat()}")
