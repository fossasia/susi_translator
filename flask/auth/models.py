from __future__ import annotations
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Organizer(db.Model):
    __tablename__ = "organizers"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<Organizer {self.email}>"

class TokenBlocklist(db.Model):
    __tablename__ = "token_blocklist"
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)

class Room(db.Model):
    __tablename__ = "rooms"
    
    tenant_id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizers.id'), nullable=False)
    source = db.Column(db.String(50), nullable=True)
    stream_type = db.Column(db.String(50), nullable=True)
    stream_url = db.Column(db.Text, nullable=True)
    configured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())