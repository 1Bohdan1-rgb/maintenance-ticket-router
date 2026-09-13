import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, url_for

from ai_classifier import classify_ticket
from email_notifier import (
    send_completion_email,
    send_confirmation_email,
    send_technician_notification,
)
from models import STATUSES, Technician, Ticket, db
from resume_processor import ResumeProcessingError, allowed_filename, extract_text, generate_summary
from translations import TRANSLATIONS, DEFAULT_LANG

logger = logging.getLogger(__name__)

bp = Blueprint("tickets", __name__)

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
    customer_email = payload.get("customer_email")
    lang = payload.get("lang")
    if lang not in TRANSLATIONS:
        lang = DEFAULT_LANG

    ticket = Ticket(
        title=title,
        description=description,
        status="new",
        customer_email=customer_email,
        lang=lang,
    )
    db.session.add(ticket)
    db.session.commit()

    classification = classify_ticket(description or "")
    ticket.category = classification["category"]
    ticket.priority = classification["priority"]
    ticket.urgency_reason = classification["urgency_reason"]

    technician = Technician.query.filter_by(
        specialty=ticket.category, available=True
    ).first()

    if technician:
        ticket.assigned_to = technician.id
        ticket.status = "assigned"
    else:
        ticket.assigned_to = None
        ticket.status = "pending_assignment"

    db.session.commit()

    if customer_email:
        try:
            send_confirmation_email(ticket, technician, lang=lang)
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
        technician = ticket.assignee
        if technician:
            try:
                send_technician_notification(ticket, technician)
            except Exception:
                logger.exception(
                    "Не вдалося надіслати email майстру для заявки #%s", ticket.id
                )
        ticket.status = "confirmed"
        db.session.commit()

    return jsonify(ticket.to_dict(include_assignee=True))


def _find_technician_by_email(email):
    if not email:
        return None
    return Technician.query.filter(db.func.lower(Technician.email) == email.strip().lower()).first()


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
    return (
        Ticket.query.filter_by(assigned_to=technician.id)
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


@bp.route("/technician/tickets/<int:ticket_id>/complete", methods=["POST"])
def technician_complete_ticket(ticket_id):
    email = (request.form.get("email") or "").strip()
    technician = _find_technician_by_email(email)
    ticket = Ticket.query.get(ticket_id)
    error = None

    if technician is None:
        error = "Майстра з таким email не знайдено."
    elif ticket is None or ticket.assigned_to != technician.id:
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
    recent_tickets = [t.to_dict(include_assignee=True) for t in tickets[:10]]
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
    return jsonify(ticket.to_dict(include_assignee=True))


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
