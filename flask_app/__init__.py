from flask import Flask
from flask_session import Session
import os, sys, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("APP_SECRET_KEY", "recoveryos-secret-2026")
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_PERMANENT"] = False

    Session(app)

    # Indian number format filter
    @app.template_filter("indian")
    def indian_format(n):
        try:
            n = int(float(n or 0))
            if n < 0: return "-" + indian_format(-n)
            s = str(n)
            if len(s) <= 3: return s
            result = s[-3:]
            s = s[:-3]
            while len(s) > 2:
                result = s[-2:] + "," + result
                s = s[:-2]
            if s: result = s + "," + result
            return result
        except: return str(n)

    # Register urlencode filter for templates
    @app.template_filter("urlencode")
    def urlencode_filter(s):
        return urllib.parse.quote(str(s), safe="")

    # Register blueprints
    from flask_app.routes.auth      import auth_bp
    from flask_app.routes.home      import home_bp
    from flask_app.routes.tickets   import tickets_bp
    from flask_app.routes.followups import followups_bp
    from flask_app.routes.ledger    import ledger_bp
    from flask_app.routes.analytics import analytics_bp
    from flask_app.routes.admin     import admin_bp
    from flask_app.routes.api       import api_bp
    from flask_app.routes.ledger_pdf import ledger_pdf_bp
    from flask_app.routes.invoices   import invoices_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(followups_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(ledger_pdf_bp)
    app.register_blueprint(invoices_bp)

    return app
