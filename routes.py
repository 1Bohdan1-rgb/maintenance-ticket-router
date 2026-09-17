import base64
import binascii
import functools
import hmac
import logging
import os
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
    GENDERS,
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
from technician_assignment import select_technician, select_technician_team
from translations import TRANSLATIONS, DEFAULT_LANG

logger = logging.getLogger(__name__)

bp = Blueprint("tickets", __name__)


def _admin_token_matches(provided):
    # Read at request time (not import time) - routes.py is imported before
    # app.py calls load_dotenv(), so a module-level os.environ.get() here
    # would always see an unset ADMIN_TOKEN in local dev.
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        return False
    return hmac.compare_digest(provided or "", token)


def require_admin_token(view):
    """Require a matching X-Admin-Token header - for JSON API endpoints
    that mutate or delete data. Fails closed: refuses every request
    (including with the right token) if ADMIN_TOKEN isn't configured on
    the server, rather than silently leaving the endpoint open.
    """

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not _admin_token_matches(request.headers.get("X-Admin-Token")):
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapped


def require_admin_basic(view):
    """Require HTTP Basic Auth (any username, ADMIN_TOKEN as the password)
    - for browser-viewed pages like the business dashboard, so opening the
    URL prompts the browser's native login dialog instead of needing a
    custom header a browser can't send on its own.
    """

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not _admin_token_matches(auth.password):
            response = jsonify({"error": "unauthorized"})
            response.status_code = 401
            response.headers["WWW-Authenticate"] = 'Basic realm="Dashboard"'
            return response
        return view(*args, **kwargs)

    return wrapped

_PHOTO_DATA_URI_RE = re.compile(r"^data:(image/[\w+.-]+);base64,(.+)$", re.DOTALL)

# Pragmatic, not RFC-5322-exact - good enough to reject obvious typos
# ("bob@", "bob@site") without rejecting real addresses.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Allows an optional leading "+", then digits/spaces/dashes/dots/parens for
# formatting - actual validity is the digit count check below (E.164 caps
# a real phone number at 15 digits; 7 is a reasonable practical minimum).
_PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,25}$")


def _is_valid_email(value):
    return bool(_EMAIL_RE.match(value))


def _is_valid_phone(value):
    if not _PHONE_RE.match(value):
        return False
    digit_count = sum(ch.isdigit() for ch in value)
    return 7 <= digit_count <= 15


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
DASHBOARD_STATUSES = ("new", "assigned", "pending_assignment", "pending_technician_response")


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
    preferred_gender = payload.get("preferred_gender")
    if preferred_gender not in GENDERS:
        preferred_gender = None
    lang = payload.get("lang")
    if lang not in TRANSLATIONS:
        lang = DEFAULT_LANG

    if not customer_email and not customer_phone:
        return jsonify({"error": TRANSLATIONS[lang]["error_contact_required"]}), 400

    if customer_email and not _is_valid_email(customer_email):
        return jsonify({"error": TRANSLATIONS[lang]["error_email_invalid"]}), 400

    if customer_phone and not _is_valid_phone(customer_phone):
        return jsonify({"error": TRANSLATIONS[lang]["error_phone_invalid"]}), 400

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
        match_priority=match_priority,
        preferred_gender=preferred_gender,
    )
    db.session.add(ticket)
    db.session.commit()

    classification = classify_ticket(description or "", photo_data=photo_data, photo_content_type=photo_content_type)
    categories = classification["categories"]
    ticket.category = classification["category"]
    ticket.priority = classification["priority"]
    ticket.urgency_reason = classification["urgency_reason"]
    ticket.severity = classification["severity"]
    ticket.severity_reason = classification["severity_reason"]

    team = select_technician_team(
        ticket, categories, match_priority=match_priority, preferred_gender=preferred_gender
    )
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

    if ticket.status not in ("pending_technician_response", "confirmed"):
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

        if technicians:
            # Wait for each notified technician to accept/decline (see
            # technician_respond_ticket) before treating the ticket as
            # truly confirmed - only assignment rows with a technician are
            # marked "pending"; an unfilled specialty stays untouched.
            for assignment in ticket.assignments:
                if assignment.technician_id is not None:
                    assignment.response_status = "pending"
            ticket.status = "pending_technician_response"
        else:
            # Nothing to wait for - matches the pre-existing behavior for
            # an entirely unassigned ticket.
            ticket.status = "confirmed"
        db.session.commit()

    return jsonify(ticket.to_dict(include_assignee=True))


