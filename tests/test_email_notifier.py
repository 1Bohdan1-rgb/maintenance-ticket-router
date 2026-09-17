"""email_notifier._build_technician_notification_message() - the HTML/plain
assignment email, built and inspected directly (no SMTP needed) via the
refactor that split message-building out of send_technician_notification.
"""
import base64

from email_notifier import _build_technician_notification_message
from models import Technician, Ticket, db

# A valid 1x1 transparent PNG, base64-encoded (no "data:" prefix - matches
# how Ticket.photo_data is stored).
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _make_ticket(**overrides):
    defaults = dict(
        title="Leaky tap",
        description="Kitchen tap is dripping constantly",
        category="plumbing",
        priority="high",
        urgency_reason="Water waste and potential fitting damage.",
        customer_email="customer@example.com",
    )
    defaults.update(overrides)
    ticket = Ticket(**defaults)
    db.session.add(ticket)
    db.session.commit()
    return ticket


def _html_part(message):
    for part in message.walk():
        if part.get_content_type() == "text/html":
            return part.get_content()
    raise AssertionError("no text/html part found in message")


def test_message_has_plain_and_html_alternative(ctx):
    technician = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _make_ticket()

    message = _build_technician_notification_message(ticket, technician, "sender@example.com")

    assert message.get_content_type() == "multipart/alternative"
    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = _html_part(message)

    assert "Kitchen tap is dripping constantly" in plain
    assert "Kitchen tap is dripping constantly" in html
    assert "customer@example.com" in plain
    assert "customer@example.com" in html


def test_message_includes_severity_when_present(ctx):
    technician = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _make_ticket(severity=5, severity_reason="Photo shows a fully collapsed ceiling.")

    message = _build_technician_notification_message(ticket, technician, "sender@example.com")

    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = _html_part(message)

    assert "5/5" in plain
    assert "Photo shows a fully collapsed ceiling." in plain
    assert "5/5" in html
    assert "Photo shows a fully collapsed ceiling." in html


def test_message_omits_severity_when_absent(ctx):
    technician = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _make_ticket(severity=None)

    message = _build_technician_notification_message(ticket, technician, "sender@example.com")

    html = _html_part(message)
    assert "/5" not in html


def test_message_embeds_photo_as_inline_related_part(ctx):
    technician = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _make_ticket(photo_data=_TINY_PNG_B64, photo_content_type="image/png")

    message = _build_technician_notification_message(ticket, technician, "sender@example.com")

    html = _html_part(message)
    assert 'src="cid:' in html

    image_parts = [p for p in message.walk() if p.get_content_maintype() == "image"]
    assert len(image_parts) == 1
    assert image_parts[0].get_content_subtype() == "png"
    assert image_parts[0].get_payload(decode=True) == base64.b64decode(_TINY_PNG_B64)


def test_message_has_no_image_part_without_photo(ctx):
    technician = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _make_ticket()

    message = _build_technician_notification_message(ticket, technician, "sender@example.com")

    image_parts = [p for p in message.walk() if p.get_content_maintype() == "image"]
    assert image_parts == []
    assert 'src="cid:' not in _html_part(message)


def test_html_escapes_description_and_reasoning(ctx):
    technician = Technician.query.filter_by(specialty="plumbing").first()
    ticket = _make_ticket(
        description="<script>alert(1)</script> water everywhere",
        urgency_reason="<b>fake bold</b>",
    )

    message = _build_technician_notification_message(ticket, technician, "sender@example.com")

    html = _html_part(message)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>fake bold</b>" not in html
