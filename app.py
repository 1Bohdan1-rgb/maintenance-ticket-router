import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

from models import Technician, db
from routes import bp as tickets_bp
from translations import DEFAULT_LANG, TRANSLATIONS

load_dotenv()

SEED_TECHNICIANS = [
    {"name": "Oksana Melnyk", "specialty": "plumbing", "available": True},
    {"name": "Ivan Petrenko", "specialty": "electrical", "available": True},
    {"name": "Sergiy Boyko", "specialty": "carpentry", "available": False},
    {"name": "Nadia Kravets", "specialty": "general", "available": True},
]


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///tickets.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")

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
