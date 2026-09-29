from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, secrets
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pos-dev-secret-change-in-production")
DB = os.path.join(os.path.dirname(__file__), "pos.db")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','staff'))
    );
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        sku TEXT UNIQUE,
        price REAL NOT NULL DEFAULT 0 CHECK(price >= 0),
        stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0)
    );
    CREATE TABLE IF NOT EXISTS suppliers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        address TEXT
    );
    CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT UNIQUE NOT NULL,
        user_id INTEGER,
        customer_name TEXT,
        subtotal REAL NOT NULL DEFAULT 0,
        discount REAL NOT NULL DEFAULT 0,
        tax REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL,
        payment_method TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS transaction_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER,
        product_id INTEGER,
        quantity INTEGER,
        price REAL,
        subtotal REAL,
        FOREIGN KEY(transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );
    CREATE TABLE IF NOT EXISTS returns(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER,
        product_id INTEGER,
        quantity INTEGER,
        reason TEXT,
        created_at TEXT NOT NULL,
        user_id INTEGER,
        FOREIGN KEY(transaction_id) REFERENCES transactions(id) ON DELETE RESTRICT,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at);
    CREATE INDEX IF NOT EXISTS idx_items_transaction ON transaction_items(transaction_id);
    CREATE INDEX IF NOT EXISTS idx_returns_transaction ON returns(transaction_id);
    """)
    # Safe migrations for databases created by the original version.
    cols = {r["name"] for r in con.execute("PRAGMA table_info(transactions)").fetchall()}
    for name, definition in [("subtotal", "REAL NOT NULL DEFAULT 0"), ("discount", "REAL NOT NULL DEFAULT 0"), ("tax", "REAL NOT NULL DEFAULT 0")]:
        if name not in cols:
            con.execute(f"ALTER TABLE transactions ADD COLUMN {name} {definition}")
    con.execute("UPDATE transactions SET subtotal=total WHERE subtotal=0 AND discount=0 AND tax=0")

    if not con.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)", ("admin", generate_password_hash("admin123"), "admin"))
    if not con.execute("SELECT 1 FROM users WHERE username='staff'").fetchone():
        con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)", ("staff", generate_password_hash("staff123"), "staff"))
    if con.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] == 0:
        products = [("Cotton Shirt","Shirts","TS001",799,25),("Denim Jeans","Jeans","JN001",1499,15),("Kurta","Ethnic","KT001",999,20),("Cotton Saree","Saree","SR001",1899,10),("Formal Trouser","Trousers","TR001",1199,18)]
        con.executemany("INSERT INTO products(name,category,sku,price,stock) VALUES(?,?,?,?,?)", products)
    con.commit(); con.close()


def login_required(role=None):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Admin access required.", "danger")
                return redirect(url_for("billing"))
            return f(*args, **kwargs)
        return wrapper
    return deco


def admin_context():
    return {"mobile_admin": bool(session.get("mobile_admin"))}


@app.route("/")
def index():
    if "user_id" not in session: return redirect(url_for("login"))
    return redirect(url_for("admin_dashboard" if session["role"] == "admin" else "billing"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form.get("username", "").strip(), request.form.get("password", "")
        con = db(); user = con.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone(); con.close()
        if user and check_password_hash(user["password"], p):
            session.update(user_id=user["id"], username=user["username"], role=user["role"], mobile_admin=False)
            return redirect(url_for("index"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))


@app.route("/admin/mobile")
@login_required("admin")
def admin_mobile():
    session["mobile_admin"] = True
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/desktop")
@login_required("admin")
def admin_desktop():
    session["mobile_admin"] = False
    return redirect(url_for("admin_dashboard"))


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    con = db()
    data = {
        "products": con.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
        "staff": con.execute("SELECT COUNT(*) c FROM users WHERE role='staff'").fetchone()["c"],
        "suppliers": con.execute("SELECT COUNT(*) c FROM suppliers").fetchone()["c"],
        "sales": con.execute("SELECT COALESCE(SUM(total),0) s FROM transactions").fetchone()["s"],
        "transactions": con.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"],
        "low_stock": con.execute("SELECT COUNT(*) c FROM products WHERE stock<=5").fetchone()["c"]
    }
    recent = con.execute("SELECT invoice_no,total,payment_method,created_at FROM transactions ORDER BY id DESC LIMIT 6").fetchall()
    con.close()
    return render_template("admin/dashboard.html", data=data, recent=recent, **admin_context())


@app.route("/admin/products")
@login_required("admin")
def products():
    q = request.args.get("q", "").strip()
    con = db(); rows = con.execute("SELECT * FROM products WHERE name LIKE ? OR sku LIKE ? OR category LIKE ? ORDER BY id DESC", (f"%{q}%",f"%{q}%",f"%{q}%")).fetchall(); con.close()
    return render_template("admin/products.html", products=rows, q=q, **admin_context())


@app.route("/admin/products/add", methods=["POST"])
@login_required("admin")
def add_product():
    try:
        name=request.form["name"].strip(); category=request.form.get("category","").strip(); sku=request.form["sku"].strip(); price=float(request.form["price"]); stock=int(request.form["stock"])
        if not name or not sku or price < 0 or stock < 0: raise ValueError("Enter valid product details")
        con=db(); con.execute("INSERT INTO products(name,category,sku,price,stock) VALUES(?,?,?,?,?)",(name,category,sku,price,stock)); con.commit(); con.close(); flash("Product added.","success")
    except Exception as e: flash(f"Could not add product: {e}","danger")
    return redirect(url_for("products"))


@app.route("/admin/products/delete/<int:pid>", methods=["POST"])
@login_required("admin")
def delete_product(pid):
    con=db()
    try:
        con.execute("DELETE FROM products WHERE id=?", (pid,)); con.commit(); flash("Product deleted.","success")
    except sqlite3.IntegrityError: flash("This product has transaction history and cannot be deleted. Set stock to 0 instead.","danger")
    con.close(); return redirect(url_for("products"))


@app.route("/admin/products/edit/<int:pid>", methods=["POST"])
@login_required("admin")
def edit_product(pid):
    try:
        con=db(); con.execute("UPDATE products SET name=?,category=?,sku=?,price=?,stock=? WHERE id=?",(request.form["name"].strip(),request.form.get("category","").strip(),request.form["sku"].strip(),float(request.form["price"]),int(request.form["stock"]),pid)); con.commit(); con.close(); flash("Product updated.","success")
    except Exception as e: flash(f"Could not update product: {e}","danger")
    return redirect(url_for("products"))


@app.route("/admin/staff", methods=["GET","POST"])
@login_required("admin")
def staff():
    con=db()
    if request.method=="POST":
        try:
            username=request.form["username"].strip(); password=request.form["password"]
            if len(password)<4: raise ValueError("Password must contain at least 4 characters")
            con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",(username,generate_password_hash(password),"staff")); con.commit(); flash("Staff account created.","success")
        except Exception as e: flash(f"Could not create staff: {e}","danger")
    rows=con.execute("SELECT id,username,role FROM users WHERE role='staff' ORDER BY id DESC").fetchall(); con.close()
    return render_template("admin/staff.html", staff=rows, **admin_context())


@app.route("/admin/staff/delete/<int:uid>", methods=["POST"])
@login_required("admin")
def delete_staff(uid):
    con=db(); con.execute("DELETE FROM users WHERE id=? AND role='staff'",(uid,)); con.commit(); con.close(); flash("Staff account deleted.","success"); return redirect(url_for("staff"))


@app.route("/admin/suppliers", methods=["GET","POST"])
@login_required("admin")
def suppliers():
    con=db()
    if request.method=="POST":
        try:
            con.execute("INSERT INTO suppliers(name,phone,email,address) VALUES(?,?,?,?)",(request.form["name"].strip(),request.form.get("phone",""),request.form.get("email",""),request.form.get("address",""))); con.commit(); flash("Supplier added.","success")
        except Exception as e: flash(f"Could not add supplier: {e}","danger")
    rows=con.execute("SELECT * FROM suppliers ORDER BY id DESC").fetchall(); con.close(); return render_template("admin/suppliers.html", suppliers=rows, **admin_context())


@app.route("/admin/suppliers/edit/<int:sid>", methods=["POST"])
@login_required("admin")
def edit_supplier(sid):
    con=db(); con.execute("UPDATE suppliers SET name=?,phone=?,email=?,address=? WHERE id=?",(request.form["name"].strip(),request.form.get("phone",""),request.form.get("email",""),request.form.get("address",""),sid)); con.commit(); con.close(); flash("Supplier updated.","success"); return redirect(url_for("suppliers"))


@app.route("/admin/suppliers/delete/<int:sid>", methods=["POST"])
@login_required("admin")
def delete_supplier(sid):
    con=db(); con.execute("DELETE FROM suppliers WHERE id=?",(sid,)); con.commit(); con.close(); flash("Supplier deleted.","success"); return redirect(url_for("suppliers"))


@app.route("/admin/transactions")
@login_required("admin")
def transactions():
    start=request.args.get("start",""); end=request.args.get("end",""); payment=request.args.get("payment",""); q=request.args.get("q","")
    sql="""SELECT t.*,u.username FROM transactions t LEFT JOIN users u ON t.user_id=u.id WHERE 1=1"""; args=[]
    if start: sql += " AND date(t.created_at)>=date(?)"; args.append(start)
    if end: sql += " AND date(t.created_at)<=date(?)"; args.append(end)
    if payment: sql += " AND t.payment_method=?"; args.append(payment)
    if q: sql += " AND (t.invoice_no LIKE ? OR t.customer_name LIKE ?)"; args += [f"%{q}%",f"%{q}%"]
    sql += " ORDER BY t.id DESC"
    con=db(); rows=con.execute(sql,args).fetchall(); summary=con.execute("SELECT COALESCE(SUM(total),0) total,COUNT(*) count FROM transactions").fetchone(); con.close()
    return render_template("admin/transactions.html", transactions=rows, start=start,end=end,payment=payment,q=q,summary=summary, **admin_context())


@app.route("/admin/returns", methods=["GET","POST"])
@login_required("admin")
def returns():
    con=db()
    if request.method=="POST":
        try:
            tid=int(request.form["transaction_id"]); pid=int(request.form["product_id"]); qty=int(request.form["quantity"])
            item=con.execute("SELECT * FROM transaction_items WHERE transaction_id=? AND product_id=?",(tid,pid)).fetchone()
            already=con.execute("SELECT COALESCE(SUM(quantity),0) q FROM returns WHERE transaction_id=? AND product_id=?",(tid,pid)).fetchone()["q"]
            available=(item["quantity"]-already) if item else 0
            if not item or qty<=0 or qty>available: raise ValueError(f"Return quantity must be between 1 and {available}")
            con.execute("INSERT INTO returns(transaction_id,product_id,quantity,reason,created_at,user_id) VALUES(?,?,?,?,?,?)",(tid,pid,qty,request.form.get("reason",""),datetime.now().strftime("%Y-%m-%d %H:%M:%S"),session["user_id"]))
            con.execute("UPDATE products SET stock=stock+? WHERE id=?",(qty,pid)); con.commit(); flash("Return processed and stock updated.","success")
        except Exception as e: con.rollback(); flash(str(e),"danger")
    rows=con.execute("""SELECT r.*,p.name product_name,t.invoice_no,u.username FROM returns r JOIN products p ON p.id=r.product_id JOIN transactions t ON t.id=r.transaction_id LEFT JOIN users u ON u.id=r.user_id ORDER BY r.id DESC""").fetchall(); con.close()
    return render_template("admin/returns.html", returns=rows, **admin_context())


@app.route("/admin/returns/invoice/<invoice>")
@login_required("admin")
def return_invoice(invoice):
    con=db(); t=con.execute("SELECT * FROM transactions WHERE invoice_no=?",(invoice,)).fetchone()
    if not t: con.close(); return jsonify({"ok":False,"error":"Invoice not found"}),404
    items=con.execute("""SELECT i.product_id,i.quantity,i.price,p.name,COALESCE((SELECT SUM(r.quantity) FROM returns r WHERE r.transaction_id=i.transaction_id AND r.product_id=i.product_id),0) returned FROM transaction_items i JOIN products p ON p.id=i.product_id WHERE i.transaction_id=?""",(t["id"],)).fetchall(); con.close()
    return jsonify({"ok":True,"invoice":dict(t),"items":[dict(x) for x in items]})


@app.route("/admin/reports")
@login_required("admin")
def reports():
    con=db(); daily=con.execute("""SELECT substr(created_at,1,10) day,COUNT(*) transactions,ROUND(SUM(total),2) sales FROM transactions GROUP BY day ORDER BY day DESC LIMIT 30""").fetchall(); top=con.execute("""SELECT p.name,SUM(i.quantity) qty,ROUND(SUM(i.subtotal),2) revenue FROM transaction_items i JOIN products p ON p.id=i.product_id GROUP BY p.id ORDER BY qty DESC LIMIT 10""").fetchall(); returns_total=con.execute("SELECT COALESCE(SUM(quantity),0) qty FROM returns").fetchone()["qty"]; con.close()
    return render_template("admin/reports.html",daily=daily,top=top,returns_total=returns_total, **admin_context())


@app.route("/billing")
@login_required()
def billing():
    con=db(); products=con.execute("SELECT * FROM products WHERE stock>0 ORDER BY name").fetchall(); con.close(); return render_template("billing.html", products=products)


@app.route("/api/products")
@login_required()
def api_products():
    con=db(); rows=con.execute("SELECT * FROM products WHERE stock>0 ORDER BY name").fetchall(); con.close(); return jsonify([dict(x) for x in rows])


@app.route("/billing/checkout", methods=["POST"])
@login_required()
def checkout():
    payload=request.get_json(force=True); items=payload.get("items",[]); customer=(payload.get("customer_name") or "Walk-in Customer").strip(); payment=payload.get("payment_method","Cash"); discount=max(float(payload.get("discount",0) or 0),0); tax_rate=max(float(payload.get("tax_rate",0) or 0),0)
    if not items: return jsonify({"ok":False,"error":"Cart is empty"}),400
    if payment not in {"Cash","UPI","Card"}: return jsonify({"ok":False,"error":"Invalid payment method"}),400
    con=db(); total=0; checked=[]
    try:
        for x in items:
            p=con.execute("SELECT * FROM products WHERE id=?",(int(x["id"]),)).fetchone(); q=int(x["qty"])
            if not p or q<=0 or q>p["stock"]: raise ValueError(f"Insufficient stock for {x.get('name','product')}")
            total += p["price"]*q; checked.append((p,q))
        discount=min(discount,total); taxable=total-discount; tax=taxable*tax_rate/100; grand=taxable+tax
        invoice="INV-"+datetime.now().strftime("%Y%m%d%H%M%S%f")
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur=con.execute("INSERT INTO transactions(invoice_no,user_id,customer_name,subtotal,discount,tax,total,payment_method,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(invoice,session["user_id"],customer,total,discount,tax,grand,payment,now)); tid=cur.lastrowid
        for p,q in checked:
            con.execute("INSERT INTO transaction_items(transaction_id,product_id,quantity,price,subtotal) VALUES(?,?,?,?,?)",(tid,p["id"],q,p["price"],p["price"]*q)); con.execute("UPDATE products SET stock=stock-? WHERE id=?",(q,p["id"]))
        con.commit(); return jsonify({"ok":True,"invoice":invoice,"total":round(grand,2)})
    except Exception as e: con.rollback(); return jsonify({"ok":False,"error":str(e)}),400
    finally: con.close()


@app.route("/bill/<invoice>")
@login_required()
def bill(invoice):
    con=db(); t=con.execute("SELECT * FROM transactions WHERE invoice_no=?",(invoice,)).fetchone(); items=con.execute("SELECT i.*,p.name FROM transaction_items i JOIN products p ON p.id=i.product_id WHERE i.transaction_id=?",(t["id"],)).fetchall() if t else []; con.close()
    if not t: return "Bill not found",404
    return render_template("bill.html",t=t,items=items)


@app.context_processor
def inject_helpers():
    return {"now_year": datetime.now().year, "mobile_admin": bool(session.get("mobile_admin"))}


if __name__ == "__main__":
    init_db()
    app.run(host=os.environ.get("HOST","127.0.0.1"), port=int(os.environ.get("PORT",5000)), debug=os.environ.get("FLASK_DEBUG","0") == "1")
