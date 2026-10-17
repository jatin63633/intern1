"""Connection handling (database access layer, part 1)."""
import os
import sqlite3
from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    app.teardown_appcontext(close_db)
    with app.app_context():
        with app.open_resource("schema.sql") as f:
            get_db().executescript(f.read().decode())
