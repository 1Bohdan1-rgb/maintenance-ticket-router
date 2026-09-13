from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

SPECIALTIES = ("plumbing", "electrical", "carpentry", "general")
CATEGORIES = ("plumbing", "electrical", "carpentry", "general", "other")
PRIORITIES = ("low", "medium", "high", "emergency")
STATUSES = ("new", "pending_assignment", "assigned", "in_progress", "resolved", "closed")


def _utcnow():
    return datetime.now(timezone.utc)


class Technician(db.Model):
    __tablename__ = "technicians"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    specialty = db.Column(db.String(50), nullable=False)
    available = db.Column(db.Boolean, nullable=False, default=True)

    tickets = db.relationship("Ticket", back_populates="assignee")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "specialty": self.specialty,
            "available": self.available,
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
    assigned_to = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

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
            "assigned_to": self.assigned_to,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_assignee:
            data["assignee"] = self.assignee.to_dict() if self.assignee else None
        return data
