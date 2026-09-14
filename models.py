from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

SPECIALTIES = ("plumbing", "electrical", "carpentry", "general")
CATEGORIES = ("plumbing", "electrical", "carpentry", "general", "other")
PRIORITIES = ("low", "medium", "high", "emergency")
STATUSES = ("new", "pending_assignment", "assigned", "confirmed", "completed", "in_progress", "resolved", "closed")
PRICE_TIERS = ("budget", "mid", "premium")
SPEED_RATINGS = ("fast", "medium", "slow")


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

    tickets = db.relationship("Ticket", back_populates="assignee")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "specialty": self.specialty,
            "available": self.available,
            "price_tier": self.price_tier,
            "speed_rating": self.speed_rating,
        }


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=True)
    priority = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="new")
    customer_email = db.Column(db.String(255), nullable=True)
    customer_phone = db.Column(db.String(30), nullable=True)
    urgency_reason = db.Column(db.Text, nullable=True)
    lang = db.Column(db.String(5), nullable=True, default="uk")
    assigned_to = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    client_rating = db.Column(db.Integer, nullable=True)
    client_review = db.Column(db.Text, nullable=True)
    assignment_reasoning = db.Column(db.Text, nullable=True)

    assignee = db.relationship("Technician", back_populates="tickets")

    def to_dict(self, include_assignee=False):
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
            "assigned_to": self.assigned_to,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "client_rating": self.client_rating,
            "client_review": self.client_review,
            "assignment_reasoning": self.assignment_reasoning,
        }
        if include_assignee:
            data["assignee"] = self.assignee.to_dict() if self.assignee else None
        return data
