import base64
import binascii
import logging
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, url_for

from ai_classifier import classify_ticket
from email_notifier import (
    send_completion_email,
    send_confirmation_email,
    send_technician_notification,
)
from models import (
    ALLOWED_PHOTO_TYPES,
    MATCH_PRIORITIES,
    MAX_PHOTO_BYTES,
    PRICE_TIERS,
    SPECIALTIES,
    SPEED_RATINGS,
    STATUSES,
    Technician,
    Ticket,
    TicketAssignment,
    db,
)
from resume_processor import ResumeProcessingError, allowed_filename, extract_text, generate_summary
from technician_assignment import select_technician_team
from translations import TRANSLATIONS, DEFAULT_LANG

logger = logging.getLogger(__name__)

bp = Blueprint("tickets", __name__)

_PHOTO_DATA_URI_RE = re.compile(r"^data:(image/[\w+.-]+);base64,(.+)$", re.DOTALL)


def _parse_photo_data_uri(data_uri):
    """Parse a 'data:image/jpeg;base64,....' URI from the photo upload field.

    Returns (content_type, base64_payload) on success. Raises ValueError
    with a translations error-key ("error_photo_invalid_type" or
    "error_photo_too_large") on an unsupported/malformed type or a decoded
    payload bigger than MAX_PHOTO_BYTES.
    """
    match = _PHOTO_DATA_URI_RE.match(data_uri)
    if not match:
        raise ValueError("error_photo_invalid_type")

    content_type, payload = match.group(1), match.group(2)
    if content_type not in ALLOWED_PHOTO_TYPES:
        raise ValueError("error_photo_invalid_type")

    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("error_photo_invalid_type") from exc

    if len(decoded) > MAX_PHOTO_BYTES:
        raise ValueError("error_photo_too_large")

    return content_type, payload

DASHBOARD_CATEGORIES = ("plumbing", "electrical", "carpentry", "general")
DASHBOARD_PRIORITIES = ("low", "medium", "high", "emergency")
DASHBOARD_STATUSES = ("new", "assigned", "pending_assignment")


def _build_dashboard_stats():
    tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()

    by_category = {c: 0 for c in DASHBOARD_CATEGORIES}
    by_priority = {p: 0 for p in DASHBOARD_PRIORITIES}
    by_status = {s: 0 for s in DASHBOARD_STATUSES}
    response_times = []

    for ticket in tickets:
        if ticket.category in by_category:
            by_category[ticket.category] += 1
        if ticket.priority in by_priority:
            by_priority[ticket.priority] += 1
        if ticket.status in by_status:
            by_status[ticket.status] += 1
        if ticket.status == "assigned" and ticket.created_at and ticket.updated_at:
            minutes = (ticket.updated_at - ticket.created_at).total_seconds() / 60
            response_times.append(minutes)

    stats = {
        "total_tickets": len(tickets),
        "by_category": by_category,
        "by_priority": by_priority,
        "by_status": by_status,
    }

    if response_times:
        stats["avg_response_time"] = round(sum(response_times) / len(response_times), 1)

    return stats, tickets


@bp.route("/tickets", methods=["POST"])
def create_ticket():
    payload = request.get_json(silent=True) or {}

    title = payload.get("title")
    if not title:
        return jsonify({"error": "'title' is required"}), 400

    description = payload.get("description")
    customer_email = (payload.get("customer_email") or "").strip() or None
    customer_phone = (payload.get("customer_phone") or "").strip() or None
    match_priority = payload.get("match_priority")
    if match_priority not in MATCH_PRIORITIES:
        match_priority = "quality"
    lang = payload.get("lang")
    if lang not in TRANSLATIONS:
        lang = DEFAULT_LANG

    if not customer_email and not customer_phone:
        return jsonify({"error": TRANSLATIONS[lang]["error_contact_required"]}), 400

    photo = payload.get("photo")
    photo_content_type = None
    photo_data = None
    if photo:
        try:
            photo_content_type, photo_data = _parse_photo_data_uri(photo)
        except ValueError as exc:
            return jsonify({"error": TRANSLATIONS[lang][str(exc)]}), 400

    ticket = Ticket(
        title=title,
        description=description,
        status="new",
        customer_email=customer_email,
        customer_phone=customer_phone,
        photo_data=photo_data,
        photo_content_type=photo_content_type,
        lang=lang,
    )
    db.session.add(ticket)
    db.session.commit()

    classification = classify_ticket(description or "", photo_data=photo_data, photo_content_type=photo_content_type)
    categories = classification["categories"]
    ticket.category = classification["category"]
    ticket.priority = classification["priority"]
    ticket.urgency_reason = classification["urgency_reason"]

    team = select_technician_team(ticket, categories, match_priority=match_priority)
    primary_specialty, primary_technician, primary_reasoning = team[0]

    if primary_technician:
        ticket.assigned_to = primary_technician.id
        ticket.assignment_reasoning = primary_reasoning
    else:
        ticket.assigned_to = None
        ticket.assignment_reasoning = None

    ticket.status = "assigned" if any(tech for _, tech, _ in team) else "pending_assignment"

    for specialty, technician, reasoning in team:
        db.session.add(
            TicketAssignment(
                ticket_id=ticket.id,
                technician_id=technician.id if technician else None,
                specialty=specialty,
                reasoning=reasoning,
            )
        )

    db.session.commit()

    if customer_email:
        try:
            send_confirmation_email(ticket, primary_technician, lang=lang)
        except Exception:
            logger.exception(
                "Не вдалося надіслати email підтвердження для заявки #%s", ticket.id
            )

    response = ticket.to_dict(include_assignee=True)
    response["ticket_id"] = ticket.id
    return jsonify(response), 201


