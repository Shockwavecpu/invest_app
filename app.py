from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify
from flask_bcrypt import Bcrypt
from models import db, User, Recharge, Withdrawal, Product, Purchase, Setting
from datetime import datetime, date, timedelta, timezone
import os, random

app = Flask(__name__)
app.secret_key = "mysecretkey123"
bcrypt = Bcrypt(app)

# ------------------- Database Config -------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_FILE}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# ------------------- Admin Config -------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin1233"
MIN_WITHDRAWAL = 50.0

# ------------------- Earnings Logic -------------------
def credit_purchase(purchase: Purchase):
    if not purchase or not purchase.active:
        return 0.0
    product = purchase.product
    if not product:
        return 0.0

    today = datetime.now(timezone.utc).date()
    if purchase.next_payout_date is None and purchase.purchased_at:
        purchase.next_payout_date = purchase.purchased_at.date() + timedelta(days=1)

    if purchase.next_payout_date is None or purchase.next_payout_date > today:
        return 0.0

    days_due = (today - purchase.next_payout_date).days + 1
    days_to_credit = min(days_due, purchase.remaining_days)
    if days_to_credit <= 0:
        return 0.0

    # 20% of product price daily
    amount = days_to_credit * (product.price * 0.20)
    user = purchase.user
    if not user:
        return 0.0

    user.balance += amount
    user.earnings += amount

    purchase.remaining_days -= days_to_credit
    purchase.next_payout_date += timedelta(days=days_to_credit)
    if purchase.remaining_days <= 0:
        purchase.active = False

    db.session.commit()
    return amount

def credit_all_for_user(user: User):
    total = 0.0
    if not user:
        return 0.0
    purchases = Purchase.query.filter_by(user_id=user.id, active=True).all()
    for p in purchases:
        total += credit_purchase(p)
    return total

# ------------------- User Routes -------------------
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard"))
    products = Product.query.order_by(Product.price.asc()).all()
    return render_template("index.html", products=products)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        phone_number = request.form.get("phone_number", "").strip()
        password = request.form.get("password", "").strip()

        if not phone_number or not password:
            flash("Phone number and password required.", "error")
            return redirect("/register")

        if User.query.filter_by(phone_number=phone_number).first():
            flash("Phone number already exists.", "error")
            return redirect("/register")

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(phone_number=phone_number, password=hashed_password, balance=0.0, earnings=0.0)
        db.session.add(new_user)
        try:
            db.session.commit()
            flash("Account created successfully", "success")
            return redirect("/login")
        except Exception as e:
            db.session.rollback()
            flash("Error creating account: " + str(e), "error")
            return redirect("/register")

    return render_template("register.html")

