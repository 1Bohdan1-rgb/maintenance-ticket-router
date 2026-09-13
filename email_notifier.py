import os
import smtplib
from email.message import EmailMessage


def send_confirmation_email(ticket, technician=None):
    """Send a ticket confirmation email to the customer.

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

    lines = [
        f'Вашу заявку "{ticket.title}" прийнято в обробку.',
        f"Категорія: {ticket.category or '—'}",
        f"Пріоритет: {ticket.priority or '—'}",
    ]
    if technician:
        lines.append(f"Призначений майстер: {technician.name}")
    else:
        lines.append("Майстра буде призначено найближчим часом.")

    message = EmailMessage()
    message["Subject"] = f"Заявку №{ticket.id} прийнято: {ticket.title}"
    message["From"] = smtp_user
    message["To"] = ticket.customer_email
    message.set_content("\n".join(lines))

    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)
