"""The day board: the per-day sign-up grid that is the heart of the app."""
import calendar as _cal
import os
import secrets
from datetime import date, datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    current_app, send_from_directory,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from .extensions import db
from .models import FieldDef, Signup, ForumPost, ForumAttachment, Event

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
from .scheduling import (
    fields_for_day, group_capacity, rebalance_group, check_staffing_alerts,
    day_type_for,
)

bp = Blueprint("board", __name__)


def _parse_day(raw):
    if not raw:
        return date.today()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def _field_by_key(key):
    return FieldDef.query.filter_by(club_id=current_user.club_id, key=key).first()


def _build_view(d):
    """Assemble everything the template needs to render a day."""
    club_id = current_user.club_id
    fields = fields_for_day(club_id, d)
    signups = Signup.query.filter_by(club_id=club_id, day=d).all()
    by_field = {}
    for s in signups:
        by_field.setdefault(s.field_key, []).append(s)
    for lst in by_field.values():
        lst.sort(key=lambda s: s.created_at or datetime.min)

    cards = []
    for f in fields:
        mine = by_field.get(f.key, [])
        card = {"field": f, "signups": mine, "capacity": None, "occupancy": ""}

        if f.kind == "PROVIDER":
            cap = f.max_slots or 0
            card["occupancy"] = f"({len(mine)}/{cap})" if cap else f"({len(mine)})"
            card["offer_options"] = list(range(1, (f.max_slots or 4) + 1))
        elif f.kind == "CONSUMER":
            capacity = group_capacity(club_id, d, f.group_key)
            active = [s for s in mine if s.status == "active"]
            card["signups"] = active  # waiting rows render on the WAITING card
            card["capacity"] = capacity
            card["occupancy"] = f"({len(active)}/{capacity})"
        elif f.kind == "WAITING":
            # Waiting rows live under the group's CONSUMER field key with
            # status 'waiting'; surface them here.
            consumer = next(
                (gf for gf in fields
                 if gf.group_key == f.group_key and gf.kind == "CONSUMER"), None
            )
            waiters = []
            if consumer:
                waiters = [
                    s for s in by_field.get(consumer.key, []) if s.status == "waiting"
                ]
            card["signups"] = waiters
            card["occupancy"] = f"({len(waiters)})" if waiters else ""
        else:  # LIST
            if f.max_slots:
                card["occupancy"] = f"({len(mine)}/{f.max_slots})"
            elif mine:
                card["occupancy"] = f"({len(mine)})"

        # Can the current user sign up here?
        signed_keys = {s.field_key for s in signups if s.member_id == current_user.id}
        group_keys = set()
        if f.group_key:
            group_keys = {
                gf.key for gf in fields if gf.group_key == f.group_key
            }
        already = f.key in signed_keys or bool(group_keys & signed_keys)
        card["already_signed"] = already
        card["can_sign"] = (
            f.kind != "WAITING"
            and f.member_allowed(current_user)
            and not already
        )
        if f.kind == "LIST" and f.max_slots and len(mine) >= f.max_slots:
            card["can_sign"] = False
            card["full"] = True
        cards.append(card)

    columns = {1: [], 2: [], 3: []}
    for c in cards:
        columns.setdefault(c["field"].column, columns[1]).append(c)

    forum = (
        ForumPost.query.filter_by(club_id=club_id, day=d)
        .order_by(ForumPost.created_at)
        .all()
    )
    upcoming = (
        Event.query.filter(Event.club_id == club_id, Event.day >= date.today())
        .order_by(Event.day)
        .limit(8)
        .all()
    )
    # Mini-calendar weeks for the selected month (Mon-first).
    _cal.setfirstweekday(_cal.MONDAY)
    weeks = _cal.monthcalendar(d.year, d.month)

    return {
        "day": d,
        "day_type": day_type_for(d),
        "columns": columns,
        "forum": forum,
        "upcoming": upcoming,
        "today": date.today(),
        "prev_day": d - timedelta(days=1),
        "next_day": d + timedelta(days=1),
        "cal_weeks": weeks,
        "cal_month_name": d.strftime("%B %Y"),
    }


@bp.route("/board")
@login_required
def day():
    d = _parse_day(request.args.get("date"))
    ctx = _build_view(d)
    return render_template("board.html", **ctx)


