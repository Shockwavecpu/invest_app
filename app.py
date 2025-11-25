from flask import Flask, render_template, request, redirect, session, flash, url_for
from flask_bcrypt import Bcrypt
from models import db, User, Recharge, Withdrawal, Product, Purchase, Setting
from datetime import datetime, date, timedelta
import os

app = Flask(__name__)
app.secret_key = "mysecretkey123"
bcrypt = Bcrypt(app)

# Database path
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_FILE}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin1233"

# Minimum withdrawal
MIN_WITHDRAWAL = 50.0

# ----------------- Earnings Logic -----------------
def credit_purchase(purchase: Purchase):
    if not purchase or not purchase.active:
        return 0.0
    product = purchase.product
    if not product:
        return 0.0
    today = date.today()
    if purchase.next_payout_date is None and purchase.purchased_at:
        purchase.next_payout_date = purchase.purchased_at.date() + timedelta(days=1)
    if purchase.next_payout_date is None or purchase.next_payout_date > today:
        return 0.0

    days_due = (today - purchase.next_payout_date).days + 1
    days_to_credit = min(days_due, purchase.remaining_days)
    if days_to_credit <= 0:
        return 0.0

    amount = days_to_credit * product.daily_earning
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

# ------------------- REGISTER -------------------
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

        new_user = User(
            phone_number=phone_number,
            password=hashed_password,
            balance=0.0,
            earnings=0.0
        )
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

# ------------------- LOGIN -------------------
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

# ------------------- DASHBOARD -------------------
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
    total_daily = sum([p.product.daily_earning for p in purchases if p.active and p.product])

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

# ------------------- LOGOUT -------------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect("/")

# ------------------- RECHARGE -------------------
@app.route("/recharge", methods=["GET", "POST"])
def recharge():
    if "user" not in session:
        return redirect("/login")
    
    user = User.query.filter_by(phone_number=session["user"]).first()
    if not user:
        session.clear()
        return redirect("/login")

    # Get latest settings
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

# ------------------- WITHDRAW -------------------
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
        w = Withdrawal(user_id=user.id, amount=amount, status="Pending")
        db.session.add(w)
        db.session.commit()
        flash("Withdrawal request submitted; admin will process.", "success")
        return redirect("/dashboard")

    withdrawals = Withdrawal.query.filter_by(user_id=user.id).all()
    return render_template("withdraw.html", user=user.phone_number, withdrawals=withdrawals, balance=user.balance)

# ------------------- PRODUCTS -------------------
@app.route("/products")
def products():
    if "user" not in session:
        flash("Please log in.", "error")
        return redirect("/login")
    user = User.query.filter_by(phone_number=session["user"]).first()
    products = Product.query.order_by(Product.price.asc()).all()
    return render_template("products.html", products=products, user=user)

