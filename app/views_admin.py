"""Administration: manage members, roles, sign-up fields, and view email outbox."""
import re
import secrets
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from .extensions import db
from .models import Member, Role, FieldDef, Signup, EmailOutbox
from .scheduling import generate_reminders

bp = Blueprint("admin", __name__, url_prefix="/admin")

FIELD_KINDS = ["LIST", "PROVIDER", "CONSUMER", "WAITING"]
DAY_TYPE_CHOICES = ["weekday", "weekend"]


def _slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug or "field"


def _unique_key(club_id, base):
    key, n = base, 2
    existing = {
        f.key for f in FieldDef.query.filter_by(club_id=club_id).all()
    }
    while key in existing:
        key = f"{base}_{n}"
        n += 1
    return key


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **k):
        if not current_user.is_admin:
            abort(403)
        return fn(*a, **k)
    return wrapper


@bp.route("/")
@admin_required
def home():
    members = (
        Member.query.filter_by(club_id=current_user.club_id)
        .order_by(Member.last_name)
        .all()
    )
    return render_template("admin_home.html", members=members)


@bp.route("/members/new", methods=["GET", "POST"])
@admin_required
def new_member():
    roles = Role.query.filter_by(club_id=current_user.club_id).order_by(Role.name).all()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Email is required.", "error")
            return redirect(url_for("admin.new_member"))
        if Member.query.filter_by(email=email).first():
            flash("A member with that email already exists.", "error")
            return redirect(url_for("admin.new_member"))
        m = Member(
            club_id=current_user.club_id,
            email=email,
            first_name=request.form.get("first_name", "").strip(),
            last_name=request.form.get("last_name", "").strip(),
            membership_number=request.form.get("membership_number", "").strip(),
            is_admin=bool(request.form.get("is_admin")),
            activation_token=secrets.token_urlsafe(24),
        )
        selected = set(request.form.getlist("roles"))
        m.roles = [r for r in roles if str(r.id) in selected]
        db.session.add(m)
        db.session.commit()
        # In production this link would be emailed; here we surface it to the admin.
        link = url_for("auth.activate", token=m.activation_token, _external=True)
        flash(f"Member created. Activation link: {link}", "success")
        return redirect(url_for("admin.home"))
    return render_template("admin_member_form.html", roles=roles, member=None)


@bp.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_member(member_id):
    m = db.session.get(Member, member_id)
    if not m or m.club_id != current_user.club_id:
        abort(404)
    roles = Role.query.filter_by(club_id=current_user.club_id).order_by(Role.name).all()
    if request.method == "POST":
        m.first_name = request.form.get("first_name", m.first_name).strip()
        m.last_name = request.form.get("last_name", m.last_name).strip()
        m.membership_number = request.form.get("membership_number", "").strip()
        m.is_admin = bool(request.form.get("is_admin"))
        selected = set(request.form.getlist("roles"))
        m.roles = [r for r in roles if str(r.id) in selected]
        db.session.commit()
        flash("Member updated.", "success")
        return redirect(url_for("admin.home"))
    return render_template("admin_member_form.html", roles=roles, member=m)


@bp.route("/members/<int:member_id>/delete", methods=["POST"])
@admin_required
def delete_member(member_id):
    m = db.session.get(Member, member_id)
    if not m or m.club_id != current_user.club_id:
        abort(404)
    if m.id == current_user.id:
        flash("You can't delete your own account.", "error")
        return redirect(url_for("admin.home"))
    db.session.delete(m)
    db.session.commit()
    flash("Member removed.", "success")
    return redirect(url_for("admin.home"))


@bp.route("/roles", methods=["GET", "POST"])
@admin_required
def roles():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            db.session.add(Role(club_id=current_user.club_id, name=name))
            db.session.commit()
            flash("Role added.", "success")
        return redirect(url_for("admin.roles"))
    role_list = (
        Role.query.filter_by(club_id=current_user.club_id).order_by(Role.name).all()
    )
    return render_template("admin_roles.html", roles=role_list)


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@admin_required
def delete_role(role_id):
    r = db.session.get(Role, role_id)
    if r and r.club_id == current_user.club_id:
        db.session.delete(r)
        db.session.commit()
        flash("Role deleted.", "success")
    return redirect(url_for("admin.roles"))


@bp.route("/fields")
@admin_required
def fields():
    field_list = (
        FieldDef.query.filter_by(club_id=current_user.club_id)
        .order_by(FieldDef.column, FieldDef.position)
        .all()
    )
    return render_template("admin_fields.html", fields=field_list)


