from flask import Flask, render_template, request, redirect, session, flash
from flask_bcrypt import Bcrypt
from models import db, User, Withdrawal, Recharge

app = Flask(__name__)
app.secret_key = "mysecretkey123"
bcrypt = Bcrypt(app)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# ------------------- User Routes -------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if User.query.filter_by(username=username).first():
            flash("User already exists.", "error")
            return redirect("/register")

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! Please log in.", "success")
        return redirect("/login")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            session["user"] = user.username
            flash(f"Welcome {user.username}!", "success")
            return redirect("/dashboard")
        flash("Invalid credentials", "error")
        return redirect("/login")
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    user = User.query.filter_by(username=session["user"]).first()
    withdrawals = Withdrawal.query.filter_by(user_id=user.id).all()
    recharges = Recharge.query.filter_by(user_id=user.id).all()

    return render_template(
        "dashboard.html",
        username=user.username,
        balance=user.balance,
        earnings=user.earnings,
        daily=user.daily_profit,
        withdrawals=withdrawals,
        recharges=recharges,
        user=user
    )


@app.route("/withdraw", methods=["GET", "POST"])
def withdraw():
    if "user" not in session:
        return redirect("/login")

    user = User.query.filter_by(username=session["user"]).first()

    if request.method == "POST":
        amount = float(request.form["amount"])
        if amount > user.balance:
            flash("Insufficient balance.", "error")
            return redirect("/withdraw")

        user.balance -= amount
        withdrawal = Withdrawal(user_id=user.id, amount=amount)
        db.session.add(withdrawal)
        db.session.commit()
        flash("Withdrawal request submitted!", "success")
        return redirect("/dashboard")

    withdrawals = Withdrawal.query.filter_by(user_id=user.id).all()
    return render_template("withdraw.html", user=user.username, withdrawals=withdrawals)


@app.route("/recharge", methods=["GET", "POST"])
def recharge():
    if "user" not in session:
        return redirect("/login")

    user = User.query.filter_by(username=session["user"]).first()

    if request.method == "POST":
        amount = float(request.form["amount"])
        if amount <= 0:
            flash("Invalid amount.", "error")
            return redirect("/recharge")

        new_recharge = Recharge(user_id=user.id, amount=amount)
        db.session.add(new_recharge)
        db.session.commit()
        flash("Recharge request submitted!", "success")
        return redirect("/dashboard")

    return render_template("recharge.html", user=user.username, balance=user.balance)

# ------------------- Admin Routes -------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            flash("Admin logged in.", "success")
            return redirect("/admin/dashboard")
        flash("Invalid admin login.", "error")
        return redirect("/admin")
    return render_template("admin_login.html")


@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect("/admin")

    users = User.query.all()
    withdrawals = Withdrawal.query.all()
    recharges = Recharge.query.all()

    return render_template(
        "admin_dashboard.html",
        users=users,
        withdrawals=withdrawals,
        recharges=recharges
    )


# ------------------- Admin Withdrawals -------------------

@app.route("/admin/withdrawals")
def admin_withdrawals():
    if "admin" not in session:
        return redirect("/admin")

    withdrawals = Withdrawal.query.all()
    return render_template("admin_withdrawals.html", withdrawals=withdrawals)


@app.route("/admin/approve/<int:id>")
def approve_withdrawal(id):
    if "admin" not in session:
        return redirect("/admin")

    w = Withdrawal.query.get(id)
    if w and w.status == "Pending":
        w.status = "Approved"
        db.session.commit()
        flash(f"Withdrawal #{w.id} approved.", "success")
    return redirect("/admin/withdrawals")


@app.route("/admin/reject/<int:id>")
def reject_withdrawal(id):
    if "admin" not in session:
        return redirect("/admin")

    w = Withdrawal.query.get(id)
    if w and w.status == "Pending":
        w.status = "Rejected"
        w.user.balance += w.amount
        db.session.commit()
        flash(f"Withdrawal #{w.id} rejected and amount refunded.", "success")
    return redirect("/admin/withdrawals")


# ------------------- Admin Recharges -------------------

@app.route("/admin/recharges")
def admin_recharges():
    if "admin" not in session:
        return redirect("/admin")

    recharges = Recharge.query.all()
    return render_template("admin_recharges.html", recharges=recharges)


@app.route("/admin/approve_recharge/<int:id>")
def approve_recharge(id):
    if "admin" not in session:
        return redirect("/admin")

    r = Recharge.query.get(id)
    if r and r.status == "Pending":
        r.status = "Approved"
        r.user.balance += r.amount
        db.session.commit()
        flash(f"Recharge #{r.id} approved and balance updated.", "success")
    return redirect("/admin/recharges")


@app.route("/admin/reject_recharge/<int:id>")
def reject_recharge(id):
    if "admin" not in session:
        return redirect("/admin")

    r = Recharge.query.get(id)
    if r and r.status == "Pending":
        r.status = "Rejected"
        db.session.commit()
        flash(f"Recharge #{r.id} rejected.", "success")
    return redirect("/admin/recharges")


# ------------------- Admin User Management -------------------

@app.route("/admin/user/delete/<int:id>")
def delete_user(id):
    if "admin" not in session:
        return redirect("/admin")

    user = User.query.get(id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash(f"User {user.username} deleted.", "success")
    return redirect("/admin/dashboard")


@app.route("/admin/user/reset_password/<int:id>", methods=["POST"])
def reset_password(id):
    if "admin" not in session:
        return redirect("/admin")

    user = User.query.get(id)
    new_pass = request.form.get("new_password")
    if user and new_pass:
        hashed_pw = bcrypt.generate_password_hash(new_pass).decode('utf-8')
        user.password = hashed_pw
        db.session.commit()
        flash(f"Password for {user.username} reset.", "success")
    return redirect("/admin/dashboard")


# ------------------- Logout -------------------

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
