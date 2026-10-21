"""Seed the combined site: club, roles, day-board fields, and an admin account.

Also provides import_website_users() to fold the old club-website sqlite
database (its `users` table) into the unified Member table, preserving each
user's existing password hash so their current password keeps working.
"""
import os
import sqlite3

from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Club, Role, Member, FieldDef

CLUB_NAME = "High Desert Soaring Club"
CLUB_SLUG = "hdsc"

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


def _get_or_create_club():
    club = Club.query.filter_by(slug=CLUB_SLUG).first()
    if club:
        return club
    club = Club(name=CLUB_NAME, slug=CLUB_SLUG)
    db.session.add(club)
    db.session.flush()
    return club


def _ensure_roles(club):
    existing = {r.name: r for r in Role.query.filter_by(club_id=club.id).all()}
    for name in ROLE_NAMES:
        if name not in existing:
            r = Role(club_id=club.id, name=name)
            db.session.add(r)
            existing[name] = r
    db.session.flush()
    return existing


def _ensure_fields(club):
    have = {f.key for f in FieldDef.query.filter_by(club_id=club.id).all()}
    for key, label, kind, group, days, aroles, col, pos, maxs, offer in FIELD_DEFS:
        if key in have:
            continue
        db.session.add(FieldDef(
            club_id=club.id, key=key, label=label, kind=kind, group_key=group,
            day_types=days, allowed_roles=aroles, column=col, position=pos,
            max_slots=maxs, default_offer=offer,
        ))
    db.session.flush()


def seed_site():
    """Create the club, roles, day-board fields, and a single admin member."""
    club = _get_or_create_club()
    _ensure_roles(club)
    _ensure_fields(club)

    admin_email = os.environ.get("ADMIN_EMAIL", "gbaker@cadenceneuro.com")
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "soaradmin")

    admin = Member.query.filter_by(email=admin_email).first()
    if admin is None:
        admin = Member(
            club_id=club.id,
            email=admin_email,
            username=admin_username,
            first_name=os.environ.get("ADMIN_FIRST", "Club"),
            last_name=os.environ.get("ADMIN_LAST", "Admin"),
            is_admin=True,
            activated=True,
        )
        admin.set_password(admin_password)
        db.session.add(admin)
        print(f"  Created admin: {admin_email}  (password: {admin_password})")
        print("  -> Log in and change this password from Settings.")
    db.session.commit()
    print(f"  Club ready: {club.name}")


def import_website_users(sqlite_path, email_domain="highdesertsoaring.org"):
    """Fold the old club-website `users` table into the Member table.

    Preserves password_hash and is_admin. The user named 'admin' is mapped to
    ADMIN_EMAIL (default gbaker@cadenceneuro.com); others become
    <username>@<email_domain>. Safe to re-run (updates existing rows).
    """
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(sqlite_path)

    club = _get_or_create_club()
    _ensure_roles(club)
    _ensure_fields(club)

    admin_email = os.environ.get("ADMIN_EMAIL", "gbaker@cadenceneuro.com")

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        "SELECT username, password_hash, is_admin FROM users"
    ).fetchall()
    src.close()

    count = 0
    for row in rows:
        username = row["username"]
        is_admin = bool(row["is_admin"])
        email = admin_email if username == "admin" else f"{username}@{email_domain}"

        member = (
            Member.query.filter_by(username=username).first()
            or Member.query.filter_by(email=email).first()
        )
        if member is None:
            member = Member(
                club_id=club.id,
                email=email,
                username=username,
                first_name=username.capitalize(),
                last_name="",
                activated=True,
            )
            db.session.add(member)
        # Carry over the existing credentials/flags.
        member.password_hash = row["password_hash"]
        member.is_admin = is_admin
        member.activated = True
        count += 1

    db.session.commit()
    return count
