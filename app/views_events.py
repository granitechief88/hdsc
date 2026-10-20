"""Events: theory lessons, maintenance days, socials — sign up in one click."""
from datetime import date, datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from .extensions import db
from .models import Event, EventSignup

bp = Blueprint("events", __name__, url_prefix="/events")


@bp.route("/")
@login_required
def list_events():
    events = (
        Event.query.filter(
            Event.club_id == current_user.club_id, Event.day >= date.today()
        )
        .order_by(Event.day)
        .all()
    )
    return render_template("events.html", events=events)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_event():
    default_day = request.args.get("date", date.today().isoformat())
    if request.method == "POST":
        try:
            d = datetime.strptime(request.form.get("day", ""), "%Y-%m-%d").date()
        except ValueError:
            flash("Please choose a valid date.", "error")
            return redirect(url_for("events.new_event"))
        cap_raw = request.form.get("capacity", "").strip()
        event = Event(
            club_id=current_user.club_id,
            day=d,
            title=request.form.get("title", "").strip() or "Untitled event",
            description=request.form.get("description", "").strip(),
            capacity=int(cap_raw) if cap_raw.isdigit() else None,
            created_by_id=current_user.id,
        )
        db.session.add(event)
        db.session.commit()
        flash("Event created.", "success")
        return redirect(url_for("events.list_events"))
    return render_template("event_new.html", default_day=default_day)


@bp.route("/<int:event_id>/signup", methods=["POST"])
@login_required
def signup(event_id):
    event = db.session.get(Event, event_id)
    if not event or event.club_id != current_user.club_id:
        abort(404)
    already = EventSignup.query.filter_by(
        event_id=event.id, member_id=current_user.id
    ).first()
    if already:
        flash("You're already signed up.", "info")
    elif event.capacity and len(event.signups) >= event.capacity:
        flash("This event is full.", "error")
    else:
        db.session.add(EventSignup(event_id=event.id, member_id=current_user.id))
        db.session.commit()
    return redirect(url_for("events.list_events"))


@bp.route("/<int:event_id>/leave", methods=["POST"])
@login_required
def leave(event_id):
    su = EventSignup.query.filter_by(
        event_id=event_id, member_id=current_user.id
    ).first()
    if su:
        db.session.delete(su)
        db.session.commit()
    return redirect(url_for("events.list_events"))
