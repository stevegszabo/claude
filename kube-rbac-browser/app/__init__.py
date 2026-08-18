import os

from flask import Flask, render_template, session

from . import k8s
from .k8s import RBACBrowserError


def _age(timestamp) -> str:
    if timestamp is None:
        return "-"
    from datetime import datetime, timezone

    delta = datetime.now(timezone.utc) - timestamp
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 365:
        return f"{days}d"
    return f"{days // 365}y"


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
    app.jinja_env.filters["age"] = _age

    # Fail fast at startup if the kubeconfig can't be read at all.
    k8s.list_contexts()

    from .routes import bp

    app.register_blueprint(bp)

    @app.context_processor
    def inject_context_info():
        contexts, default_name = k8s.list_contexts()
        return {
            "available_contexts": contexts,
            "default_context_name": default_name,
            "current_context_name": session.get("kube_context") or default_name,
        }

    @app.errorhandler(RBACBrowserError)
    def handle_rbac_error(err: RBACBrowserError):
        return render_template("error.html", message=err.message), err.status

    return app