@bp.route("/tickets/<int:ticket_id>", methods=["DELETE"])
@require_admin_token
def delete_ticket(ticket_id):
    """Remove a ticket (e.g. test/junk data) and its assignment rows -
    Ticket.assignments cascades on delete, so no manual cleanup needed.
    """
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        return jsonify({"error": "ticket not found"}), 404

    db.session.delete(ticket)
    db.session.commit()

    return "", 204


@bp.route("/admin/reassign-pending", methods=["POST"])
@require_admin_token
def reassign_pending():
    """Retry technician matching for ticket_assignments rows still missing
    a technician.

    Assignment only ever runs once, at ticket creation - if no technician
    was available/registered for a specialty yet at that moment, the gap
    (e.g. "carpentry: -") stays forever, even after a matching technician
    later becomes available. This re-runs select_technician() for each open
    gap and fills in whatever now matches, catching up tickets that were
    confirmed - and whose technician therefore never got notified - before
    the gap was fixed. Reuses the ticket's own saved match_priority/
    preferred_gender (defaulting to "quality"/None for older tickets
    created before those columns existed) instead of silently ignoring
    what the client originally asked for.
    """
    open_assignments = TicketAssignment.query.filter(TicketAssignment.technician_id.is_(None)).all()

    reassigned = []
    for assignment in open_assignments:
        ticket = assignment.ticket
        technician, reasoning = select_technician(
            ticket,
            match_priority=ticket.match_priority or "quality",
            specialty=assignment.specialty,
            preferred_gender=ticket.preferred_gender,
        )
        if technician is None:
            continue

        assignment.technician_id = technician.id
        assignment.reasoning = reasoning

        if ticket.assignments and ticket.assignments[0].id == assignment.id and ticket.assigned_to is None:
            ticket.assigned_to = technician.id
            ticket.assignment_reasoning = reasoning

        if ticket.status == "pending_assignment":
            ticket.status = "assigned"
        elif ticket.status in ("confirmed", "completed", "in_progress", "resolved", "closed"):
            try:
                send_technician_notification(ticket, technician)
            except Exception:
                logger.exception(
                    "Не вдалося надіслати email майстру %s для заявки #%s", technician.id, ticket.id
                )

        reassigned.append({"ticket_id": ticket.id, "specialty": assignment.specialty, "technician": technician.name})

    db.session.commit()

    return jsonify({"reassigned": reassigned, "remaining_gaps": len(open_assignments) - len(reassigned)})


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
    gender = (payload.get("gender") or "").strip() or None
    lang = payload.get("lang")
    if lang not in TRANSLATIONS:
        lang = DEFAULT_LANG
    t = TRANSLATIONS[lang]

    if not name or not email or not phone or specialty not in SPECIALTIES:
        return jsonify({"error": t["tech_error_required"]}), 400

    if not _is_valid_email(email):
        return jsonify({"error": t["tech_error_email_invalid"]}), 400

    if not _is_valid_phone(phone):
        return jsonify({"error": t["tech_error_phone_invalid"]}), 400

    if price_tier is not None and price_tier not in PRICE_TIERS:
        return jsonify({"error": t["tech_error_invalid_option"]}), 400

    if speed_rating is not None and speed_rating not in SPEED_RATINGS:
        return jsonify({"error": t["tech_error_invalid_option"]}), 400

    if gender is not None and gender not in GENDERS:
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
        gender=gender,
        available=True,
    )
    db.session.add(technician)
    db.session.commit()

    return jsonify(technician.to_dict()), 201


@bp.route("/technicians/<int:technician_id>/availability", methods=["PATCH"])
@require_admin_token
def set_technician_availability(technician_id):
    """Toggle a technician in/out of the assignment pool without deleting
    them (e.g. taking test/seed data back out of live routing, or a
    technician going on leave) - there's no technician-delete endpoint, so
    this is the only way to stop one from being matched to new tickets.
    """
    technician = Technician.query.get(technician_id)
    if technician is None:
        return jsonify({"error": "technician not found"}), 404

    payload = request.get_json(silent=True) or {}
    if "available" not in payload or not isinstance(payload["available"], bool):
        return jsonify({"error": "'available' (boolean) is required"}), 400

    technician.available = payload["available"]
    db.session.commit()

    return jsonify(technician.to_dict())


