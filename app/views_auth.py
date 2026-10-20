"""Authentication: activation, login, logout, personal settings."""
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_user, logout_user, login_required, current_user

from .extensions import db
from .models import Member

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("board.day"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        stay = bool(request.form.get("stay"))
        member = Member.query.filter_by(email=email).first()
        if member and member.activated and member.check_password(password):
            login_user(member, remember=stay)
            return redirect(request.args.get("next") or url_for("board.day"))
        if member and not member.activated:
            flash("Your account isn't activated yet. Use your activation link.", "error")
        else:
            flash("Incorrect email or password.", "error")
    return render_template("login.html")


@bp.route("/activate/<token>", methods=["GET", "POST"])
def activate(token):
    member = Member.query.filter_by(activation_token=token).first()
    if not member:
        abort(404)
    if member.activated:
        flash("This account is already activated — please log in.", "info")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        pw = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if len(pw) < 6:
            flash("Password must be at least 6 characters.", "error")
        elif pw != confirm:
            flash("Passwords do not match.", "error")
        else:
            member.set_password(pw)
            member.activated = True
            member.activation_token = None
            db.session.commit()
            login_user(member)
            flash("Account activated. Welcome!", "success")
            return redirect(url_for("board.day"))
    return render_template("activate.html", member=member)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        current_user.first_name = request.form.get("first_name", current_user.first_name).strip()
        current_user.last_name = request.form.get("last_name", current_user.last_name).strip()
        current_user.wants_reminders = bool(request.form.get("wants_reminders"))
        new_pw = request.form.get("password", "")
        if new_pw:
            if len(new_pw) < 6:
                flash("Password must be at least 6 characters.", "error")
                return redirect(url_for("auth.settings"))
            current_user.set_password(new_pw)
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("auth.settings"))
    return render_template("settings.html")
