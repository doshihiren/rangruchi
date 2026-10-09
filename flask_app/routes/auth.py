from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import hashlib
from db import fetchone

auth_bp = Blueprint("auth", __name__)

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("role") not in roles:
                flash("Access denied.", "error")
                return redirect(url_for("home.dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator

@auth_bp.route("/", methods=["GET","POST"])
@auth_bp.route("/login", methods=["GET","POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("home.dashboard"))
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        user = fetchone(
            "SELECT id,username,role,tally_name FROM users WHERE username=%s AND password=%s AND is_active=TRUE",
            (username, hash_pw(password))
        )
        if user:
            session.update({
                "logged_in":  True,
                "username":   user["username"],
                "role":       user["role"],
                "user_id":    user["id"],
                "tally_name": user.get("tally_name",""),
            })
            return redirect(url_for("home.dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
