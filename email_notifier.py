import os
import smtplib
from email.message import EmailMessage

from translations import get_translation


def send_confirmation_email(ticket, technician=None, lang="uk"):
    """Send a ticket confirmation email to the customer in the given language.

    Raises on missing SMTP configuration or any send failure - callers are
    expected to catch and log, since a failed email must not block ticket
    creation.
    """
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
        raise RuntimeError(
            "SMTP is not configured (SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD)"
        )

    t = get_translation(lang)["email"]
    ui = get_translation(lang)
    category_name = ui["category_names"].get(ticket.category, ticket.category or "—")
    priority_name = ui["priority_names"].get(ticket.priority, ticket.priority or "—")

    lines = [
        t["intro"].format(title=ticket.title),
        t["category_line"].format(category=category_name),
        t["priority_line"].format(priority=priority_name),
    ]
    if technician:
        lines.append(t["assigned_line"].format(technician=technician.name))
    else:
        lines.append(t["pending_line"])

    message = EmailMessage()
    message["Subject"] = t["subject"].format(id=ticket.id, title=ticket.title)
    message["From"] = smtp_user
    message["To"] = ticket.customer_email
    message.set_content("\n".join(lines))

    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def send_completion_email(ticket, review_link, lang="uk"):
    """Notify the customer that their ticket was completed, with a link to
    leave a review.

    Raises on missing SMTP configuration, a ticket without a customer email,
    or any send failure - callers are expected to catch and log, since a
    failed email must not block marking the ticket completed.
    """
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
        raise RuntimeError(
            "SMTP is not configured (SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD)"
        )

    if not ticket.customer_email:
        raise RuntimeError("Ticket has no customer email")

    t = get_translation(lang)["email"]

    lines = [
        t["completed_intro"].format(title=ticket.title),
        t["completed_review_prompt"].format(link=review_link),
    ]

    message = EmailMessage()
    message["Subject"] = t["completed_subject"].format(id=ticket.id, title=ticket.title)
    message["From"] = smtp_user
    message["To"] = ticket.customer_email
    message.set_content("\n".join(lines))

    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def send_technician_notification(ticket, technician):
    """Notify the assigned technician that a customer confirmed a ticket.

    Raises on missing SMTP configuration, a technician without an email, or
    any send failure - callers are expected to catch and log, since a failed
    email must not block the confirmation itself.
    """
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
        raise RuntimeError(
            "SMTP is not configured (SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD)"
        )

    if not technician or not technician.email:
        raise RuntimeError("Assigned technician has no email address")

    ui = get_translation("uk")
    category_name = ui["category_names"].get(ticket.category, ticket.category or "—")
    priority_name = ui["priority_names"].get(ticket.priority, ticket.priority or "—")
    customer_contact = ticket.customer_email or ticket.customer_phone or "клієнт не залишив контакт"

    lines = [
        f"Опис проблеми: {ticket.description or '—'}",
        f"Пріоритет: {priority_name}",
        f"Обґрунтування: {ticket.urgency_reason or '—'}",
        f"Контакт клієнта: {customer_contact}",
    ]

    message = EmailMessage()
    message["Subject"] = f"Нова заявка #{ticket.id}: {category_name}"
    message["From"] = smtp_user
    message["To"] = technician.email
    message.set_content("\n".join(lines))

    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)
