import base64
import html as html_lib
import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from translations import get_translation

_PRIORITY_COLORS = {
    "low": "#5b7b4b",
    "medium": "#c99a3b",
    "high": "#c1652f",
    "emergency": "#a63d2f",
}
_SEVERITY_COLORS = {1: "#5b7b4b", 2: "#5b7b4b", 3: "#c99a3b", 4: "#c1652f", 5: "#a63d2f"}


def _esc(value):
    return html_lib.escape(str(value)) if value else ""


def _build_technician_notification_html(
    ticket, category_name, priority_name, customer_contact, photo_cid=None
):
    """Inline-styled HTML body for the technician assignment email - plain
    tables/inline CSS only, since email clients don't load stylesheets and
    strip <style> blocks inconsistently. Colors match the app's own palette
    (technician_dashboard.html's --accent/--text-muted/etc.) for a
    consistent look across the product.
    """
    priority_color = _PRIORITY_COLORS.get(ticket.priority, "#8a7761")

    severity_rows = ""
    if ticket.severity:
        severity_color = _SEVERITY_COLORS.get(ticket.severity, "#8a7761")
        severity_rows = f"""
          <tr>
            <td style="padding:6px 0; color:#8a7761; font-size:13px;">Серйозність</td>
            <td style="padding:6px 0; text-align:right;">
              <span style="background:{severity_color}; color:#fff8f0; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:700;">{ticket.severity}/5</span>
            </td>
          </tr>"""
        if ticket.severity_reason:
            severity_rows += f"""
          <tr>
            <td colspan="2" style="padding:0 0 6px; color:#8a7761; font-size:12px; font-style:italic;">{_esc(ticket.severity_reason)}</td>
          </tr>"""

    photo_row = ""
    if photo_cid:
        photo_row = f"""
          <tr>
            <td colspan="2" style="padding:14px 0 0;">
              <img src="cid:{photo_cid}" alt="Фото проблеми" width="504" style="max-width:100%; border-radius:8px; display:block; border:1px solid #e8dcc8;">
            </td>
          </tr>"""

    return f"""\
<!doctype html>
<html>
<body style="margin:0; padding:24px; background:#ede3d3; font-family:system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif; color:#3a2e26;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px; width:100%; background:#fffdf9; border:1px solid #e8dcc8; border-radius:14px; overflow:hidden;">
          <tr>
            <td style="background:#c1652f; padding:20px 28px;">
              <span style="color:#fff8f0; font-size:18px; font-weight:700;">Нова заявка №{ticket.id}</span>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 28px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
                <tr>
                  <td style="padding:6px 0; color:#8a7761; font-size:13px;">Категорія</td>
                  <td style="padding:6px 0; text-align:right; font-weight:600;">{_esc(category_name)}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0; color:#8a7761; font-size:13px;">Пріоритет</td>
                  <td style="padding:6px 0; text-align:right;">
                    <span style="background:{priority_color}; color:#fff8f0; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:700; text-transform:uppercase;">{_esc(priority_name)}</span>
                  </td>
                </tr>
                {severity_rows}
                <tr><td colspan="2" style="padding-top:14px; border-top:1px solid #e8dcc8;"></td></tr>
                <tr>
                  <td colspan="2" style="padding:14px 0 4px; color:#8a7761; font-size:13px;">Опис проблеми</td>
                </tr>
                <tr>
                  <td colspan="2" style="padding:0; font-size:14px; line-height:1.5;">{_esc(ticket.description) or "—"}</td>
                </tr>
                {photo_row}
                <tr><td colspan="2" style="padding-top:14px; border-top:1px solid #e8dcc8;"></td></tr>
                <tr>
                  <td colspan="2" style="padding:14px 0 4px; color:#8a7761; font-size:13px;">Обґрунтування пріоритету</td>
                </tr>
                <tr>
                  <td colspan="2" style="padding:0 0 14px; font-size:13px; font-style:italic; color:#5c4d3e;">{_esc(ticket.urgency_reason) or "—"}</td>
                </tr>
                <tr>
                  <td colspan="2" style="padding:14px 16px; background:#faf5eb; border-radius:10px; font-size:13px;">
                    <strong>Контакт клієнта:</strong> {_esc(customer_contact)}
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


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


def _build_technician_notification_message(ticket, technician, smtp_user):
    """Builds the (unsent) assignment notification EmailMessage - split out
    from send_technician_notification so tests can inspect its plain/HTML
    bodies and inline photo without needing real SMTP credentials.
    """
    ui = get_translation("uk")
    category_name = ui["category_names"].get(ticket.category, ticket.category or "—")
    priority_name = ui["priority_names"].get(ticket.priority, ticket.priority or "—")
    customer_contact = ticket.customer_email or ticket.customer_phone or "клієнт не залишив контакт"

    plain_lines = [
        f"Опис проблеми: {ticket.description or '—'}",
        f"Категорія: {category_name}",
        f"Пріоритет: {priority_name}",
    ]
    if ticket.severity:
        severity_line = f"Серйозність: {ticket.severity}/5"
        if ticket.severity_reason:
            severity_line += f" ({ticket.severity_reason})"
        plain_lines.append(severity_line)
    plain_lines.append(f"Обґрунтування: {ticket.urgency_reason or '—'}")
    plain_lines.append(f"Контакт клієнта: {customer_contact}")
    if ticket.photo_data:
        plain_lines.append("(До заявки додано фото - див. HTML-версію листа.)")

    message = EmailMessage()
    message["Subject"] = f"Нова заявка #{ticket.id}: {category_name}"
    message["From"] = smtp_user
    message["To"] = technician.email
    message.set_content("\n".join(plain_lines))

    photo_cid = None
    if ticket.photo_data and ticket.photo_content_type:
        cid = make_msgid(domain="maintenance-ticket-router.local")
        photo_cid = cid[1:-1]  # strip <> for the "cid:" URL used in the HTML

    html_body = _build_technician_notification_html(
        ticket, category_name, priority_name, customer_contact, photo_cid=photo_cid
    )
    message.add_alternative(html_body, subtype="html")

    if photo_cid:
        html_part = message.get_payload()[-1]
        subtype = ticket.photo_content_type.split("/", 1)[-1]
        photo_bytes = base64.b64decode(ticket.photo_data)
        html_part.add_related(photo_bytes, maintype="image", subtype=subtype, cid=f"<{photo_cid}>")

    return message


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

    message = _build_technician_notification_message(ticket, technician, smtp_user)

    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)
