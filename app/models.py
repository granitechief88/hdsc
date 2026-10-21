"""Database models for the Soar Scheduler (a Click n' Glide-style day board)."""
from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


# --- Many-to-many: members <-> roles -------------------------------------
member_roles = db.Table(
    "member_roles",
    db.Column("member_id", db.Integer, db.ForeignKey("member.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("role.id"), primary_key=True),
)


class Club(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(60), unique=True, nullable=False)

    members = db.relationship("Member", backref="club", lazy=True)
    roles = db.relationship("Role", backref="club", lazy=True)
    fields = db.relationship("FieldDef", backref="club", lazy=True)


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    name = db.Column(db.String(60), nullable=False)


class Member(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    # Optional legacy handle carried over from the old club website (login is
    # by email; username is kept for reference / display).
    username = db.Column(db.String(80), unique=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    membership_number = db.Column(db.String(40))
    password_hash = db.Column(db.String(256))
    is_admin = db.Column(db.Boolean, default=False)
    activated = db.Column(db.Boolean, default=False)
    activation_token = db.Column(db.String(64))
    wants_reminders = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    roles = db.relationship(
        "Role", secondary=member_roles, backref=db.backref("members", lazy=True)
    )

    # --- auth helpers ---
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return bool(self.password_hash) and check_password_hash(self.password_hash, raw)

    # --- display helpers ---
    @property
    def display_name(self):
        tag = f" {self.membership_number}" if self.membership_number else ""
        return f"{self.first_name} {self.last_name}{tag}"

    @property
    def role_names(self):
        return {r.name for r in self.roles}

    def has_role(self, name):
        return self.is_admin or name in self.role_names


class FieldDef(db.Model):
    """A sign-up column on the day board, configurable per club.

    kind:
        LIST     - simple unlimited (or capped) list, e.g. Winch Driver
        PROVIDER - instructors who open student slots (choose `offered` count)
        CONSUMER - students who fill slots opened by the group's providers
        WAITING  - overflow queue for a CONSUMER field in the same group
    """
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    key = db.Column(db.String(60), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="LIST")
    group_key = db.Column(db.String(60))  # links PROVIDER/CONSUMER/WAITING together
    day_types = db.Column(db.String(40), default="weekday,weekend")  # csv
    allowed_roles = db.Column(db.String(200), default="")  # csv; empty = everyone
    column = db.Column(db.Integer, default=1)
    position = db.Column(db.Integer, default=0)
    max_slots = db.Column(db.Integer)  # provider/list cap; None = unlimited
    default_offer = db.Column(db.Integer, default=1)  # provider default student count

    def shows_on(self, day_type):
        return day_type in (self.day_types or "").split(",")

    def allowed_role_list(self):
        return [r for r in (self.allowed_roles or "").split(",") if r]

    def member_allowed(self, member):
        roles = self.allowed_role_list()
        if not roles:
            return True
        return member.is_admin or bool(set(roles) & member.role_names)


class Signup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    field_key = db.Column(db.String(60), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    comment = db.Column(db.String(500))
    offered = db.Column(db.Integer, default=0)  # providers: student slots opened
    status = db.Column(db.String(10), default="active")  # active | waiting
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    member = db.relationship("Member")


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(1000))
    capacity = db.Column(db.Integer)  # None = unlimited
    created_by_id = db.Column(db.Integer, db.ForeignKey("member.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship("Member")
    signups = db.relationship(
        "EventSignup", backref="event", lazy=True, cascade="all, delete-orphan"
    )


class EventSignup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    member = db.relationship("Member")


class ForumPost(db.Model):
    """Per-day discussion thread for a flying day."""
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    body = db.Column(db.String(2000))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    member = db.relationship("Member")
    attachments = db.relationship(
        "ForumAttachment", backref="post", lazy=True,
        cascade="all, delete-orphan",
    )


class ForumAttachment(db.Model):
    """An image attached to a day's forum post (e.g. MM5 / RASP forecast)."""
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("forum_post.id"), nullable=False)
    filename = db.Column(db.String(128), nullable=False)  # stored name on disk
    original_name = db.Column(db.String(256))
    content_type = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    """Internal mailbox message (one row per recipient)."""
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    audience = db.Column(db.String(80))  # label of the group it was sent to
    subject = db.Column(db.String(200))
    body = db.Column(db.String(4000))
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("Member", foreign_keys=[sender_id])
    recipient = db.relationship("Member", foreign_keys=[recipient_id])


class EmailOutbox(db.Model):
    """Stub mail transport: automatic reminders/alerts are recorded here
    instead of being sent, so the behaviour is visible without an SMTP server."""
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    to_email = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(200))
    body = db.Column(db.String(4000))
    kind = db.Column(db.String(40))  # reminder | staffing_alert | message
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
