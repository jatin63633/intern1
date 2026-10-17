"""Authentication + role-based access control."""
import re
from functools import wraps
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import repo

bp = Blueprint("auth", __name__)
ROLES = ["admin", "doctor", "staff"]


@bp.before_app_request
def load_user():
    uid = session.get("user_id")
    g.user = repo.get_user(uid) if uid else None


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def role_required(*roles):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if g.user["role"] not in roles:
                abort(403, "Your role does not have access to this page.")
            return view(*a, **kw)
        return wrapped
    return deco


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = repo.get_user_by_name(request.form.get("username", "").strip())
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["user_id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u, p = request.form.get("username", "").strip(), request.form.get("password", "")
        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", u):
            flash("Username must be 3-30 letters, digits or underscores.", "danger")
        elif len(p) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif repo.get_user_by_name(u):
            flash("That username is taken.", "danger")
        else:
            role = "admin" if repo.count_users() == 0 else "staff"     # others are upgraded by an admin
            repo.create_user(u, generate_password_hash(p), role)
            flash(f"Account created with role '{role}'. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("register.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/admin/users", methods=["GET", "POST"])
@role_required("admin")
def users():
    if request.method == "POST":
        uid, role = request.form.get("user_id", type=int), request.form.get("role")
        target = repo.get_user(uid) if uid else None
        if role not in ROLES or target is None:
            flash("Invalid request.", "danger")
        elif target["role"] == "admin" and role != "admin" and repo.count_admins() <= 1:
            flash("There must be at least one administrator.", "danger")
        else:
            repo.set_role(uid, role)
            flash(f"{target['username']} is now '{role}'.", "success")
        return redirect(url_for("auth.users"))
    return render_template("users.html", users=repo.list_users(), roles=ROLES)
