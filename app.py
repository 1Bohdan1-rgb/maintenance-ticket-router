import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from models import Technician, db
from routes import bp as tickets_bp
from translations import DEFAULT_LANG, TRANSLATIONS

load_dotenv()

SEED_TECHNICIANS = [
    {
        "name": "Oksana Melnyk",
        "specialty": "plumbing",
        "available": True,
        "email": "oksana@example.com",
        "phone": "+380671234567",
    },
    {
        "name": "Ivan Petrenko",
        "specialty": "electrical",
        "available": True,
        "email": "ivan@example.com",
        "phone": "+380509876543",
    },
    {
        "name": "Sergiy Boyko",
        "specialty": "carpentry",
        "available": True,
        "email": "sergiy@example.com",
        "phone": "+380631112233",
    },
    {
        "name": "Nadia Kravets",
        "specialty": "general",
        "available": True,
        "email": "nadia@example.com",
        "phone": "+380971239876",
    },
]


def _normalized_database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///tickets.db")
    # Render (and some other providers) hand out "postgres://", but
    # SQLAlchemy 1.4+/2.x only accepts the "postgresql://" scheme.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def create_app():
    app = Flask(__name__)
    # Render (and most PaaS hosts) sit behind a reverse proxy - without this,
    # url_for(..., _external=True) generates http:// links (wrong scheme/host)
    # for things like the completion-email review link.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalized_database_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB, for resume uploads

    db.init_app(app)
    app.register_blueprint(tickets_bp)

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            translations_json=json.dumps(TRANSLATIONS, ensure_ascii=False),
            default_lang=DEFAULT_LANG,
            t=TRANSLATIONS[DEFAULT_LANG],
        )

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "maintenance-ticket-router"})

    with app.app_context():
        db.create_all()
        seed_technicians()

    return app


def seed_technicians():
    if Technician.query.first() is not None:
        return
    for data in SEED_TECHNICIANS:
        db.session.add(Technician(**data))
    db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