@bp.route("/board/signup", methods=["POST"])
@login_required
def signup():
    d = _parse_day(request.form.get("date"))
    key = request.form.get("field_key", "")
    field = _field_by_key(key)
    if not field or not field.shows_on(day_type_for(d)):
        abort(400)
    if not field.member_allowed(current_user):
        flash("Your roles don't allow signing up for that.", "error")
        return redirect(url_for("board.day", date=d.isoformat()))

    # No duplicates within the same field or linked group.
    group_fields = []
    if field.group_key:
        group_fields = FieldDef.query.filter_by(
            club_id=current_user.club_id, group_key=field.group_key
        ).all()
    check_keys = {key} | {gf.key for gf in group_fields}
    exists = Signup.query.filter(
        Signup.club_id == current_user.club_id,
        Signup.day == d,
        Signup.member_id == current_user.id,
        Signup.field_key.in_(check_keys),
    ).first()
    if exists:
        flash("You're already signed up there.", "info")
        return redirect(url_for("board.day", date=d.isoformat()))

    s = Signup(
        club_id=current_user.club_id,
        day=d,
        field_key=key,
        member_id=current_user.id,
        comment=request.form.get("comment", "").strip() or None,
    )

    if field.kind == "PROVIDER":
        try:
            offered = int(request.form.get("offered", field.default_offer))
        except ValueError:
            offered = field.default_offer
        if field.max_slots:
            # cap on number of providers, not offered; offered just >= 1
            current = Signup.query.filter_by(
                club_id=current_user.club_id, day=d, field_key=key
            ).count()
            if current >= field.max_slots:
                flash("That instructor list is full.", "error")
                return redirect(url_for("board.day", date=d.isoformat()))
        s.offered = max(1, offered)
        s.status = "active"
    elif field.kind == "CONSUMER":
        capacity = group_capacity(current_user.club_id, d, field.group_key)
        active = Signup.query.filter_by(
            club_id=current_user.club_id, day=d, field_key=key, status="active"
        ).count()
        s.status = "active" if active < capacity else "waiting"
    elif field.kind == "LIST":
        if field.max_slots:
            count = Signup.query.filter_by(
                club_id=current_user.club_id, day=d, field_key=key
            ).count()
            if count >= field.max_slots:
                flash("That list is full.", "error")
                return redirect(url_for("board.day", date=d.isoformat()))
        s.status = "active"

    db.session.add(s)
    db.session.flush()
    if field.group_key:
        rebalance_group(current_user.club_id, d, field.group_key)
    check_staffing_alerts(current_user.club_id, d)
    db.session.commit()
    if s.status == "waiting":
        flash("No slots free yet — you're on the waiting list.", "info")
    return redirect(url_for("board.day", date=d.isoformat()))


@bp.route("/board/remove", methods=["POST"])
@login_required
def remove():
    d = _parse_day(request.form.get("date"))
    s = db.session.get(Signup, int(request.form.get("signup_id", 0)))
    if not s or s.club_id != current_user.club_id:
        abort(404)
    if s.member_id != current_user.id and not current_user.is_admin:
        abort(403)
    field = _field_by_key(s.field_key)
    group = field.group_key if field else None
    db.session.delete(s)
    db.session.flush()
    if group:
        rebalance_group(current_user.club_id, d, group)
    check_staffing_alerts(current_user.club_id, d)
    db.session.commit()
    return redirect(url_for("board.day", date=d.isoformat()))


@bp.route("/board/comment", methods=["POST"])
@login_required
def comment():
    d = _parse_day(request.form.get("date"))
    s = db.session.get(Signup, int(request.form.get("signup_id", 0)))
    if not s or s.club_id != current_user.club_id:
        abort(404)
    if s.member_id != current_user.id and not current_user.is_admin:
        abort(403)
    s.comment = request.form.get("comment", "").strip() or None
    db.session.commit()
    return redirect(url_for("board.day", date=d.isoformat()))


def _save_upload(file_storage):
    """Validate and save one uploaded image; return (stored_name, ext) or None."""
    name = file_storage.filename or ""
    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        return None
    stored = f"{secrets.token_hex(16)}.{ext}"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
    file_storage.save(path)
    return stored, ext


@bp.route("/board/forum", methods=["POST"])
@login_required
def forum_post():
    d = _parse_day(request.form.get("date"))
    body = request.form.get("body", "").strip()
    files = [f for f in request.files.getlist("images") if f and f.filename]

    if not body and not files:
        flash("Add a message or an image.", "error")
        return redirect(url_for("board.day", date=d.isoformat()))

    post = ForumPost(
        club_id=current_user.club_id, day=d, member_id=current_user.id,
        body=body or None,
    )
    db.session.add(post)
    db.session.flush()

    saved, rejected = 0, 0
    for f in files:
        result = _save_upload(f)
        if not result:
            rejected += 1
            continue
        stored, ext = result
        db.session.add(ForumAttachment(
            post_id=post.id, filename=stored,
            original_name=secure_filename(f.filename),
            content_type=f.mimetype,
        ))
        saved += 1

    if saved == 0 and not body:
        # Nothing usable was attached; drop the empty post.
        db.session.rollback()
        flash("Those files weren't accepted (images only: "
              f"{', '.join(sorted(ALLOWED_IMAGE_EXT))}).", "error")
        return redirect(url_for("board.day", date=d.isoformat()))

    db.session.commit()
    if rejected:
        flash(f"Posted. {rejected} file(s) skipped (images only).", "info")
    return redirect(url_for("board.day", date=d.isoformat()))


@bp.route("/board/forum/<int:post_id>/delete", methods=["POST"])
@login_required
def forum_delete(post_id):
    post = db.session.get(ForumPost, post_id)
    if not post or post.club_id != current_user.club_id:
        abort(404)
    if post.member_id != current_user.id and not current_user.is_admin:
        abort(403)
    d = post.day
    # Remove attachment files from disk, then the post (cascade clears rows).
    for att in post.attachments:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], att.filename))
        except OSError:
            pass
    db.session.delete(post)
    db.session.commit()
    return redirect(url_for("board.day", date=d.isoformat()))


@bp.route("/uploads/<path:name>")
@login_required
def uploaded_file(name):
    # Only serve known attachments to logged-in members of the owning club.
    att = ForumAttachment.query.filter_by(filename=name).first()
    if not att or att.post.club_id != current_user.club_id:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], name)
