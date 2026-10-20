"""Application factory for Soar Scheduler."""
import os

from flask import Flask, redirect, url_for
from flask_login import current_user

from .extensions import db, login_manager


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI="sqlite:///"
        + os.path.join(app.instance_path, "soar.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        REMEMBER_COOKIE_DURATION=60 * 60 * 24 * 30,  # "stay connected" ~30 days
        UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,  # 12 MB cap on uploads
    )
    if config:
        app.config.update(config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import Member

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Member, int(user_id))

    # Blueprints
    from .views_auth import bp as auth_bp
    from .views_board import bp as board_bp
    from .views_events import bp as events_bp
    from .views_messages import bp as messages_bp
    from .views_admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(board_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("board.day"))
        return redirect(url_for("auth.login"))

    # Make unread-message count available to every template.
    @app.context_processor
    def inject_globals():
        from .models import Message

        unread = 0
        if current_user.is_authenticated:
            unread = Message.query.filter_by(
                recipient_id=current_user.id, read=False
            ).count()
        return {"unread_messages": unread}

    @app.cli.command("init-demo")
    def init_demo():
        """Create tables and load demo club/members/fields."""
        from .seed import seed_demo

        db.drop_all()
        db.create_all()
        seed_demo()
        print("Demo data loaded.")

    @app.cli.command("send-reminders")
    def send_reminders():
        """Queue 2-day reminder emails for every club (for a daily scheduled job)."""
        from .models import Club
        from .scheduling import generate_reminders

        total = 0
        for club in Club.query.all():
            total += generate_reminders(club.id)
        print(f"Queued {total} reminder email(s).")

    # On first boot (e.g. a fresh deploy with no shell access), make sure the
    # tables exist and, unless disabled, load the demo club so the site works
    # immediately. Idempotent: seeding only runs when the database is empty.
    with app.app_context():
        _ensure_initialized(app)

    return app


def _ensure_initialized(app):
    from .models import Club

    db.create_all()
    if os.environ.get("AUTO_SEED", "1") == "0":
        return
    try:
        if Club.query.first() is None:
            from .seed import seed_demo

            seed_demo()
            app.logger.info("Seeded demo data on first boot.")
    except Exception as exc:  # pragma: no cover - don't crash the app on boot
        db.session.rollback()
        app.logger.warning("Auto-seed skipped: %s", exc)
