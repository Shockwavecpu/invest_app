from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# ---------------- User ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    earnings = db.Column(db.Float, default=0.0)
    wallet_number = db.Column(db.String(50), nullable=True)

    # Cascade deletes for related tables
    purchases = db.relationship("Purchase", backref="user", cascade="all, delete-orphan")
    withdrawals = db.relationship("Withdrawal", backref="user", cascade="all, delete-orphan")
    recharges = db.relationship("Recharge", backref="user", cascade="all, delete-orphan")


# ---------------- Product ----------------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=False)
    daily_earning = db.Column(db.Float, nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)

    purchases = db.relationship("Purchase", backref="product", cascade="all, delete-orphan")


# ---------------- Purchase ----------------
class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)
    next_payout_date = db.Column(db.Date, nullable=True)
    remaining_days = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, default=True)


# ---------------- Recharge ----------------
class Recharge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="Pending")  # Pending, Approved, Rejected


# ---------------- Withdrawal ----------------
class Withdrawal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="Pending")  # Pending, Approved, Rejected


# ---------------- Settings ----------------
class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)
