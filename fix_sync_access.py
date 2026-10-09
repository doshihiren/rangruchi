import ast

with open(r"flask_app\routes\admin.py","r",encoding="utf-8") as f:
    code = f.read()

# Find admin_required decorator on sync routes and add CHIRAG
OLD = '''def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "Owner":
            flash("Access denied.", "error")
            return redirect(url_for("home.dashboard"))
        return f(*args, **kwargs)
    return decorated'''

NEW = '''def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "Owner":
            flash("Access denied.", "error")
            return redirect(url_for("home.dashboard"))
        return f(*args, **kwargs)
    return decorated

def sync_allowed(f):
    """Allow Owner or CHIRAG to run syncs"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "Owner" and session.get("username") != "CHIRAG":
            flash("Access denied.", "error")
            return redirect(url_for("home.dashboard"))
        return f(*args, **kwargs)
    return decorated'''

if OLD in code:
    code = code.replace(OLD, NEW)
    # Replace @admin_required on sync routes with @sync_allowed
    code = code.replace(
        '@admin_bp.route("/admin/sync", methods=["POST"])\n@login_required\n@admin_required\ndef trigger_sync',
        '@admin_bp.route("/admin/sync", methods=["POST"])\n@login_required\n@sync_allowed\ndef trigger_sync'
    )
    code = code.replace(
        '@admin_bp.route("/admin/sync-pdc", methods=["POST"])\n@login_required\n@admin_required\ndef trigger_pdc_sync',
        '@admin_bp.route("/admin/sync-pdc", methods=["POST"])\n@login_required\n@sync_allowed\ndef trigger_pdc_sync'
    )
    try:
        ast.parse(code)
        with open(r"flask_app\routes\admin.py","w",encoding="utf-8") as f:
            f.write(code)
        print("Fixed: CHIRAG can now run Tally Sync and PDC Sync")
    except SyntaxError as e:
        print(f"ERROR: {e}")
else:
    print("MISS")