@bp.route("/technicians/<int:technician_id>", methods=["DELETE"])
@require_admin_token
def delete_technician(technician_id):
    """Remove a technician (e.g. test/junk data) - refuses if they're
    referenced by any ticket/assignment, since unlike a ticket a technician
    can be historical data other rows depend on; deactivate via the
    availability endpoint instead for anyone with real ticket history.
    """
    technician = Technician.query.get(technician_id)
    if technician is None:
        return jsonify({"error": "technician not found"}), 404

    has_history = (
        Ticket.query.filter_by(assigned_to=technician_id).first() is not None
        or TicketAssignment.query.filter_by(technician_id=technician_id).first() is not None
    )
    if has_history:
        return jsonify({"error": "technician has ticket history; use the availability endpoint instead"}), 409

    db.session.delete(technician)
    db.session.commit()

    return "", 204


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
    tickets = (
        Ticket.query.filter(
            db.or_(Ticket.assigned_to == technician.id, Ticket.id.in_(assigned_ticket_ids))
        )
        .order_by(Ticket.created_at.desc())
        .limit(20)
        .all()
    )
    # Not persisted - just lets the template know, per ticket, whether
    # *this* technician's own assignment row is still awaiting their
    # accept/decline response.
    for ticket in tickets:
        my_assignment = next((a for a in ticket.assignments if a.technician_id == technician.id), None)
        ticket.my_response_status = my_assignment.response_status if my_assignment else None
    return tickets


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
    elif ticket.status == "pending_technician_response":
        error = "Спершу прийміть заявку, перш ніж позначати її виконаною."
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


def _maybe_confirm_ticket(ticket):
    """Flips a ticket from pending_technician_response to confirmed once
    every assignment row that currently has a technician has accepted - a
    specialty with no technician at all (a gap) doesn't block this, same
    as it doesn't block the initial "assigned" status at creation time.
    """
    if ticket.status != "pending_technician_response":
        return
    still_waiting = any(
        a.technician_id is not None and a.response_status != "accepted" for a in ticket.assignments
    )
    if not still_waiting:
        ticket.status = "confirmed"


def _decline_and_reassign(ticket, assignment, declining_technician):
    """Handles one technician declining their assignment: reopens that
    specialty's slot and immediately retries select_technician(), excluding
    the technician who just declined so they can't be handed the same
    ticket right back. Mirrors /admin/reassign-pending's fill-a-gap logic,
    but for a slot that had a technician who said no rather than one that
    started out empty.
    """
    assignment.response_status = "declined"
    assignment.technician_id = None

    new_technician, reasoning = select_technician(
        ticket,
        match_priority=ticket.match_priority or "quality",
        specialty=assignment.specialty,
        preferred_gender=ticket.preferred_gender,
        exclude_ids={declining_technician.id},
    )

    was_primary = ticket.assigned_to == declining_technician.id

    if new_technician is None:
        if was_primary:
            ticket.assigned_to = None
            ticket.assignment_reasoning = None
        if not any(a.technician_id for a in ticket.assignments):
            ticket.status = "pending_assignment"
        return

    assignment.technician_id = new_technician.id
    assignment.reasoning = reasoning
    assignment.response_status = "pending"

    if was_primary:
        ticket.assigned_to = new_technician.id
        ticket.assignment_reasoning = reasoning

    try:
        send_technician_notification(ticket, new_technician)
    except Exception:
        logger.exception(
            "Не вдалося надіслати email майстру %s для заявки #%s", new_technician.id, ticket.id
        )


@bp.route("/technician/tickets/<int:ticket_id>/respond", methods=["POST"])
def technician_respond_ticket(ticket_id):
    """A technician accepts or declines a ticket they were assigned, once
    the customer has confirmed it (ticket.status ==
    "pending_technician_response"). Declining immediately retries
    assignment for that specialty via _decline_and_reassign, so the ticket
    moves on to the next candidate instead of just sitting there.
    """
    email = (request.form.get("email") or "").strip()
    response = (request.form.get("response") or "").strip()
    technician = _find_technician_by_email(email)
    ticket = Ticket.query.get(ticket_id)
    error = None

    if technician is None:
        error = "Майстра з таким email не знайдено."
    elif ticket is None:
        error = "Заявку не знайдено."
    elif response not in ("accept", "decline"):
        error = "Некоректна відповідь."
    else:
        my_pending = [
            a for a in ticket.assignments
            if a.technician_id == technician.id and a.response_status == "pending"
        ]
        if not my_pending:
            error = "Ця заявка не очікує на вашу відповідь."
        elif response == "accept":
            for assignment in my_pending:
                assignment.response_status = "accepted"
            _maybe_confirm_ticket(ticket)
            db.session.commit()
        else:
            for assignment in my_pending:
                _decline_and_reassign(ticket, assignment, technician)
            db.session.commit()

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
@require_admin_basic
def dashboard():
    stats, _ = _build_dashboard_stats()
    return jsonify(stats)


@bp.route("/dashboard/view", methods=["GET"])
@require_admin_basic
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
@require_admin_token
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