def _apply_field_form(field, form, club_id, roles):
    """Populate a FieldDef from submitted form data. Returns an error string
    or None on success."""
    label = form.get("label", "").strip()
    if not label:
        return "Label is required."
    kind = form.get("kind", "LIST")
    if kind not in FIELD_KINDS:
        return "Invalid field type."
    group_key = form.get("group_key", "").strip() or None
    if kind != "LIST" and not group_key:
        return "Instructor/Student/Waiting fields need a group name to link them."

    day_types = [d for d in form.getlist("day_types") if d in DAY_TYPE_CHOICES]
    if not day_types:
        return "Choose at least one of weekday / weekend."

    allowed = [r.name for r in roles if str(r.id) in set(form.getlist("allowed_roles"))]

    def _int(name, default=None):
        raw = form.get(name, "").strip()
        return int(raw) if raw.isdigit() else default

    field.label = label
    field.kind = kind
    field.group_key = group_key
    field.day_types = ",".join(day_types)
    field.allowed_roles = ",".join(allowed)
    field.column = min(3, max(1, _int("column", 1) or 1))
    field.position = _int("position", field.position or 0) or 0
    field.max_slots = _int("max_slots", None)
    field.default_offer = _int("default_offer", 1) or 1
    return None


@bp.route("/fields/new", methods=["GET", "POST"])
@admin_required
def new_field():
    roles = Role.query.filter_by(club_id=current_user.club_id).order_by(Role.name).all()
    if request.method == "POST":
        field = FieldDef(club_id=current_user.club_id)
        err = _apply_field_form(field, request.form, current_user.club_id, roles)
        if err:
            flash(err, "error")
            return render_template(
                "admin_field_form.html", roles=roles, field=None,
                kinds=FIELD_KINDS, form=request.form,
            )
        field.key = _unique_key(current_user.club_id, _slugify(field.label))
        # Default new fields to the end of their column.
        if not request.form.get("position", "").strip():
            last = (
                FieldDef.query.filter_by(club_id=current_user.club_id, column=field.column)
                .order_by(FieldDef.position.desc())
                .first()
            )
            field.position = (last.position + 1) if last else 0
        db.session.add(field)
        db.session.commit()
        flash(f"Field “{field.label}” added to the day board.", "success")
        return redirect(url_for("admin.fields"))
    return render_template(
        "admin_field_form.html", roles=roles, field=None, kinds=FIELD_KINDS, form=None
    )


@bp.route("/fields/<int:field_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_field(field_id):
    field = db.session.get(FieldDef, field_id)
    if not field or field.club_id != current_user.club_id:
        abort(404)
    roles = Role.query.filter_by(club_id=current_user.club_id).order_by(Role.name).all()
    if request.method == "POST":
        err = _apply_field_form(field, request.form, current_user.club_id, roles)
        if err:
            flash(err, "error")
            db.session.rollback()
            return render_template(
                "admin_field_form.html", roles=roles, field=field,
                kinds=FIELD_KINDS, form=request.form,
            )
        db.session.commit()
        flash("Field updated.", "success")
        return redirect(url_for("admin.fields"))
    return render_template(
        "admin_field_form.html", roles=roles, field=field, kinds=FIELD_KINDS, form=None
    )


@bp.route("/fields/<int:field_id>/delete", methods=["POST"])
@admin_required
def delete_field(field_id):
    field = db.session.get(FieldDef, field_id)
    if not field or field.club_id != current_user.club_id:
        abort(404)
    # Remove any sign-ups recorded against this field so none are orphaned.
    Signup.query.filter_by(club_id=current_user.club_id, field_key=field.key).delete()
    db.session.delete(field)
    db.session.commit()
    flash("Field removed from the day board.", "success")
    return redirect(url_for("admin.fields"))


@bp.route("/outbox")
@admin_required
def outbox():
    emails = (
        EmailOutbox.query.filter_by(club_id=current_user.club_id)
        .order_by(EmailOutbox.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template("admin_outbox.html", emails=emails)


@bp.route("/outbox/run-reminders", methods=["POST"])
@admin_required
def run_reminders():
    n = generate_reminders(current_user.club_id)
    flash(f"Queued {n} reminder email(s) for sign-ups two days out.", "success")
    return redirect(url_for("admin.outbox"))
