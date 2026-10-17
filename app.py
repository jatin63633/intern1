import hmac
import secrets
from flask import Flask, abort, render_template, request, session
from config import Config
import db


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)
    db.init_app(app)

    from auth import bp as auth_bp
    from views import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.jinja_env.globals["zip"] = zip

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
            token = session.get("_csrf", "")
            if not token or not hmac.compare_digest(token, sent):
                abort(400, "Invalid or missing CSRF token. Reload the page and try again.")

    @app.context_processor
    def inject_csrf():
        session.setdefault("_csrf", secrets.token_hex(16))
        return {"csrf_token": session["_csrf"]}

    @app.after_request
    def no_cache_for_patient_data(resp):
        resp.headers["Cache-Control"] = "no-store"          # sensitive pages should not be cached
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    for code in (400, 403, 404, 413):
        app.register_error_handler(code, lambda e: (render_template("error.html", error=e), e.code))
    return app


if __name__ == "__main__":
    create_app().run(debug=True)
