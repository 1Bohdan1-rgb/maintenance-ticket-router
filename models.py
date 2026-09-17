from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

SPECIALTIES = ("plumbing", "electrical", "carpentry", "general")
CATEGORIES = ("plumbing", "electrical", "carpentry", "general", "other")
PRIORITIES = ("low", "medium", "high", "emergency")
STATUSES = (
    "new",
    "pending_assignment",
    "assigned",
    "pending_technician_response",
    "confirmed",
    "completed",
    "in_progress",
    "resolved",
    "closed",
)
PRICE_TIERS = ("budget", "mid", "premium")
SPEED_RATINGS = ("fast", "medium", "slow")
MATCH_PRIORITIES = ("quality", "speed", "price")
ALLOWED_PHOTO_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB, pre-base64 (decoded) size
GENDERS = ("male", "female")


def _utcnow():
    return datetime.now(timezone.utc)


class Technician(db.Model):
    __tablename__ = "technicians"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    specialty = db.Column(db.String(50), nullable=False)
    available = db.Column(db.Boolean, nullable=False, default=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    resume_summary = db.Column(db.Text, nullable=True)
    resume_uploaded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    price_tier = db.Column(db.String(20), nullable=True)
    speed_rating = db.Column(db.String(20), nullable=True)
    gender = db.Column(db.String(20), nullable=True)

    tickets = db.relationship("Ticket", back_populates="assignee")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "specialty": self.specialty,
            "available": self.available,
            "price_tier": self.price_tier,
            "speed_rating": self.speed_rating,
            "gender": self.gender,
        }


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=True)
    priority = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="new")
    customer_email = db.Column(db.String(255), nullable=True)
    customer_phone = db.Column(db.String(30), nullable=True)
    urgency_reason = db.Column(db.Text, nullable=True)
    severity = db.Column(db.Integer, nullable=True)
    severity_reason = db.Column(db.Text, nullable=True)
    lang = db.Column(db.String(5), nullable=True, default="uk")
    match_priority = db.Column(db.String(20), nullable=True)
    preferred_gender = db.Column(db.String(20), nullable=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    client_rating = db.Column(db.Integer, nullable=True)
    client_review = db.Column(db.Text, nullable=True)
    assignment_reasoning = db.Column(db.Text, nullable=True)
    photo_data = db.Column(db.Text, nullable=True)
    photo_content_type = db.Column(db.String(50), nullable=True)

    assignee = db.relationship("Technician", back_populates="tickets")
    assignments = db.relationship(
        "TicketAssignment",
        back_populates="ticket",
        order_by="TicketAssignment.id",
        cascade="all, delete-orphan",
    )

    def to_dict(self, include_assignee=False, include_photo=False):
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "customer_email": self.customer_email,
            "customer_phone": self.customer_phone,
            "urgency_reason": self.urgency_reason,
            "severity": self.severity,
            "severity_reason": self.severity_reason,
            "match_priority": self.match_priority,
            "preferred_gender": self.preferred_gender,
            "assigned_to": self.assigned_to,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "client_rating": self.client_rating,
            "client_review": self.client_review,
            "assignment_reasoning": self.assignment_reasoning,
            "has_photo": bool(self.photo_data),
        }
        if include_assignee:
            data["assignee"] = self.assignee.to_dict() if self.assignee else None
            data["assignments"] = [a.to_dict() for a in self.assignments]
        if include_photo:
            data["photo_data"] = self.photo_data
            data["photo_content_type"] = self.photo_content_type
        return data


class TicketAssignment(db.Model):
    """One technician assigned to a ticket for one required specialty.

    A single-specialty ticket gets exactly one row here (mirroring
    Ticket.assigned_to/assignment_reasoning, kept in sync with the first
    entry for backward compatibility). A multi-discipline ticket
    ("the ceiling collapsed" -> carpentry + electrical + plumbing) gets one
    row per specialty, each independently matched. `technician_id` is NULL
    when no available technician could be found for that specialty.

    `response_status` tracks whether the assigned technician has responded
    to the ticket once the customer confirms it (see Ticket.status ==
    "pending_technician_response"): None before that point (or for a row
    with no technician), "pending" while awaiting their response,
    "accepted", or transiently "declined" right before the row is either
    reassigned to a new candidate (back to "pending") or left as a gap
    (technician_id reset to NULL) if none is available.

    `decline_count` is a running total of how many times *this slot* has
    been declined - unlike response_status (which a successful reassignment
    overwrites back to "pending", losing the fact that a decline ever
    happened), this persists across reassignment so analytics can compute
    an accurate decline rate instead of only ever seeing declines that
    happened to end in an unfilled gap.
    """

    __tablename__ = "ticket_assignments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    technician_id = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=True)
    specialty = db.Column(db.String(50), nullable=False)
    reasoning = db.Column(db.Text, nullable=True)
    response_status = db.Column(db.String(20), nullable=True)
    decline_count = db.Column(db.Integer, nullable=False, default=0)

    ticket = db.relationship("Ticket", back_populates="assignments")
    technician = db.relationship("Technician")

    def to_dict(self):
        return {
            "specialty": self.specialty,
            "technician": self.technician.to_dict() if self.technician else None,
            "reasoning": self.reasoning,
            "response_status": self.response_status,
            "decline_count": self.decline_count,
        }
