"""Public club-site pages plus the members-only Documents area.

These were carried over from the standalone club website and now live inside
the combined app, sharing its single user database and login.
"""
import os

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    current_app, send_from_directory,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

bp = Blueprint("site", __name__)

ALLOWED_DOC_EXT = {
    "pdf", "doc", "docx", "txt", "rtf", "odt",
    "xls", "xlsx", "csv", "ppt", "pptx",
    "png", "jpg", "jpeg", "gif",
}


def _docs_folder():
    return current_app.config["DOCUMENTS_FOLDER"]


def _list_documents():
    folder = _docs_folder()
    files = []
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if not name.startswith("."):
                files.append(name)
    return sorted(files)


# --- Public pages --------------------------------------------------------
@bp.route("/")
def index():
    return render_template("site/index.html", title="High Desert Soaring Club")


@bp.route("/about")
def about():
    return render_template("site/about.html", title="About the Club")


@bp.route("/fleet")
def fleet():
    return render_template("site/fleet.html", title="Our Fleet")


@bp.route("/contact")
def contact():
    return render_template("site/contact.html", title="Visit & Contact")


# --- Members-only documents ---------------------------------------------
@bp.route("/documents")
@login_required
def documents():
    return render_template(
        "site/documents.html", title="Club Documents", files=_list_documents()
    )


@bp.route("/documents/upload", methods=["GET", "POST"])
@login_required
def upload_document():
    if not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("No file selected.", "warning")
            return redirect(url_for("site.upload_document"))
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if not filename or ext not in ALLOWED_DOC_EXT:
            flash(
                "That file type isn't allowed. Permitted: "
                + ", ".join(sorted(ALLOWED_DOC_EXT)) + ".",
                "danger",
            )
            return redirect(url_for("site.upload_document"))
        os.makedirs(_docs_folder(), exist_ok=True)
        file.save(os.path.join(_docs_folder(), filename))
        flash(f"“{filename}” uploaded.", "success")
        return redirect(url_for("site.documents"))
    return render_template("site/document_upload.html", title="Upload Document")


@bp.route("/documents/download/<path:filename>")
@login_required
def download_document(filename):
    return send_from_directory(_docs_folder(), filename, as_attachment=True)


@bp.route("/documents/delete/<path:filename>", methods=["POST"])
@login_required
def delete_document(filename):
    if not current_user.is_admin:
        abort(403)
    safe = secure_filename(filename)
    path = os.path.join(_docs_folder(), safe)
    if os.path.isfile(path):
        os.remove(path)
        flash(f"“{safe}” deleted.", "info")
    return redirect(url_for("site.documents"))
