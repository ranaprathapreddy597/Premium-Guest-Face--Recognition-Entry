from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100)) # Added for notification system
    tier = db.Column(db.String(20), nullable=False, default="GUEST")
    airline = db.Column(db.String(50))
    ff_number = db.Column(db.String(50))
    pref_drink = db.Column(db.String(50))
    pref_seat = db.Column(db.String(50))
    avatar_color = db.Column(db.String(10))
    avatar_initials = db.Column(db.String(2))
    
    # Biometric Data
    embedding_json = db.Column(db.Text) # Store as JSON array string
    has_biometrics = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="PENDING") # PENDING, APPROVED, REVOKED
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "tier": self.tier,
            "airline": self.airline,
            "ff": self.ff_number,
            "preferences": {
                "drink": self.pref_drink,
                "seat": self.pref_seat
            },
            "avatar": self.avatar_initials,
            "avatar_color": self.avatar_color,
            "status": self.status,
            "has_biometrics": self.has_biometrics,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }

class AccessLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(100), nullable=True)
    event_type = db.Column(db.String(20)) # GRANTED, DENIED, SPOOF_DETECTED, ENROLLED
    confidence = db.Column(db.Float)
    emotion = db.Column(db.String(20))
    device = db.Column(db.String(50), default="KIOSK_50")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "member_name": self.user_name,
            "event_type": self.event_type,
            "confidence": round(self.confidence * 100, 1) if self.confidence else 0,
            "emotion": self.emotion,
            "timestamp_display": self.timestamp.strftime("%H:%M:%S") if self.timestamp else None,
            "date_display": self.timestamp.strftime("%Y-%m-%d") if self.timestamp else None
        }
