"""Internal mailbox: message a member, all instructors, all students, everyone."""
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from .extensions import db
from .models import Member, Message, Role
from .scheduling import queue_email

bp = Blueprint("messages", __name__, url_prefix="/messages")

# Audience label -> function returning recipient members.
def _audience_members(label):
    club_id = current_user.club_id
    base = Member.query.filter_by(club_id=club_id, activated=True)
    if label == "All members":
        return base.all()
    if label.startswith("All "):
        role = label[4:].rstrip("s")  # "All Instructors" -> "Instructor"
        role = {"Student": "Dual student", "Instructor": "Instructor"}.get(role, role)
        return base.filter(Member.roles.any(name=role)).all()
    return []


@bp.route("/")
@login_required
def inbox():
    msgs = (
        Message.query.filter_by(recipient_id=current_user.id)
        .order_by(Message.created_at.desc())
        .all()
    )
    return render_template("messages.html", msgs=msgs)


@bp.route("/<int:msg_id>")
@login_required
def view(msg_id):
    msg = db.session.get(Message, msg_id)
    if not msg or msg.recipient_id != current_user.id:
        abort(404)
    if not msg.read:
        msg.read = True
        db.session.commit()
    return render_template("message_view.html", msg=msg)


@bp.route("/compose", methods=["GET", "POST"])
@login_required
def compose():
    members = (
        Member.query.filter_by(club_id=current_user.club_id, activated=True)
        .order_by(Member.last_name)
        .all()
    )
    roles = Role.query.filter_by(club_id=current_user.club_id).all()
    audiences = ["All members"] + [f"All {r.name}s" for r in roles]

    if request.method == "POST":
        subject = request.form.get("subject", "").strip() or "(no subject)"
        body = request.form.get("body", "").strip()
        target = request.form.get("target", "")
        recipients = []
        if target.startswith("member:"):
            m = db.session.get(Member, int(target.split(":", 1)[1]))
            if m and m.club_id == current_user.club_id:
                recipients = [m]
        else:
            recipients = _audience_members(target)

        if not recipients:
            flash("No recipients matched.", "error")
            return redirect(url_for("messages.compose"))

        audience_label = target if not target.startswith("member:") else None
        for m in recipients:
            db.session.add(
                Message(
                    club_id=current_user.club_id,
                    sender_id=current_user.id,
                    recipient_id=m.id,
                    audience=audience_label,
                    subject=subject,
                    body=body,
                )
            )
            queue_email(current_user.club_id, m.email, subject, body, "message")
        db.session.commit()
        flash(f"Message sent to {len(recipients)} member(s).", "success")
        return redirect(url_for("messages.inbox"))

    return render_template(
        "message_compose.html", members=members, audiences=audiences
    )
