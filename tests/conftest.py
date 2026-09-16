import pytest

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def app(monkeypatch):
    """A Flask app wired to a fresh in-memory SQLite database per test.

    Also strips out ANTHROPIC_API_KEY/SMTP_* so any code path that isn't
    explicitly mocked falls back to its deterministic no-AI/no-email
    behavior instead of making a real network call - tests that DO want
    the AI path set ANTHROPIC_API_KEY themselves and monkeypatch the
    anthropic client (see tests/fakes.py).
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    from app import create_app
    from models import db

    application = create_app()
    application.config["TESTING"] = True

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_headers():
    return {"X-Admin-Token": ADMIN_TOKEN}


@pytest.fixture
def ctx(app):
    """An active app context, for tests that query the ORM directly
    instead of only going through the test client.
    """
    with app.app_context():
        yield app
