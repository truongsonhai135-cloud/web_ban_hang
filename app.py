from functools import wraps
import sqlite3
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = "doi-secret-key-truoc-khi-su-dung-that"
DB = Path(__file__).with_name("pos.db")


@app.template_filter("money")
def money(value):
    return "{:,.0f}".format(float(value or 0))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def table_columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'nhanvien'))
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL CHECK(price >= 0),
            stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
            barcode TEXT UNIQUE,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_code TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            cashier_id INTEGER NOT NULL,
            total INTEGER NOT NULL,
            payment_method TEXT NOT NULL,
            amount_received INTEGER NOT NULL,
            change_amount INTEGER NOT NULL,
            FOREIGN KEY(cashier_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            price INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
    """)

    # Thêm cột barcode cho cơ sở dữ liệu cũ nếu chưa có.
    product_columns = table_columns(db, "products")
    if "barcode" not in product_columns:
        db.execute("ALTER TABLE products ADD COLUMN barcode TEXT")
    if "active" not in product_columns:
        db.execute("ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1")

    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count == 0:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("Admin123"), "admin")
        )
    db.commit()


def login_required(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if roles and session.get("role") not in roles:
                flash("Bạn không có quyền thực hiện chức năng này.", "error")
                return redirect(url_for("pos"))
            return func(*args, **kwargs)
        return wrapper
    return decorator


@app.route("/")
def index():
    return redirect(url_for("pos" if session.get("user_id") else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("pos"))
        flash("Tên đăng nhập hoặc mật khẩu không đúng.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not 4 <= len(username) <= 50:
            flash("Tên đăng nhập phải từ 4 đến 50 ký tự.", "error")
            return render_template("register.html")
        if len(password) < 8:
            flash("Mật khẩu phải có ít nhất 8 ký tự.", "error")
            return render_template("register.html")
        if password != confirm_password:
            flash("Mật khẩu nhập lại không khớp.", "error")
            return render_template("register.html")

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), "nhanvien")
            )
            db.commit()
            flash("Đăng ký thành công. Hãy đăng nhập.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Tên đăng nhập đã tồn tại.", "error")
    return render_template("register.html")


@app.route("/pos")
@login_required("admin", "nhanvien")
def pos():
    products = get_db().execute(
        "SELECT * FROM products WHERE active = 1 ORDER BY name"
    ).fetchall()
    return render_template("pos.html", products=products)


@app.route("/checkout", methods=["POST"])
@login_required("admin", "nhanvien")
def checkout():
    db = get_db()
    product_ids = request.form.getlist("product_id")
    quantities = request.form.getlist("quantity")
    payment_method = request.form.get("payment_method", "cash")

    if payment_method not in ("cash", "bank"):
        flash("Phương thức thanh toán không hợp lệ.", "error")
        return redirect(url_for("pos"))

    if not product_ids or len(product_ids) != len(quantities):
        flash("Không nhận được sản phẩm trong giỏ hàng. Vui lòng chọn lại.", "error")
        return redirect(url_for("pos"))

    cart = {}
    try:
        for pid, qty in zip(product_ids, quantities):
            pid, qty = int(pid), int(qty)
            if pid <= 0 or qty <= 0:
                raise ValueError
            cart[pid] = cart.get(pid, 0) + qty
    except (TypeError, ValueError):
        flash("Sản phẩm hoặc số lượng không hợp lệ.", "error")
        return redirect(url_for("pos"))

    if not cart:
        flash("Vui lòng chọn ít nhất một sản phẩm.", "error")
        return redirect(url_for("pos"))

    items = []
    total = 0
    for product_id, quantity in cart.items():
        product = db.execute(
            "SELECT * FROM products WHERE id = ? AND active = 1",
            (product_id,)
        ).fetchone()
        if product is None:
            flash("Có sản phẩm không tồn tại hoặc đã ngừng kinh doanh.", "error")
            return redirect(url_for("pos"))
        if quantity > product["stock"]:
            flash(f"Sản phẩm {product['name']} không đủ hàng.", "error")
            return redirect(url_for("pos"))

        subtotal = int(product["price"]) * quantity
        total += subtotal
        items.append({
            "id": product["id"],
            "name": product["name"],
            "price": int(product["price"]),
            "quantity": quantity,
            "subtotal": subtotal
        })

    try:
        amount_received = int(request.form.get("amount_received", "0") or 0)
    except ValueError:
        flash("Số tiền khách đưa không hợp lệ.", "error")
        return redirect(url_for("pos"))

    if amount_received < 0:
        flash("Số tiền khách đưa không hợp lệ.", "error")
        return redirect(url_for("pos"))
    if payment_method == "cash" and amount_received < total:
        flash("Tiền khách đưa chưa đủ thanh toán.", "error")
        return redirect(url_for("pos"))
    if payment_method == "bank":
        amount_received = total

    change_amount = max(0, amount_received - total)
    receipt_code = "HD" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid4().hex[:4].upper()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor = db.execute(
            """INSERT INTO receipts
            (receipt_code, created_at, cashier_id, total, payment_method, amount_received, change_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (receipt_code, created_at, session["user_id"], total,
             payment_method, amount_received, change_amount)
        )
        receipt_id = cursor.lastrowid

        for item in items:
            db.execute(
                """INSERT INTO receipt_items
                (receipt_id, product_id, product_name, price, quantity, subtotal)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (receipt_id, item["id"], item["name"], item["price"],
                 item["quantity"], item["subtotal"])
            )
            db.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (item["quantity"], item["id"])
            )
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("Lỗi khi lưu hóa đơn")
        flash("Không thể lưu hóa đơn. Vui lòng kiểm tra Terminal.", "error")
        return redirect(url_for("pos"))

    return redirect(url_for("receipt_detail", receipt_id=receipt_id))


@app.route("/receipt/<int:receipt_id>")
@login_required("admin", "nhanvien")
def receipt_detail(receipt_id):
    db = get_db()
    receipt = db.execute(
        """SELECT receipts.*, users.username
        FROM receipts JOIN users ON users.id = receipts.cashier_id
        WHERE receipts.id = ?""",
        (receipt_id,)
    ).fetchone()

    if receipt is None:
        flash("Không tìm thấy hóa đơn.", "error")
        return redirect(url_for("history"))
    if session.get("role") != "admin" and receipt["cashier_id"] != session.get("user_id"):
        flash("Bạn không có quyền xem hóa đơn này.", "error")
        return redirect(url_for("history"))

    items = db.execute(
        """SELECT receipt_items.*, (price * quantity) AS subtotal
        FROM receipt_items WHERE receipt_id = ? ORDER BY id""",
        (receipt_id,)
    ).fetchall()
    return render_template("receipt.html", receipt=receipt, items=items)


@app.route("/history")
@login_required("admin", "nhanvien")
def history():
    db = get_db()
    if session.get("role") == "admin":
        receipts = db.execute(
            """SELECT receipts.*, users.username
            FROM receipts JOIN users ON users.id = receipts.cashier_id
            ORDER BY receipts.id DESC LIMIT 100"""
        ).fetchall()
    else:
        receipts = db.execute(
            """SELECT receipts.*, users.username
            FROM receipts JOIN users ON users.id = receipts.cashier_id
            WHERE receipts.cashier_id = ?
            ORDER BY receipts.id DESC LIMIT 100""",
            (session["user_id"],)
        ).fetchall()
    return render_template("history.html", receipts=receipts)


@app.route("/products", methods=["GET", "POST"])
@login_required("admin")
def products():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action", "add")
        name = request.form.get("name", "").strip()

        try:
            price = int(request.form.get("price", ""))
            stock = int(request.form.get("stock", ""))
        except ValueError:
            flash("Giá và số lượng phải là số nguyên hợp lệ.", "error")
            return redirect(url_for("products"))

        barcode = request.form.get("barcode", "").strip() or None
        if not name or price < 0 or stock < 0:
            flash("Tên, giá hoặc số lượng không hợp lệ.", "error")
            return redirect(url_for("products"))

        try:
            if action == "update":
                product_id = int(request.form.get("product_id", ""))
                db.execute(
                    """UPDATE products SET name=?, price=?, stock=?, barcode=?
                    WHERE id=? AND active=1""",
                    (name, price, stock, barcode, product_id)
                )
                flash("Đã cập nhật sản phẩm.", "success")
            elif action == "delete":
                product_id = int(request.form.get("product_id", ""))
                db.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
                flash("Đã ngừng kinh doanh sản phẩm.", "success")
            else:
                db.execute(
                    """INSERT INTO products (name, price, stock, barcode, active)
                    VALUES (?, ?, ?, ?, 1)""",
                    (name, price, stock, barcode)
                )
                flash("Đã thêm sản phẩm.", "success")
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Mã vạch đã được sử dụng hoặc dữ liệu bị trùng.", "error")
        except (ValueError, TypeError):
            db.rollback()
            flash("Mã sản phẩm không hợp lệ.", "error")
        return redirect(url_for("products"))

    product_list = db.execute(
        "SELECT * FROM products WHERE active = 1 ORDER BY id DESC"
    ).fetchall()
    return render_template("products.html", products=product_list)


@app.route("/products/<int:pid>/update", methods=["POST"])
@login_required("admin")
def update_product(pid):
    db = get_db()
    name = request.form.get("name", "").strip()
    try:
        price = int(request.form.get("price", ""))
        stock = int(request.form.get("stock", ""))
    except ValueError:
        flash("Giá và số lượng phải là số nguyên hợp lệ.", "error")
        return redirect(url_for("products"))
    barcode = request.form.get("barcode", "").strip() or None
    if not name or price < 0 or stock < 0:
        flash("Tên, giá hoặc số lượng không hợp lệ.", "error")
        return redirect(url_for("products"))
    try:
        cur = db.execute(
            "UPDATE products SET name=?, price=?, stock=?, barcode=? WHERE id=? AND active=1",
            (name, price, stock, barcode, pid)
        )
        db.commit()
        flash("Đã cập nhật sản phẩm." if cur.rowcount else "Không tìm thấy sản phẩm.", 
              "success" if cur.rowcount else "error")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Mã vạch đã được sử dụng.", "error")
    return redirect(url_for("products"))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("Bạn đã đăng xuất.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
