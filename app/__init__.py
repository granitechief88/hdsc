"""Application factory for the High Desert Soaring Club site + scheduler."""
import os

from flask import Flask
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
        DOCUMENTS_FOLDER=os.path.join(app.instance_path, "documents"),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,  # 25 MB cap on uploads
    )
    if config:
        app.config.update(config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["DOCUMENTS_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import Member

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Member, int(user_id))

    # Blueprints
    from .views_site import bp as site_bp
    from .views_auth import bp as auth_bp
    from .views_board import bp as board_bp
    from .views_events import bp as events_bp
    from .views_messages import bp as messages_bp
    from .views_admin import bp as admin_bp

    app.register_blueprint(site_bp)      # owns "/" and the public club pages
    app.register_blueprint(auth_bp)
    app.register_blueprint(board_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(admin_bp)

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

    @app.cli.command("init-site")
    def init_site():
        """Create tables and seed the club, roles, board fields, and admin."""
        from .seed import seed_site

        db.drop_all()
        db.create_all()
        seed_site()

    @app.cli.command("import-club-db")
    def import_club_db():
        """Import users from the old club-website sqlite DB into Member.

        Usage: flask --app "app:create_app" import-club-db <path> [email-domain]
        Preserves each user's existing password hash and admin flag.
        """
        import sys
        from .seed import import_website_users

        args = sys.argv[sys.argv.index("import-club-db") + 1:]
        if not args:
            print("Usage: import-club-db <soaringclub.db path> [email-domain]")
            return
        path = args[0]
        domain = args[1] if len(args) > 1 else "highdesertsoaring.org"
        n = import_website_users(path, domain)
        print(f"Imported/updated {n} user(s) from {path}.")

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
    # tables exist and, unless disabled, seed the club so the site works
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
            from .seed import seed_site

            seed_site()
            app.logger.info("Seeded club, roles, board fields, and admin on first boot.")
    except Exception as exc:  # pragma: no cover - don't crash the app on boot
        db.session.rollback()
        app.logger.warning("Auto-seed skipped: %s", exc)