@app.route("/dashboard/chart-data")
def dashboard_chart_data():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = User.query.filter_by(phone_number=session["user"]).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    purchases = Purchase.query.filter_by(user_id=user.id).all()
    labels = []
    earnings = []

    today = date.today()
    for i in range(7, 0, -1):
        day = today - timedelta(days=i)
        daily_total = 0
        for p in purchases:
            if p.active and p.next_payout_date <= day:
                daily_total += p.product.price * 0.20
        labels.append(day.strftime("%d-%b"))
        earnings.append(daily_total)

    return jsonify({"labels": labels, "earnings": earnings})

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone_number = request.form.get("phone_number", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(phone_number=phone_number).first()
        if user and bcrypt.check_password_hash(user.password, password):
            session["user"] = user.phone_number
            flash(f"Welcome {user.phone_number}", "success")
            return redirect("/dashboard")
        flash("Invalid credentials", "error")
        return redirect("/login")
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    user = User.query.filter_by(phone_number=session["user"]).first()
    if not user:
        session.clear()
        flash("User not found. Please login again.", "error")
        return redirect("/login")

    credited = credit_all_for_user(user)
    if credited > 0:
        flash(f"K{credited:.2f} credited from purchased products.", "success")

    purchases = Purchase.query.filter_by(user_id=user.id).all()
    withdrawals = Withdrawal.query.filter_by(user_id=user.id).all()
    recharges = Recharge.query.filter_by(user_id=user.id).all()
    total_daily = sum([p.product.price * 0.20 for p in purchases if p.active and p.product])

    recharge_setting = Setting.query.filter_by(key="recharge_number").first()
    admin_setting = Setting.query.filter_by(key="admin_name").first()
    recharge_number = recharge_setting.value if recharge_setting else "Not set"
    admin_name = admin_setting.value if admin_setting else "Admin"

    return render_template(
        "dashboard.html",
        username=user.phone_number,
        balance=user.balance,
        earnings=user.earnings,
        daily=total_daily,
        purchases=purchases,
        withdrawals=withdrawals,
        recharges=recharges,
        user=user,
        recharge_number=recharge_number,
        admin_name=admin_name
    )

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect("/")

@app.route("/recharge", methods=["GET", "POST"])
def recharge():
    if "user" not in session:
        return redirect("/login")
    user = User.query.filter_by(phone_number=session["user"]).first()
    if not user:
        session.clear()
        return redirect("/login")

    recharge_setting = Setting.query.filter_by(key="recharge_number").first()
    recharge_number = recharge_setting.value if recharge_setting else "Not set"
    admin_setting = Setting.query.filter_by(key="admin_name").first()
    admin_name = admin_setting.value if admin_setting else "Admin"

    if request.method == "POST":
        wallet = request.form.get("wallet_number", "").strip()
        if wallet:
            user.wallet_number = wallet
        try:
            amount = float(request.form.get("amount"))
        except (TypeError, ValueError):
            flash("Invalid amount.", "error")
            return redirect("/recharge")
        if amount <= 0:
            flash("Invalid amount.", "error")
            return redirect("/recharge")
        r = Recharge(user_id=user.id, amount=amount, status="Pending")
        db.session.add(r)
        db.session.commit()
        flash("Recharge request submitted. Admin must approve.", "success")
        return redirect("/dashboard")

    return render_template(
        "recharge.html",
        user=user.phone_number,
        balance=user.balance,
        contact_number=recharge_number,
        admin_name=admin_name,
        wallet_number=user.wallet_number or ""
    )

@app.route("/withdraw", methods=["GET", "POST"])
def withdraw():
    if "user" not in session:
        return redirect("/login")
    user = User.query.filter_by(phone_number=session["user"]).first()
    if not user:
        session.clear()
        return redirect("/login")

    if request.method == "POST":
        try:
            amount = float(request.form.get("amount"))
        except (TypeError, ValueError):
            flash("Invalid amount.", "error")
            return redirect("/withdraw")

        if amount < MIN_WITHDRAWAL:
            flash(f"Minimum withdrawal is K{MIN_WITHDRAWAL:.0f}.", "error")
            return redirect("/withdraw")
        if amount > user.balance:
            flash("Insufficient balance.", "error")
            return redirect("/withdraw")

        user.balance -= amount
        w = Withdrawal(user_id=user.id, amount=amount, status="Pending")
        db.session.add(w)
        db.session.commit()
        flash("Withdrawal request submitted; admin will process.", "success")
        return redirect("/dashboard")

    withdrawals = Withdrawal.query.filter_by(user_id=user.id).all()
    return render_template("withdraw.html", user=user.phone_number, withdrawals=withdrawals, balance=user.balance)

@app.route("/my_purchases")
def my_purchases():
    if "user" not in session:
        return redirect("/login")
    user = User.query.filter_by(phone_number=session["user"]).first()
    if not user:
        session.clear()
        return redirect("/login")

    # Ensure earnings are credited before showing purchases
    credit_all_for_user(user)

    purchases = Purchase.query.filter_by(user_id=user.id).all()
    return render_template("my_purchases.html", purchases=purchases, user=user)

# ------------------- Products Routes -------------------
@app.route("/products")
def products_page():
    if "user" not in session:
        return redirect("/login")
    user = User.query.filter_by(phone_number=session["user"]).first()
    products = Product.query.order_by(Product.price.asc()).all()
    return render_template("products.html", products=products, user=user)

@app.route("/buy_product/<int:id>")
def buy_product(id):
    if "user" not in session:
        return redirect("/login")
    user = User.query.filter_by(phone_number=session["user"]).first()
    product = Product.query.get(id)
    if not product:
        flash("Product not found.", "error")
        return redirect("/products")
    if user.balance < product.price:
        flash("Insufficient balance to buy this product.", "error")
        return redirect("/products")
    # Deduct balance and create purchase
    user.balance -= product.price
    purchase = Purchase(
        user_id=user.id,
        product_id=product.id,
        purchased_at=datetime.now(timezone.utc),
        remaining_days=product.duration_days,
        active=True
    )
    db.session.add(purchase)
    db.session.commit()
    flash(f"You have successfully purchased {product.name}", "success")
    return redirect("/dashboard")

# ------------------- Admin Routes -------------------
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            flash("Admin logged in.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.", "error")
        return redirect("/admin")
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect("/admin")
    users = User.query.all()
    withdrawals = Withdrawal.query.all()
    recharges = Recharge.query.all()
    products = Product.query.all()
    purchases = Purchase.query.all()

    # Calculate total balance and total earnings across all users
    total_balance = sum(user.balance for user in users)
    total_earnings = sum(user.earnings for user in users)

    return render_template(
        "admin_dashboard.html",
        users=users,
        withdrawals=withdrawals,
        recharges=recharges,
        products=products,
        purchases=purchases,
        total_balance=total_balance,
        total_earnings=total_earnings
    )

@app.route("/admin/update_settings", methods=["GET", "POST"])
def update_settings():
    if "admin" not in session:
        return redirect("/admin")

    recharge_setting = Setting.query.filter_by(key="recharge_number").first()
    admin_name_setting = Setting.query.filter_by(key="admin_name").first()

    if request.method == "POST":
        new_number = request.form.get("recharge_number", "").strip()
        new_name = request.form.get("admin_name", "").strip()

        if recharge_setting:
            recharge_setting.value = new_number
        else:
            recharge_setting = Setting(key="recharge_number", value=new_number)
            db.session.add(recharge_setting)

        if admin_name_setting:
            admin_name_setting.value = new_name
        else:
            admin_name_setting = Setting(key="admin_name", value=new_name)
            db.session.add(admin_name_setting)

        db.session.commit()
        flash("Settings updated successfully!", "success")
        return redirect("/admin/dashboard")

    recharge_number = recharge_setting.value if recharge_setting else ""
    admin_name = admin_name_setting.value if admin_name_setting else ""
    return render_template("admin_update_settings.html",
                           recharge_number=recharge_number,
                           admin_name=admin_name)

# ------------------- Admin Reset/Delete -------------------
@app.route("/admin/reset_password/<int:id>", methods=["POST"])
def admin_reset_password(id):
    if "admin" not in session:
        return redirect("/admin")
    user = User.query.get(id)
    if not user:
        flash("User not found.", "error")
        return redirect("/admin/dashboard")
    new_password = request.form.get("new_password", "").strip() or "123456"
    user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
    db.session.commit()
    flash(f"Password for {user.phone_number} reset to {new_password}", "success")
    return redirect("/admin/dashboard")

@app.route("/admin/delete_user/<int:id>")
def delete_user(id):
    if "admin" not in session:
        return redirect("/admin")
    user = User.query.get(id)
    if not user:
        flash("User not found.", "error")
        return redirect("/admin/dashboard")
    Purchase.query.filter_by(user_id=id).delete()
    Withdrawal.query.filter_by(user_id=id).delete()
    Recharge.query.filter_by(user_id=id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully", "success")
    return redirect("/admin/dashboard")

# ------------------- Admin Approve/Reject -------------------
@app.route("/admin/approve_recharge/<int:id>")
def approve_recharge(id):
    if "admin" not in session:
        return redirect("/admin")
    r = Recharge.query.get(id)
    if r and r.status == "Pending":
        r.status = "Approved"
        r.user.balance += r.amount
        db.session.commit()
        flash(f"Recharge #{r.id} approved.", "success")
    return redirect("/admin/dashboard")

@app.route("/admin/reject_recharge/<int:id>")
def reject_recharge(id):
    if "admin" not in session:
        return redirect("/admin")
    r = Recharge.query.get(id)
    if r and r.status == "Pending":
        r.status = "Rejected"
        db.session.commit()
        flash(f"Recharge #{r.id} rejected.", "success")
    return redirect("/admin/dashboard")

@app.route("/admin/approve_withdraw/<int:id>")
def approve_withdraw(id):
    if "admin" not in session:
        return redirect("/admin")
    w = Withdrawal.query.get(id)
    if w and w.status == "Pending":
        w.status = "Approved"
        db.session.commit()
        flash(f"Withdrawal #{w.id} approved.", "success")
    return redirect("/admin/dashboard")

@app.route("/admin/reject_withdraw/<int:id>")
def reject_withdraw(id):
    if "admin" not in session:
        return redirect("/admin")
    w = Withdrawal.query.get(id)
    if w and w.status == "Pending":
        w.status = "Rejected"
        w.user.balance += w.amount
        db.session.commit()
        flash(f"Withdrawal #{w.id} rejected and refunded.", "success")
    return redirect("/admin/dashboard")

# ------------------- Chart Demo -------------------
@app.route('/chart-data')
def chart_data():
    now = datetime.now().strftime("%H:%M:%S")
    price = random.randint(50, 150)
    return jsonify(time=now, price=price)

# ------------------- DB Init -------------------
with app.app_context():
    db.create_all()
    if Product.query.count() == 0:
        starter = Product(name="Starter Package", description="K50 - 20% daily for 20 days", price=50.0, daily_earning=0, duration_days=20)
        standard = Product(name="Standard Package", description="K150 - 20% daily for 20 days", price=150.0, daily_earning=0, duration_days=20)
        premium = Product(name="Premium Package", description="K300 - 20% daily for 20 days", price=300.0, daily_earning=0, duration_days=20)
        db.session.add_all([starter, standard, premium])
    if not Setting.query.filter_by(key="recharge_number").first():
        db.session.add(Setting(key="recharge_number", value="0777777777"))
    if not Setting.query.filter_by(key="admin_name").first():
        db.session.add(Setting(key="admin_name", value="Admin"))
    db.session.commit()

# ------------------- Run App -------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