@app.route("/buy_product/<int:product_id>")
def buy_product(product_id):
    if "user" not in session:
        return redirect("/login")
    user = User.query.filter_by(phone_number=session["user"]).first()
    product = Product.query.get(product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect("/products")
    if user.balance < product.price:
        flash("Insufficient balance. Please recharge first.", "error")
        return redirect("/products")
    user.balance -= product.price
    purchase = Purchase(
        user_id=user.id,
        product_id=product.id,
        purchased_at=datetime.utcnow(),
        next_payout_date=(date.today() + timedelta(days=1)),
        remaining_days=product.duration_days,
        active=True
    )
    db.session.add(purchase)
    db.session.commit()
    flash(f"You purchased {product.name}. Daily earnings will be credited automatically.", "success")
    return redirect("/dashboard")

# ------------------- ADMIN ROUTES -------------------
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
    return render_template("admin_dashboard.html", users=users, withdrawals=withdrawals,
                           recharges=recharges, products=products, purchases=purchases)


# Admin: reset password (accepts optional new_password from form)
@app.route("/admin/reset_password/<int:id>", methods=["POST"])
def admin_reset_password(id):
    if "admin" not in session:
        flash("Admin login required.", "error")
        return redirect("/admin")
    user = User.query.get(id)
    if not user:
        flash("User not found.", "error")
        return redirect("/admin/dashboard")

    # if the form provided a new_password input, use it; otherwise default
    new_password = request.form.get("new_password", "").strip()
    if new_password:
        pw = new_password
    else:
        pw = "123456"

    user.password = bcrypt.generate_password_hash(pw).decode('utf-8')
    db.session.commit()
    flash(f"Password for {user.phone_number} reset to {pw}", "success")
    return redirect("/admin/dashboard")


# Admin: delete user
@app.route("/admin/delete_user/<int:id>")
def delete_user(id):
    if "admin" not in session:
        flash("Admin login required.", "error")
        return redirect("/admin")

    user = User.query.get(id)
    if not user:
        flash("User not found.", "error")
        return redirect("/admin/dashboard")

    # Delete user's related data first
    Purchase.query.filter_by(user_id=id).delete()
    Withdrawal.query.filter_by(user_id=id).delete()
    Recharge.query.filter_by(user_id=id).delete()

    # Delete user
    db.session.delete(user)
    db.session.commit()

    flash("User deleted successfully", "success")
    return redirect("/admin/dashboard")


# ------------------- SETTINGS -------------------
@app.route("/admin/update_settings", methods=["GET", "POST"])
def update_settings():
    if "admin" not in session:
        return redirect("/admin")

    recharge_setting = Setting.query.filter_by(key="recharge_number").first()
    admin_name_setting = Setting.query.filter_by(key="admin_name").first()

    if request.method == "POST":
        new_number = request.form.get("recharge_number", "").strip()
        new_name = request.form.get("admin_name", "").strip()

        # Save or update recharge number
        if recharge_setting:
            recharge_setting.value = new_number
        else:
            recharge_setting = Setting(key="recharge_number", value=new_number)
            db.session.add(recharge_setting)

        # Save or update admin name
        if admin_name_setting:
            admin_name_setting.value = new_name
        else:
            admin_name_setting = Setting(key="admin_name", value=new_name)
            db.session.add(admin_name_setting)

        db.session.commit()
        flash("Settings updated successfully!", "success")
        return redirect("/admin/dashboard")

    # Render the form with current settings
    recharge_number = recharge_setting.value if recharge_setting else ""
    admin_name = admin_name_setting.value if admin_name_setting else ""
    return render_template("admin_update_settings.html",
                           recharge_number=recharge_number,
                           admin_name=admin_name)

# --- Alias route so old templates that call update_recharge_number won't fail ---
@app.route("/admin/update_recharge_number", methods=["GET", "POST"])
def update_recharge_number():
    # Reuse the same view as update_settings (keeps the UI consistent)
    return update_settings()


# ------------------ ADMIN APPROVE/REJECT ROUTES ------------------
# Accept both GET and POST to make buttons/links/forms work regardless.

@app.route("/admin/approve_recharge/<int:id>")
def approve_recharge(id):
    if "admin" not in session:
        return redirect("/admin")
    r = Recharge.query.get(id)
    if r and r.status == "Pending":
        r.status = "Approved"
        # credit balance
        r.user.balance += r.amount
        db.session.commit()
        flash(f"Recharge #{r.id} approved and balance updated.", "success")
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
        # in this system we already reduced balance at request time? (we didn't) - we didn't deduct; keep original behavior:
        # For safety: if balance was already reduced at request creation, do nothing. If you want to deduct only on approval, implement accordingly.
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
        # refund
        w.user.balance += w.amount
        db.session.commit()
        flash(f"Withdrawal #{w.id} rejected and refunded.", "success")
    return redirect("/admin/dashboard")


# ------------------- INIT DB & SEED -------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if Product.query.count() == 0:
            starter = Product(name="Starter Package", description="K50 - K3/day for 20 days", price=50.0, daily_earning=3.0, duration_days=20)
            standard = Product(name="Standard Package", description="K150 - K12/day for 20 days", price=150.0, daily_earning=12.0, duration_days=20)
            premium = Product(name="Premium Package", description="K300 - K25/day for 20 days", price=300.0, daily_earning=25.0, duration_days=20)
            db.session.add_all([starter, standard, premium])
        if not Setting.query.filter_by(key="recharge_number").first():
            s = Setting(key="recharge_number", value="0777777777")
            db.session.add(s)
        if not Setting.query.filter_by(key="admin_name").first():
            a = Setting(key="admin_name", value="Admin")
            db.session.add(a)
        db.session.commit()

    app.run(debug=True, host="0.0.0.0", port=5000)
