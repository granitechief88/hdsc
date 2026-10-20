"""WSGI entry point for production servers (PythonAnywhere, gunicorn, etc.).

PythonAnywhere: point your web app's WSGI file at this module's `application`
(see DEPLOY.md). gunicorn:  `gunicorn wsgi:application`.
"""
from app import create_app

application = create_app()
app = application  # some tools look for `app`

if __name__ == "__main__":
    application.run()