@bp.route("/tickets/<int:ticket_id>/confirm", methods=["POST"])
def confirm_ticket(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        return jsonify({"error": "ticket not found"}), 404

    if ticket.status != "confirmed":
        technicians = []
        seen_ids = set()
        for assignment in ticket.assignments:
            if assignment.technician and assignment.technician.id not in seen_ids:
                technicians.append(assignment.technician)
                seen_ids.add(assignment.technician.id)
        if not technicians and ticket.assignee:
            # Legacy tickets created before ticket_assignments existed have
            # no assignment rows - fall back to the single legacy field.
            technicians = [ticket.assignee]

        for technician in technicians:
            try:
                send_technician_notification(ticket, technician)
            except Exception:
                logger.exception(
                    "Не вдалося надіслати email майстру %s для заявки #%s", technician.id, ticket.id
                )
        ticket.status = "confirmed"
        db.session.commit()

    return jsonify(ticket.to_dict(include_assignee=True))


def _find_technician_by_email(email):
    if not email:
        return None
    return Technician.query.filter(db.func.lower(Technician.email) == email.strip().lower()).first()


@bp.route("/technicians", methods=["POST"])
def register_technician():
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()
    specialty = payload.get("specialty")
    price_tier = (payload.get("price_tier") or "").strip() or None
    speed_rating = (payload.get("speed_rating") or "").strip() or None
    lang = payload.get("lang")
    if lang not in TRANSLATIONS:
        lang = DEFAULT_LANG
    t = TRANSLATIONS[lang]

    if not name or not email or not phone or specialty not in SPECIALTIES:
        return jsonify({"error": t["tech_error_required"]}), 400

    if price_tier is not None and price_tier not in PRICE_TIERS:
        return jsonify({"error": t["tech_error_invalid_option"]}), 400

    if speed_rating is not None and speed_rating not in SPEED_RATINGS:
        return jsonify({"error": t["tech_error_invalid_option"]}), 400

    if _find_technician_by_email(email) is not None:
        return jsonify({"error": t["tech_error_email_exists"]}), 409

    technician = Technician(
        name=name,
        email=email,
        phone=phone,
        specialty=specialty,
        price_tier=price_tier,
        speed_rating=speed_rating,
        available=True,
    )
    db.session.add(technician)
    db.session.commit()

    return jsonify(technician.to_dict()), 201


@bp.route("/technician/upload", methods=["GET"])
def technician_upload_form():
    email = (request.args.get("email") or "").strip()
    technician = None
    error = None

    if email:
        technician = _find_technician_by_email(email)
        if technician is None:
            error = "Майстра з таким email не знайдено."

    return render_template(
        "technician_upload.html", email=email, technician=technician, error=error, success=None
    )


@bp.route("/technician/upload", methods=["POST"])
def technician_upload_submit():
    email = (request.form.get("email") or "").strip()
    technician = _find_technician_by_email(email)
    error = None
    success = None

    if not email:
        error = "Вкажіть email."
    elif technician is None:
        error = "Майстра з таким email не знайдено."
    else:
        file = request.files.get("resume")
        if file is None or not file.filename:
            error = "Виберіть файл резюме (PDF або DOCX)."
        elif not allowed_filename(file.filename):
            error = "Підтримуються лише файли у форматі PDF або DOCX."
        else:
            try:
                file_bytes = file.read()
                resume_text = extract_text(file.filename, file_bytes)
                summary = generate_summary(resume_text)
            except ResumeProcessingError as exc:
                error = str(exc)
            except Exception:
                logger.exception("Не вдалося обробити резюме для %s", email)
                error = "Не вдалося згенерувати саммарі. Спробуйте ще раз пізніше."
            else:
                technician.resume_summary = summary
                technician.resume_uploaded_at = datetime.now(timezone.utc)
                db.session.commit()
                success = "Резюме успішно оброблено, саммарі збережено."

    return render_template(
        "technician_upload.html", email=email, technician=technician, error=error, success=success
    )


def _technician_tickets(technician):
    assigned_ticket_ids = db.session.query(TicketAssignment.ticket_id).filter(
        TicketAssignment.technician_id == technician.id
    )
    return (
        Ticket.query.filter(
            db.or_(Ticket.assigned_to == technician.id, Ticket.id.in_(assigned_ticket_ids))
        )
        .order_by(Ticket.created_at.desc())
        .limit(20)
        .all()
    )


@bp.route("/technician/dashboard", methods=["GET"])
def technician_dashboard_view():
    email = (request.args.get("email") or "").strip()
    technician = None
    tickets = []
    error = None

    if email:
        technician = _find_technician_by_email(email)
        if technician is None:
            error = "Майстра з таким email не знайдено."
        else:
            tickets = _technician_tickets(technician)

    return render_template(
        "technician_dashboard.html", email=email, technician=technician, tickets=tickets, error=error
    )


def _ticket_has_technician(ticket, technician):
    if ticket.assigned_to == technician.id:
        return True
    return any(a.technician_id == technician.id for a in ticket.assignments)


@bp.route("/technician/tickets/<int:ticket_id>/complete", methods=["POST"])
def technician_complete_ticket(ticket_id):
    email = (request.form.get("email") or "").strip()
    technician = _find_technician_by_email(email)
    ticket = Ticket.query.get(ticket_id)
    error = None

    if technician is None:
        error = "Майстра з таким email не знайдено."
    elif ticket is None or not _ticket_has_technician(ticket, technician):
        error = "Заявку не знайдено або вона не призначена вам."
    elif ticket.status != "completed":
        ticket.status = "completed"
        ticket.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        if ticket.customer_email:
            try:
                lang = ticket.lang if ticket.lang in TRANSLATIONS else DEFAULT_LANG
                review_link = url_for(
                    "tickets.ticket_review_form", ticket_id=ticket.id, _external=True
                )
                send_completion_email(ticket, review_link, lang=lang)
            except Exception:
                logger.exception(
                    "Не вдалося надіслати email про завершення заявки #%s", ticket.id
                )

    tickets = _technician_tickets(technician) if technician else []
    return render_template(
        "technician_dashboard.html", email=email, technician=technician, tickets=tickets, error=error
    )


@bp.route("/tickets/<int:ticket_id>/review", methods=["GET"])
def ticket_review_form(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        return jsonify({"error": "ticket not found"}), 404

    lang = ticket.lang if ticket.lang in TRANSLATIONS else DEFAULT_LANG
    return render_template(
        "ticket_review.html", ticket=ticket, t=TRANSLATIONS[lang], lang=lang, success=None, error=None
    )


@bp.route("/tickets/<int:ticket_id>/review", methods=["POST"])
def ticket_review_submit(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        return jsonify({"error": "ticket not found"}), 404

    lang = ticket.lang if ticket.lang in TRANSLATIONS else DEFAULT_LANG
    t = TRANSLATIONS[lang]
    error = None
    success = None

    if ticket.status != "completed":
        error = t["review_not_completed_body"]
    else:
        try:
            rating = int(request.form.get("rating"))
            if rating < 1 or rating > 5:
                raise ValueError
        except (TypeError, ValueError):
            error = t["review_error"]
        else:
            ticket.client_rating = rating
            ticket.client_review = (request.form.get("review") or "").strip() or None
            db.session.commit()
            success = t["review_thanks"]

    return render_template(
        "ticket_review.html", ticket=ticket, t=t, lang=lang, success=success, error=error
    )


@bp.route("/dashboard", methods=["GET"])
def dashboard():
    stats, _ = _build_dashboard_stats()
    return jsonify(stats)


@bp.route("/dashboard/view", methods=["GET"])
def dashboard_view():
    stats, tickets = _build_dashboard_stats()
    recent_tickets = [t.to_dict(include_assignee=True, include_photo=True) for t in tickets[:10]]
    technicians = Technician.query.order_by(Technician.name).all()
    completed_tickets = (
        Ticket.query.filter_by(status="completed")
        .order_by(Ticket.completed_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "dashboard.html",
        stats=stats,
        tickets=recent_tickets,
        technicians=technicians,
        completed_tickets=completed_tickets,
    )


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    query = Ticket.query

    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)

    category = request.args.get("category")
    if category:
        query = query.filter_by(category=category)

    priority = request.args.get("priority")
    if priority:
        query = query.filter_by(priority=priority)

    tickets = query.order_by(Ticket.created_at.desc()).all()
    return jsonify([t.to_dict() for t in tickets])


@bp.route("/tickets/<int:ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        return jsonify({"error": "ticket not found"}), 404
    return jsonify(ticket.to_dict(include_assignee=True, include_photo=True))


@bp.route("/tickets/<int:ticket_id>", methods=["PATCH"])
def update_ticket(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        return jsonify({"error": "ticket not found"}), 404

    payload = request.get_json(silent=True) or {}

    if "status" in payload:
        if payload["status"] not in STATUSES:
            return jsonify({"error": f"'status' must be one of {STATUSES}"}), 400
        ticket.status = payload["status"]

    if "assigned_to" in payload:
        assigned_to = payload["assigned_to"]
        if assigned_to is not None:
            technician = Technician.query.get(assigned_to)
            if technician is None:
                return jsonify({"error": f"technician {assigned_to} not found"}), 400
        ticket.assigned_to = assigned_to

    db.session.commit()
    return jsonify(ticket.to_dict(include_assignee=True))
