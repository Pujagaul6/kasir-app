#!/usr/bin/env python3
"""
Kasir App — Simple POS & Bookkeeping
Flask + SQLite, single file
Port: 5050
"""

import os, sqlite3, json, csv, io, secrets
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask import Flask, request, redirect, url_for, render_template_string, jsonify, Response, session

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kasir.db")

# ─── DATABASE ─────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total INTEGER NOT NULL DEFAULT 0,
            payment INTEGER NOT NULL DEFAULT 0,
            change_amount INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        );
        CREATE TABLE IF NOT EXISTS finance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('income','expense')),
            amount INTEGER NOT NULL,
            description TEXT,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ppob_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type TEXT NOT NULL,
            product_name TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            selling_price INTEGER NOT NULL,
            cost_price INTEGER NOT NULL,
            profit INTEGER NOT NULL,
            status TEXT DEFAULT 'success',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'kasir',
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            transaction_id INTEGER,
            total_amount INTEGER NOT NULL,
            paid_amount INTEGER NOT NULL DEFAULT 0,
            remaining INTEGER NOT NULL,
            status TEXT DEFAULT 'unpaid',
            due_date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        );
        CREATE TABLE IF NOT EXISTS returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (debt_id) REFERENCES debts(id)
        );
    """)
    # Seed sample products if empty
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        samples = [
            ("Indomie Goreng", 3500, 100),
            ("Aqua 600ml", 3000, 50),
            ("Teh Botol Sosro", 4500, 60),
            ("Kopi Kapal Api", 2500, 80),
            ("Chitato 68g", 9500, 30),
            ("Roti Tawar", 12000, 20),
            ("Telur 1kg", 28000, 15),
            ("Minyak Goreng 1L", 14500, 25),
            ("Gula Pasir 1kg", 14000, 20),
            ("Beras 5kg", 62000, 10),
        ]
        conn.executemany("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", samples)
    # Migrate existing tables
    try:
        conn.execute("ALTER TABLE products ADD COLUMN cost_price INTEGER NOT NULL DEFAULT 0")
    except: pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN discount INTEGER NOT NULL DEFAULT 0")
    except: pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN discount_type TEXT DEFAULT 'rupiah'")
    except: pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN tax_amount INTEGER NOT NULL DEFAULT 0")
    except: pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER")
    except: pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN customer_id INTEGER")
    except: pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN is_debt INTEGER NOT NULL DEFAULT 0")
    except: pass

    # Seed default settings if empty
    if conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        defaults = [
            ("store_name", "Toko Saya"),
            ("store_address", ""),
            ("store_phone", ""),
            ("store_footer", "Terima kasih atas kunjungan Anda!"),
        ]
        conn.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults)
    # Seed admin user if empty
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users (username, password, role, name) VALUES (?, ?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "admin", "Administrator"))
    # Seed default settings
    conn.commit()
    conn.close()

# ─── HELPERS ──────────────────────────────────────────────────────────
def rupiah(val):
    """Format number as Rp XX.XXX"""
    if val is None:
        return "Rp 0"
    return f"Rp {val:,.0f}".replace(",", ".")

def now_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def get_setting(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_current_user():
    if 'user_id' not in session:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    conn.close()
    return user

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ─── TEMPLATES ────────────────────────────────────────────────────────
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login — Kasir App</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gradient-to-br from-indigo-600 to-purple-700 min-h-screen flex items-center justify-center">
    <div class="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-md">
        <div class="text-center mb-8">
            <div class="text-4xl mb-2">🛒</div>
            <h1 class="text-2xl font-bold text-gray-800">Kasir App</h1>
            <p class="text-gray-500 text-sm">Silakan login untuk melanjutkan</p>
        </div>
        {% if error %}
        <div class="bg-red-50 text-red-600 px-4 py-3 rounded-lg mb-4 text-sm">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <div class="mb-4">
                <label class="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input type="text" name="username" required class="w-full border rounded-lg px-4 py-3 text-lg" placeholder="Masukkan username" autofocus>
            </div>
            <div class="mb-6">
                <label class="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input type="password" name="password" required class="w-full border rounded-lg px-4 py-3 text-lg" placeholder="Masukkan password">
            </div>
            <button type="submit" class="w-full bg-indigo-600 text-white py-3 rounded-lg font-semibold text-lg hover:bg-indigo-700 transition">
                🔐 Login
            </button>
        </form>
        <p class="text-center text-xs text-gray-400 mt-6">Default: admin / admin123</p>
    </div>
</body>
</html>
'''

LAYOUT = '''
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} — Kasir App</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @media print {
            .no-print { display: none !important; }
            body { background: white !important; margin: 0; padding: 0; }
            #receiptArea {
                width: 72mm; /* 80mm thermal */
                margin: 0; padding: 8px;
                font-family: 'Courier New', monospace;
                font-size: 11px; line-height: 1.3;
                box-shadow: none; border: none;
            }
            #receiptArea .text-xl { font-size: 14px; }
            #receiptArea .text-lg { font-size: 12px; }
            #receiptArea .border-dashed { border-style: dashed; }
        }
        @media print and (max-width: 58mm) {
            #receiptArea { width: 52mm; font-size: 10px; }
        }
        .toast { position: fixed; top: 1rem; right: 1rem; z-index: 9999; padding: 1rem 1.5rem;
                 border-radius: 0.5rem; color: white; font-weight: 600; opacity: 0;
                 transition: opacity 0.3s; }
        .toast.show { opacity: 1; }
        .toast.success { background: #10b981; }
        .toast.error { background: #ef4444; }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <div id="toast" class="toast"></div>

    <!-- Sidebar -->
    <div class="no-print flex">
        <nav id="sidebar" class="w-64 bg-indigo-800 text-white min-h-screen p-4 fixed lg:relative transform -translate-x-full lg:translate-x-0 transition-transform z-50">
            <div class="text-2xl font-bold mb-8 flex items-center gap-2">
                <span>🛒</span> <span>Kasir App</span>
            </div>
            <div class="space-y-1">
                <a href="/" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'active' if page=='dashboard' else '' }} {{ 'bg-indigo-700' if page=='dashboard' else '' }}">
                    <span>📊</span> Dashboard
                </a>
                <a href="/products" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='products' else '' }}">
                    <span>📦</span> Produk & Stok
                </a>
                <a href="/import" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='import' else '' }}">
                    <span>📥</span> Import Produk
                </a>
                <a href="/ppob" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='ppob' else '' }}">
                    <span>⚡</span> PPOB (Token/Pulsa)
                </a>
                <a href="/kasir" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='kasir' else '' }}">
                    <span>💳</span> Kasir (POS)
                </a>
                <a href="/penjualan" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='penjualan' else '' }}">
                    <span>📋</span> Riwayat Penjualan
                </a>
                <a href="/pembukuan" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='pembukuan' else '' }}">
                    <span>💰</span> Pembukuan
                </a>
                <a href="/piutang" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='piutang' else '' }}">
                    <span>📝</span> Piutang
                </a>
                <a href="/retur" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='retur' else '' }}">
                    <span>📦</span> Retur
                </a>
                <a href="/users" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='users' else '' }}">
                    <span>👥</span> Kelola User
                </a>
                <a href="/backup" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='backup' else '' }}">
                    <span>💾</span> Backup & Restore
                </a>
                <a href="/settings" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='settings' else '' }}">
                    <span>⚙️</span> Pengaturan
                </a>
            </div>
        </nav>

        <!-- Main -->
        <div class="flex-1">
            <!-- Top bar -->
            <div class="bg-white shadow-sm px-6 py-3 flex items-center justify-between no-print">
                <button onclick="document.getElementById('sidebar').classList.toggle('-translate-x-full')" class="lg:hidden text-2xl">☰</button>
                <h1 class="text-xl font-semibold text-gray-800">{{ title }}</h1>
                <div class="flex items-center gap-4">
                    <span class="text-sm text-gray-500">{{ now }}</span>
                    {% if session.get('user_name') %}
                    <span class="text-sm text-indigo-600 font-medium">👤 {{ session.get('user_name') }}</span>
                    <a href="/logout" class="text-sm text-red-500 hover:underline">Logout</a>
                    {% endif %}
                </div>
            </div>
            <div class="p-6">
                {{ content|safe }}
            </div>
        </div>
    </div>

    <script>
        function showToast(msg, type='success') {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = 'toast show ' + type;
            setTimeout(() => t.className = 'toast', 3000);
        }
        function formatRupiah(n) {
            return 'Rp ' + n.toLocaleString('id-ID').replace(/,/g, '.');
        }
    </script>
    {% block scripts %}{% endblock %}
</body>
</html>
'''

# ─── ROUTES ───────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_role"] = user["role"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        return render_template_string(LOGIN_TEMPLATE, error="Username atau password salah!")
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    # Today's stats
    row = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(total),0) as total
        FROM transactions WHERE DATE(created_at) = ?
    """, (today,)).fetchone()
    today_sales = row["count"]
    today_income = row["total"]

    # Today's items sold
    row = conn.execute("""
        SELECT COALESCE(SUM(ti.quantity),0) as qty
        FROM transaction_items ti
        JOIN transactions t ON t.id = ti.transaction_id
        WHERE DATE(t.created_at) = ?
    """, (today,)).fetchone()
    today_items = row["qty"]

    # Total products
    total_products = conn.execute("SELECT COUNT(*) as c FROM products").fetchone()["c"]
    low_stock = conn.execute("SELECT COUNT(*) as c FROM products WHERE stock <= 5").fetchone()["c"]

    # Stock value
    stock_data = conn.execute("SELECT COALESCE(SUM(price * stock), 0) as total_value, COALESCE(SUM(stock), 0) as total_items FROM products").fetchone()
    stock_value = stock_data["total_value"]
    stock_items = stock_data["total_items"]

    # Piutang summary
    total_piutang = conn.execute("SELECT COALESCE(SUM(remaining),0) as s FROM debts WHERE status != 'paid'").fetchone()["s"]
    piutang_count = conn.execute("SELECT COUNT(*) as c FROM debts WHERE status != 'paid'").fetchone()["c"]

    # This month finance
    month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    month_income = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM finance WHERE type='income' AND DATE(created_at) >= ?", (month_start,)
    ).fetchone()["s"]
    month_expense = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM finance WHERE type='expense' AND DATE(created_at) >= ?", (month_start,)
    ).fetchone()["s"]

    # Recent transactions
    recent = conn.execute("""
        SELECT * FROM transactions ORDER BY created_at DESC LIMIT 5
    """).fetchall()

    conn.close()

    content = render_template_string('''
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Penjualan Hari Ini</div>
            <div class="text-3xl font-bold text-indigo-600 mt-1">{{ today_sales }}</div>
            <div class="text-sm text-gray-400">transaksi</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Pendapatan Hari Ini</div>
            <div class="text-3xl font-bold text-green-600 mt-1">{{ r(today_income) }}</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Barang Terjual</div>
            <div class="text-3xl font-bold text-blue-600 mt-1">{{ today_items }}</div>
            <div class="text-sm text-gray-400">item</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Stok Menipis</div>
            <div class="text-3xl font-bold {{ 'text-red-500' if low_stock > 0 else 'text-gray-400' }} mt-1">{{ low_stock }}</div>
            <div class="text-sm text-gray-400">dari {{ total_products }} produk</div>
        </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <a href="/piutang" class="bg-white rounded-xl shadow p-6 hover:shadow-md transition">
            <div class="text-gray-500 text-sm">📝 Total Piutang</div>
            <div class="text-3xl font-bold {{ 'text-red-500' if total_piutang > 0 else 'text-gray-400' }} mt-1">{{ r(total_piutang) }}</div>
            <div class="text-sm text-gray-400">{{ piutang_count }} transaksi belum lunas</div>
        </a>
    </div>

    <!-- Stock Value Section -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">📦 Total Nilai Stok</div>
            <div class="text-3xl font-bold text-purple-600 mt-1">{{ r(stock_value) }}</div>
            <div class="text-sm text-gray-400">nilai inventory saat ini</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">📊 Total Item di Stok</div>
            <div class="text-3xl font-bold text-orange-500 mt-1">{{ stock_items }}</div>
            <div class="text-sm text-gray-400">pcs di semua gudang</div>
        </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="font-semibold text-gray-700 mb-4">📈 Bulan Ini</h3>
            <div class="space-y-3">
                <div class="flex justify-between"><span class="text-gray-500">Pemasukan</span><span class="text-green-600 font-semibold">{{ r(month_income) }}</span></div>
                <div class="flex justify-between"><span class="text-gray-500">Pengeluaran</span><span class="text-red-500 font-semibold">{{ r(month_expense) }}</span></div>
                <hr>
                <div class="flex justify-between font-bold"><span>Laba Bersih</span><span class="{{ 'text-green-600' if month_income - month_expense >= 0 else 'text-red-500' }}">{{ r(month_income - month_expense) }}</span></div>
            </div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="font-semibold text-gray-700 mb-4">🕐 Transaksi Terakhir</h3>
            {% if recent %}
            <div class="space-y-2">
                {% for t in recent %}
                <div class="flex justify-between items-center text-sm">
                    <span class="text-gray-600">#{{ t.id }} — {{ t.created_at[:16] }}</span>
                    <span class="font-semibold">{{ r(t.total) }}</span>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <p class="text-gray-400">Belum ada transaksi</p>
            {% endif %}
        </div>
    </div>

    <div class="flex gap-4 no-print">
        <a href="/kasir" class="bg-indigo-600 text-white px-6 py-3 rounded-lg hover:bg-indigo-700 font-semibold">💳 Buka Kasir</a>
        <a href="/products" class="bg-white text-indigo-600 border border-indigo-600 px-6 py-3 rounded-lg hover:bg-indigo-50 font-semibold">📦 Kelola Produk</a>
    </div>
    ''', today_sales=today_sales, today_income=today_income, today_items=today_items,
        total_products=total_products, low_stock=low_stock,
        stock_value=stock_value, stock_items=stock_items,
        month_income=month_income, month_expense=month_expense,
        recent=recent, r=rupiah, total_piutang=total_piutang, piutang_count=piutang_count)

    return render_template_string(LAYOUT, title="Dashboard", page="dashboard", content=content, now=now_str())


@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name = request.form["name"]
            price = int(request.form["price"])
            stock = int(request.form.get("stock", 0))
            conn.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", (name, price, stock))
            conn.commit()
            conn.close()
            return redirect(url_for("products"))

        elif action == "edit":
            pid = int(request.form["id"])
            name = request.form["name"]
            price = int(request.form["price"])
            conn.execute("UPDATE products SET name=?, price=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (name, price, pid))
            conn.commit()
            conn.close()
            return redirect(url_for("products"))

        elif action == "delete":
            pid = int(request.form["id"])
            conn.execute("DELETE FROM products WHERE id=?", (pid,))
            conn.commit()
            conn.close()
            return redirect(url_for("products"))

        elif action == "stock":
            pid = int(request.form["id"])
            qty = int(request.form["qty"])
            stype = request.form["stock_type"]
            if stype == "in":
                conn.execute("UPDATE products SET stock = stock + ?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (qty, pid))
            else:
                conn.execute("UPDATE products SET stock = MAX(0, stock - ?), updated_at=CURRENT_TIMESTAMP WHERE id=?", (qty, pid))
            conn.commit()
            conn.close()
            return redirect(url_for("products"))

    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()

    content = render_template_string('''
    <div class="flex justify-between items-center mb-6 no-print">
        <h2 class="text-lg font-semibold">Daftar Produk</h2>
        <div class="flex gap-2">
            <a href="/import" class="bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700">📥 Import CSV</a>
            <button onclick="document.getElementById('addModal').classList.remove('hidden')" class="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700">+ Tambah Produk</button>
        </div>
    </div>

    <div class="bg-white rounded-xl shadow overflow-hidden">
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Nama</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Harga</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Stok</th>
                    <th class="px-4 py-3 text-center text-sm font-semibold text-gray-600 no-print">Aksi</th>
                </tr>
<thead><tr class="border-b"><th class="text-left py-2">Nama</th><th class="text-right py-2">Harga Jual</th><th class="text-right py-2">HPP</th><th class="text-right py-2">Margin</th><th class="text-right py-2">Stok</th><th class="text-right py-2">Aksi</th></tr></thead>
                    <tbody>
                    {% for p in products %}
                    <tr class="border-b hover:bg-gray-50">
                        <td class="py-2 font-medium">{{ p.name }}</td>
                        <td class="py-2 text-right">{{ r(p.price) }}</td>
                        <td class="py-2 text-right text-gray-500">{{ r(p.cost_price or 0) }}</td>
                        <td class="py-2 text-right text-green-600">{{ r(p.price - (p.cost_price or 0)) }}</td>
                        <td class="py-2 text-right">
                            <span class="{{ 'text-red-500 font-bold' if p.stock <= 5 else '' }}">{{ p.stock }}</span>
                        </td>
                    <td class="px-4 py-3 text-center no-print">
                        <button onclick="editProduct({{ p.id }}, '{{ p.name }}', {{ p.price }})" class="text-blue-600 hover:underline text-sm mr-2">✏️ Edit</button>
                        <button onclick="stockProduct({{ p.id }}, '{{ p.name }}', {{ p.stock }})" class="text-green-600 hover:underline text-sm mr-2">📦 Stok</button>
                        <form method="POST" class="inline" onsubmit="return confirm('Hapus {{ p.name }}?')">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="id" value="{{ p.id }}">
                            <button type="submit" class="text-red-500 hover:underline text-sm">🗑️ Hapus</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <!-- Add Modal -->
    <div id="addModal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white rounded-xl p-6 w-96">
            <h3 class="text-lg font-semibold mb-4">Tambah Produk</h3>
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <div class="space-y-3">
                    <input name="name" placeholder="Nama produk" required class="w-full border rounded-lg px-3 py-2">
                    <input name="price" type="number" placeholder="Harga (Rp)" required class="w-full border rounded-lg px-3 py-2">
                    <input name="stock" type="number" value="0" placeholder="Stok awal" class="w-full border rounded-lg px-3 py-2">
                </div>
                <div class="flex gap-2 mt-4">
                    <button type="submit" class="flex-1 bg-indigo-600 text-white py-2 rounded-lg">Simpan</button>
                    <button type="button" onclick="document.getElementById('addModal').classList.add('hidden')" class="flex-1 bg-gray-200 py-2 rounded-lg">Batal</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Edit Modal -->
    <div id="editModal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white rounded-xl p-6 w-96">
            <h3 class="text-lg font-semibold mb-4">Edit Produk</h3>
            <form method="POST">
                <input type="hidden" name="action" value="edit">
                <input type="hidden" name="id" id="edit_id">
                <div class="space-y-3">
                    <input name="name" id="edit_name" placeholder="Nama produk" required class="w-full border rounded-lg px-3 py-2">
                    <input name="price" id="edit_price" type="number" placeholder="Harga (Rp)" required class="w-full border rounded-lg px-3 py-2">
                </div>
                <div class="flex gap-2 mt-4">
                    <button type="submit" class="flex-1 bg-indigo-600 text-white py-2 rounded-lg">Simpan</button>
                    <button type="button" onclick="document.getElementById('editModal').classList.add('hidden')" class="flex-1 bg-gray-200 py-2 rounded-lg">Batal</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Stock Modal -->
    <div id="stockModal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white rounded-xl p-6 w-96">
            <h3 class="text-lg font-semibold mb-2">Kelola Stok</h3>
            <p class="text-gray-500 text-sm mb-4" id="stock_info"></p>
            <form method="POST">
                <input type="hidden" name="action" value="stock">
                <input type="hidden" name="id" id="stock_id">
                <div class="space-y-3">
                    <select name="stock_type" class="w-full border rounded-lg px-3 py-2">
                        <option value="in">📥 Stok Masuk</option>
                        <option value="out">📤 Stok Keluar</option>
                    </select>
                    <input name="qty" type="number" min="1" value="1" placeholder="Jumlah" required class="w-full border rounded-lg px-3 py-2">
                </div>
                <div class="flex gap-2 mt-4">
                    <button type="submit" class="flex-1 bg-green-600 text-white py-2 rounded-lg">Proses</button>
                    <button type="button" onclick="document.getElementById('stockModal').classList.add('hidden')" class="flex-1 bg-gray-200 py-2 rounded-lg">Batal</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        function editProduct(id, name, price) {
            document.getElementById('edit_id').value = id;
            document.getElementById('edit_name').value = name;
            document.getElementById('edit_price').value = price;
            document.getElementById('editModal').classList.remove('hidden');
        }
        function stockProduct(id, name, stock) {
            document.getElementById('stock_id').value = id;
            document.getElementById('stock_info').textContent = name + ' (Stok: ' + stock + ')';
            document.getElementById('stockModal').classList.remove('hidden');
        }
    </script>
    ''', products=products, r=rupiah)

    return render_template_string(LAYOUT, title="Produk & Stok", page="products", content=content, now=now_str())


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    store_name = get_setting("store_name", "Toko Saya")
    store_address = get_setting("store_address", "")
    store_phone = get_setting("store_phone", "")
    store_footer = get_setting("store_footer", "Terima kasih atas kunjungan Anda!")
    tax_enabled = get_setting("tax_enabled", "off")
    tax_rate = get_setting("tax_rate", "11")

    if request.method == "POST":
        for key in ["store_name","store_address","store_phone","store_footer","tax_rate"]:
            if key in request.form:
                set_setting(key, request.form[key])
        set_setting("tax_enabled", "on" if request.form.get("tax_enabled") else "off")
        return redirect(url_for("settings"))

    store_name = get_setting("store_name", "Toko Saya")
    store_address = get_setting("store_address", "")
    store_phone = get_setting("store_phone", "")
    store_footer = get_setting("store_footer", "Terima kasih atas kunjungan Anda!")

    content = render_template_string('''
    <div class="max-w-2xl mx-auto">
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="text-lg font-semibold mb-6">🏪 Pengaturan Toko</h3>
            <form method="POST">
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Nama Toko</label>
                        <input name="store_name" value="{{ store_name }}" class="w-full border rounded-lg px-4 py-3 text-lg" placeholder="Nama tokomu">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Alamat</label>
                        <input name="store_address" value="{{ store_address }}" class="w-full border rounded-lg px-4 py-3" placeholder="Jl. Contoh No. 123, Kota">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">No. HP / WhatsApp</label>
                        <input name="store_phone" value="{{ store_phone }}" class="w-full border rounded-lg px-4 py-3" placeholder="08xxxxxxxxxx">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Footer Struk</label>
                        <input name="store_footer" value="{{ store_footer }}" class="w-full border rounded-lg px-4 py-3" placeholder="Pesan di bawah struk">
                    </div>
                </div>
                <hr class="my-6">
                <h4 class="font-semibold text-gray-700 mb-4">🧾 Pengaturan Pajak (PPN)</h4>
                <div class="space-y-4">
                    <div class="flex items-center gap-3">
                        <input type="checkbox" name="tax_enabled" id="taxToggle" {{ 'checked' if tax_enabled=='on' else '' }} class="w-5 h-5">
                        <label for="taxToggle" class="text-sm font-medium text-gray-700">Aktifkan PPN</label>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Tarif PPN (%)</label>
                        <input name="tax_rate" type="number" value="{{ tax_rate }}" min="0" max="100" class="w-full border rounded-lg px-4 py-3" placeholder="11">
                        <p class="text-xs text-gray-400 mt-1">Default: 11% (PPN Indonesia)</p>
                    </div>
                </div>
                <button type="submit" class="mt-6 w-full bg-indigo-600 text-white py-3 rounded-lg hover:bg-indigo-700 font-semibold">
                    💾 Simpan Pengaturan
                </button>
            </form>
        </div>

        <!-- Preview Struk -->
        <div class="bg-white rounded-xl shadow p-6 mt-6">
            <h3 class="text-lg font-semibold mb-4">👁️ Preview Struk</h3>
            <div class="border-2 border-dashed border-gray-300 rounded-lg p-6 max-w-sm mx-auto font-mono text-sm">
                <div class="text-center mb-4">
                    <div class="text-xl font-bold">{{ store_name }}</div>
                    {% if store_address %}<div class="text-xs">{{ store_address }}</div>{% endif %}
                    {% if store_phone %}<div class="text-xs">Telp: {{ store_phone }}</div>{% endif %}
                </div>
                <div class="border-t border-dashed my-2"></div>
                <div class="flex justify-between">
                    <span>Contoh Item x2</span>
                    <span>Rp 10.000</span>
                </div>
                <div class="flex justify-between">
                    <span>Contoh Item x1</span>
                    <span>Rp 5.000</span>
                </div>
                <div class="border-t border-dashed my-2"></div>
                <div class="flex justify-between font-bold">
                    <span>TOTAL</span>
                    <span>Rp 15.000</span>
                </div>
                <div class="flex justify-between text-xs mt-1">
                    <span>Bayar</span><span>Rp 20.000</span>
                </div>
                <div class="flex justify-between text-xs">
                    <span>Kembali</span><span>Rp 5.000</span>
                </div>
                <div class="border-t border-dashed my-2"></div>
                <div class="text-center text-xs mt-4">{{ store_footer }}</div>
            </div>
        </div>
    </div>
    ''', store_name=store_name, store_address=store_address,
        store_phone=store_phone, store_footer=store_footer)

    return render_template_string(LAYOUT, title="Pengaturan", page="settings", content=content, now=now_str())


@app.route("/import", methods=["GET", "POST"])
@login_required
def import_products():
    conn = get_db()
    result = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "upload_csv":
            file = request.files.get("file")
            if not file or not file.filename:
                result = ("error", "Pilih file CSV dulu!")
            else:
                try:
                    content = file.read().decode("utf-8-sig")  # handle BOM
                    reader = csv.DictReader(io.StringIO(content))

                    # Normalize headers (lowercase, strip spaces)
                    if reader.fieldnames:
                        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

                    imported = 0
                    skipped = 0
                    errors = []

                    for i, row in enumerate(reader, start=2):
                        try:
                            name = row.get("nama", row.get("name", "")).strip()
                            if not name:
                                skipped += 1
                                continue

                            price_str = row.get("harga", row.get("price", "0"))
                            price = int(str(price_str).replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip())

                            stock_str = row.get("stok", row.get("stock", "0"))
                            stock = int(str(stock_str).strip())

                            conn.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", (name, price, stock))
                            imported += 1
                        except Exception as e:
                            errors.append(f"Baris {i}: {e}")
                            skipped += 1

                    conn.commit()
                    result = ("success", f"✅ {imported} produk berhasil diimport! {f'({skipped} dilewati)' if skipped else ''}")
                    if errors:
                        result = ("warning", f"✅ {imported} produk imported, ⚠️ {len(errors)} error: {'; '.join(errors[:3])}")

                except Exception as e:
                    result = ("error", f"Gagal baca file: {e}")

        elif action == "paste_import":
            text = request.form.get("data", "")
            if not text.strip():
                result = ("error", "Data kosong!")
            else:
                try:
                    reader = csv.DictReader(io.StringIO(text))
                    if reader.fieldnames:
                        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

                    imported = 0
                    for i, row in enumerate(reader, start=2):
                        name = row.get("nama", row.get("name", "")).strip()
                        if not name:
                            continue
                        price_str = row.get("harga", row.get("price", "0"))
                        price = int(str(price_str).replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip())
                        stock_str = row.get("stok", row.get("stock", "0"))
                        stock = int(str(stock_str).strip())
                        conn.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", (name, price, stock))
                        imported += 1

                    conn.commit()
                    result = ("success", f"✅ {imported} produk berhasil diimport!")
                except Exception as e:
                    result = ("error", f"Format salah: {e}")

        elif action == "clear_all":
            conn.execute("DELETE FROM products")
            conn.commit()
            result = ("success", "🗑️ Semua produk dihapus!")

    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()

    content = render_template_string('''
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Upload CSV -->
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="text-lg font-semibold mb-4">📁 Upload File CSV</h3>
            <p class="text-sm text-gray-500 mb-4">Format: <code>nama,harga,stok</code> (atau <code>name,price,stock</code>)</p>

            <form method="POST" enctype="multipart/form-data">
                <input type="hidden" name="action" value="upload_csv">
                <div class="mb-4">
                    <input type="file" name="file" accept=".csv" class="w-full border rounded-lg px-3 py-2">
                </div>
                <button type="submit" class="w-full bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-700">📤 Upload & Import</button>
            </form>

            <div class="mt-4 pt-4 border-t">
                <a href="/template.csv" class="text-indigo-600 hover:underline text-sm">📥 Download Template CSV</a>
            </div>
        </div>

        <!-- Paste Data -->
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="text-lg font-semibold mb-4">📋 Paste Data Langsung</h3>
            <p class="text-sm text-gray-500 mb-4">Copy dari Excel/Google Sheets, paste di sini</p>

            <form method="POST">
                <input type="hidden" name="action" value="paste_import">
                <textarea name="data" rows="8" class="w-full border rounded-lg px-3 py-2 font-mono text-sm" placeholder="nama,harga,stok
Indomie Goreng,3500,100
Aqua 600ml,3000,50
Teh Botol Sosro,4500,60"></textarea>
                <button type="submit" class="w-full bg-green-600 text-white py-2 rounded-lg hover:bg-green-700 mt-3">📥 Import Data</button>
            </form>
        </div>
    </div>

    {% if result %}
    <div class="mt-4 p-4 rounded-lg {{ 'bg-green-100 text-green-800' if result[0]=='success' else 'bg-red-100 text-red-800' if result[0]=='error' else 'bg-yellow-100 text-yellow-800' }}">
        {{ result[1] }}
    </div>
    {% endif %}

    <!-- Current Products Count -->
    <div class="mt-6 bg-white rounded-xl shadow p-4 flex justify-between items-center">
        <span class="text-gray-600">📦 Total produk saat ini: <strong>{{ products|length }}</strong></span>
        <form method="POST" onsubmit="return confirm('HAPUS SEMUA PRODUK? Ini tidak bisa dibatalkan!')">
            <input type="hidden" name="action" value="clear_all">
            <button type="submit" class="text-red-500 hover:underline text-sm">🗑️ Hapus Semua</button>
        </form>
    </div>

    {% if result and result[0] == 'success' %}
    <script>showToast('{{ result[1] }}', 'success');</script>
    {% endif %}
    ''', result=result, products=products)

    return render_template_string(LAYOUT, title="Import Produk", page="products", content=content, now=now_str())


@app.route("/template.csv")
def template_csv():
    template = "nama,harga,stok\nIndomie Goreng,3500,100\nAqua 600ml,3000,50\nTeh Botol Sosro,4500,60\n"
    return Response(
        template,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=template_produk.csv"}
    )


@app.route("/kasir", methods=["GET", "POST"])
@login_required
def kasir():
    conn = get_db()

    if request.method == "POST":
        data = json.loads(request.form.get("cart", "[]"))
        payment = int(request.form.get("payment", 0))
        discount = int(request.form.get("discount", 0))
        discount_type = request.form.get("discount_type", "rupiah")
        customer_id = request.form.get("customer_id", "")
        is_debt = 1 if request.form.get("is_debt") else 0

        if not data:
            conn.close()
            return redirect(url_for("kasir"))

        subtotal = sum(item["price"] * item["qty"] for item in data)

        # Apply discount
        if discount_type == "percent":
            disc_amount = subtotal * discount // 100
        else:
            disc_amount = discount
        after_discount = max(0, subtotal - disc_amount)

        # Apply tax
        tax_enabled = get_setting("tax_enabled", "off")
        tax_rate = int(get_setting("tax_rate", "11"))
        tax_amount = 0
        if tax_enabled == "on":
            tax_amount = after_discount * tax_rate // 100

        total = after_discount + tax_amount
        change = max(0, payment - total)

        if is_debt:
            change = 0
            payment = 0

        # Create transaction
        uid = session.get("user_id")
        cid = int(customer_id) if customer_id else None
        cur = conn.execute(
            "INSERT INTO transactions (total, payment, change_amount, discount, discount_type, tax_amount, user_id, customer_id, is_debt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (total, payment, change, disc_amount, discount_type, tax_amount, uid, cid, is_debt)
        )
        tid = cur.lastrowid

        # Add items & reduce stock
        for item in data:
            conn.execute(
                "INSERT INTO transaction_items (transaction_id, product_id, product_name, quantity, price, subtotal) VALUES (?, ?, ?, ?, ?, ?)",
                (tid, item["id"], item["name"], item["qty"], item["price"], item["price"] * item["qty"])
            )
            conn.execute(
                "UPDATE products SET stock = MAX(0, stock - ?), updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (item["qty"], item["id"])
            )

        # Auto-record income in finance
        conn.execute(
            "INSERT INTO finance (type, amount, description, category) VALUES ('income', ?, ?, 'penjualan')",
            (total, f"Penjualan #{tid}")
        )

        # Create debt record if hutang
        if is_debt and cid:
            conn.execute(
                "INSERT INTO debts (customer_id, transaction_id, total_amount, paid_amount, remaining, status) VALUES (?, ?, ?, 0, ?, 'unpaid')",
                (cid, tid, total, total)
            )

        conn.commit()
        conn.close()

        return redirect(url_for("receipt", tid=tid))

    products = conn.execute("SELECT * FROM products WHERE stock > 0 ORDER BY name").fetchall()
    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    tax_enabled = get_setting('tax_enabled', 'off')
    tax_rate = int(get_setting('tax_rate', '11'))
    conn.close()

    content = render_template_string('''
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Product Selection -->
        <div class="lg:col-span-2">
            <div class="bg-white rounded-xl shadow p-4 mb-4">
                <input type="text" id="search" placeholder="🔍 Cari produk..." class="w-full border rounded-lg px-4 py-2 text-lg" oninput="filterProducts()">
            </div>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-3" id="productGrid">
                {% for p in products %}
                <button onclick="addToCart({{ p.id }}, '{{ p.name }}', {{ p.price }}, {{ p.stock }})"
                    class="product-card bg-white rounded-xl shadow p-4 hover:shadow-md transition text-left"
                    data-name="{{ p.name|lower }}">
                    <div class="font-semibold text-sm mb-1">{{ p.name }}</div>
                    <div class="text-indigo-600 font-bold">{{ r(p.price) }}</div>
                    <div class="text-xs text-gray-400">Stok: {{ p.stock }}</div>
                </button>
                {% endfor %}
            </div>
        </div>

        <!-- Cart -->
        <div class="bg-white rounded-xl shadow p-4 sticky top-4">
            <h3 class="font-semibold text-lg mb-3">🛒 Keranjang</h3>
            <div id="cartItems" class="space-y-2 mb-4 max-h-64 overflow-y-auto">
                <p class="text-gray-400 text-sm" id="emptyCart">Keranjang kosong</p>
            </div>
            <hr class="my-3">
            <div class="flex justify-between text-lg font-bold mb-4">
                <span>Total</span>
                <span id="cartTotal" class="text-indigo-600">Rp 0</span>
            </div>
            <form method="POST" id="checkoutForm" onsubmit="return prepareCheckout()">
                <input type="hidden" name="cart" id="cartData">
                <div class="mb-3">
                    <label class="text-sm text-gray-600">Diskon</label>
                    <div class="flex gap-2">
                        <input type="number" name="discount" id="discountInput" min="0" value="0" class="flex-1 border rounded-lg px-3 py-2" placeholder="0" oninput="calcTotal()">
                        <select name="discount_type" id="discountType" class="border rounded-lg px-2 py-2 text-sm" onchange="calcTotal()">
                            <option value="rupiah">Rp</option>
                            <option value="percent">%</option>
                        </select>
                    </div>
                </div>
                <div class="mb-3">
                    <label class="text-sm text-gray-600">Pelanggan (opsional)</label>
                    <select name="customer_id" id="customerSelect" class="w-full border rounded-lg px-3 py-2 text-sm" onchange="calcChange()">
                        <option value="">-- Umum --</option>
                        {% for c in customers %}<option value="{{ c.id }}">{{ c.name }}{% if c.phone %} ({{ c.phone }}){% endif %}</option>{% endfor %}
                    </select>
                </div>
                <div class="mb-3 flex items-center gap-2">
                    <input type="checkbox" name="is_debt" id="isDebt" class="w-4 h-4">
                    <label for="isDebt" class="text-sm text-gray-600">📝 Bayar Nanti (Hutang)</label>
                </div>
                <div class="mb-3">
                    <label class="text-sm text-gray-600">Uang Bayar</label>
                    <input type="number" name="payment" id="paymentInput" min="0" class="w-full border rounded-lg px-3 py-2 text-lg" placeholder="0" oninput="calcChange()">
                </div>
                <div class="space-y-1 text-sm mb-3" id="summarySection" style="display:none">
                    <div class="flex justify-between"><span class="text-gray-500">Subtotal</span><span id="summSubtotal">Rp 0</span></div>
                    <div class="flex justify-between" id="summDiscRow"><span class="text-gray-500">Diskon</span><span id="summDiscount" class="text-red-500">- Rp 0</span></div>
                    <div class="flex justify-between" id="summTaxRow" style="display:none"><span class="text-gray-500">PPN</span><span id="summTax">Rp 0</span></div>
                    <div class="flex justify-between font-bold text-lg"><span>Total</span><span id="summTotal" class="text-indigo-600">Rp 0</span></div>
                </div>
                <div class="flex justify-between text-sm mb-4" id="changeRow" style="display:none">
                    <span class="text-gray-500">Kembalian</span>
                    <span id="changeAmount" class="font-semibold text-green-600">Rp 0</span>
                </div>
                <button type="submit" id="payBtn" disabled class="w-full bg-indigo-600 text-white py-3 rounded-lg font-semibold text-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-indigo-700">
                    💵 Bayar
                </button>
            </form>
            <button onclick="clearCart()" class="w-full mt-2 text-sm text-red-500 hover:underline">🗑️ Kosongkan Keranjang</button>
        </div>
    </div>

    <script>
        let cart = [];

        function addToCart(id, name, price, maxStock) {
            const existing = cart.find(i => i.id === id);
            if (existing) {
                if (existing.qty >= maxStock) { showToast('Stok tidak cukup!', 'error'); return; }
                existing.qty++;
            } else {
                cart.push({ id, name, price, qty: 1, maxStock });
            }
            renderCart();
        }

        function updateQty(id, delta) {
            const item = cart.find(i => i.id === id);
            if (!item) return;
            item.qty += delta;
            if (item.qty <= 0) cart = cart.filter(i => i.id !== id);
            if (item.qty > item.maxStock) { item.qty = item.maxStock; showToast('Stok tidak cukup!', 'error'); }
            renderCart();
        }

        function removeItem(id) {
            cart = cart.filter(i => i.id !== id);
            renderCart();
        }

        function clearCart() {
            cart = [];
            renderCart();
        }

        function renderCart() {
            const container = document.getElementById('cartItems');
            const empty = document.getElementById('emptyCart');
            const totalEl = document.getElementById('cartTotal');

            if (cart.length === 0) {
                container.innerHTML = '<p class="text-gray-400 text-sm" id="emptyCart">Keranjang kosong</p>';
                totalEl.textContent = 'Rp 0';
                document.getElementById('payBtn').disabled = true;
                return;
            }

            let html = '';
            let total = 0;
            cart.forEach(item => {
                const sub = item.price * item.qty;
                total += sub;
                html += `
                <div class="flex items-center justify-between text-sm">
                    <div class="flex-1">
                        <div class="font-medium">${item.name}</div>
                        <div class="text-gray-400">${formatRupiah(item.price)} × ${item.qty}</div>
                    </div>
                    <div class="flex items-center gap-2">
                        <button onclick="updateQty(${item.id}, -1)" class="w-6 h-6 bg-gray-200 rounded text-center">-</button>
                        <span class="w-6 text-center">${item.qty}</span>
                        <button onclick="updateQty(${item.id}, 1)" class="w-6 h-6 bg-gray-200 rounded text-center">+</button>
                        <span class="w-20 text-right font-semibold">${formatRupiah(sub)}</span>
                        <button onclick="removeItem(${item.id})" class="text-red-400 hover:text-red-600">×</button>
                    </div>
                </div>`;
            });
            container.innerHTML = html;
            totalEl.textContent = formatRupiah(total);
            document.getElementById('payBtn').disabled = false;
            calcTotal();
            calcChange();
        }

        function getFinalTotal() {
            const subtotal = cart.reduce((s, i) => s + i.price * i.qty, 0);
            const discVal = parseInt(document.getElementById('discountInput').value) || 0;
            const discType = document.getElementById('discountType').value;
            const disc = discType === 'percent' ? Math.floor(subtotal * discVal / 100) : discVal;
            const afterDisc = Math.max(0, subtotal - disc);
            const taxEnabled = {{ 'true' if tax_enabled == 'on' else 'false' }};
            const taxRate = {{ tax_rate }};
            const tax = taxEnabled ? Math.floor(afterDisc * taxRate / 100) : 0;
            return { subtotal, disc, afterDisc, tax, total: afterDisc + tax, taxEnabled };
        }

        function calcTotal() {
            const f = getFinalTotal();
            const summ = document.getElementById('summarySection');
            if (cart.length === 0) { summ.style.display = 'none'; return; }
            summ.style.display = 'block';
            document.getElementById('summSubtotal').textContent = formatRupiah(f.subtotal);
            document.getElementById('summDiscount').textContent = '- ' + formatRupiah(f.disc);
            document.getElementById('summDiscRow').style.display = f.disc > 0 ? 'flex' : 'none';
            document.getElementById('summTaxRow').style.display = f.taxEnabled ? 'flex' : 'none';
            document.getElementById('summTax').textContent = formatRupiah(f.tax);
            document.getElementById('summTotal').textContent = formatRupiah(f.total);
            calcChange();
        }

        function calcChange() {
            const f = getFinalTotal();
            const isDebt = document.getElementById('isDebt').checked;
            const payment = parseInt(document.getElementById('paymentInput').value) || 0;
            const change = payment - f.total;
            const payInput = document.getElementById('paymentInput');
            const row = document.getElementById('changeRow');
            if (isDebt) {
                payInput.disabled = true; payInput.value = '';
                row.style.display = 'none';
                document.getElementById('payBtn').disabled = cart.length === 0 || !document.getElementById('customerSelect').value;
                return;
            } else {
                payInput.disabled = false;
            }
            if (payment > 0) {
                row.style.display = 'flex';
                document.getElementById('changeAmount').textContent = formatRupiah(Math.max(0, change));
                document.getElementById('changeAmount').className = change >= 0 ? 'font-semibold text-green-600' : 'font-semibold text-red-500';
            } else {
                row.style.display = 'none';
            }
            document.getElementById('payBtn').disabled = cart.length === 0 || change < 0;
        }

        function prepareCheckout() {
            if (cart.length === 0) return false;
            const f = getFinalTotal();
            const isDebt = document.getElementById('isDebt').checked;
            if (!isDebt) {
                const payment = parseInt(document.getElementById('paymentInput').value) || 0;
                if (payment < f.total) { showToast('Uang kurang!', 'error'); return false; }
            }
            if (isDebt && !document.getElementById('customerSelect').value) { showToast('Pilih pelanggan untuk hutang!', 'error'); return false; }
            document.getElementById('cartData').value = JSON.stringify(cart);
            return true;
        }

        document.getElementById('isDebt').addEventListener('change', calcChange);
        document.getElementById('discountInput').addEventListener('input', calcTotal);
        document.getElementById('discountType').addEventListener('change', calcTotal);

        function filterProducts() {
            const q = document.getElementById('search').value.toLowerCase();
            document.querySelectorAll('.product-card').forEach(card => {
                card.style.display = card.dataset.name.includes(q) ? '' : 'none';
            });
        }
    </script>
    ''', products=products, customers=customers, r=rupiah, tax_enabled=tax_enabled, tax_rate=tax_rate)

    return render_template_string(LAYOUT, title="Kasir (POS)", page="kasir", content=content, now=now_str())


@app.route("/receipt/<int:tid>")
@login_required
def receipt(tid):
    conn = get_db()
    trx = conn.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if not trx:
        conn.close()
        return "Transaksi tidak ditemukan", 404

    items = conn.execute("SELECT * FROM transaction_items WHERE transaction_id=?", (tid,)).fetchall()

    # Get store settings
    store_name = conn.execute("SELECT value FROM settings WHERE key='store_name'").fetchone()
    store_name = store_name["value"] if store_name else "Kasir App"
    store_address = conn.execute("SELECT value FROM settings WHERE key='store_address'").fetchone()
    store_address = store_address["value"] if store_address else ""
    store_phone = conn.execute("SELECT value FROM settings WHERE key='store_phone'").fetchone()
    store_phone = store_phone["value"] if store_phone else ""
    store_footer = conn.execute("SELECT value FROM settings WHERE key='store_footer'").fetchone()
    store_footer = store_footer["value"] if store_footer else "Terima kasih atas kunjungan Anda!"

    # Get cashier name
    cashier_name = ""
    if trx["user_id"]:
        u = conn.execute("SELECT name FROM users WHERE id=?", (trx["user_id"],)).fetchone()
        cashier_name = u["name"] if u else ""

    # Get customer name
    customer_name = ""
    if trx["customer_id"]:
        c = conn.execute("SELECT name FROM customers WHERE id=?", (trx["customer_id"],)).fetchone()
        customer_name = c["name"] if c else ""

    conn.close()

    # Calculate subtotal (before discount/tax)
    subtotal = sum(i["subtotal"] for i in items)
    disc_amount = trx["discount"] or 0
    if trx.get("discount_type") == "percent":
        disc_amount = subtotal * (trx["discount"] or 0) // 100

    content = render_template_string('''
    <div class="max-w-md mx-auto bg-white rounded-xl shadow p-6" id="receiptArea">
        <div class="text-center mb-4">
            <h2 class="text-xl font-bold">{{ store_name }}</h2>
            {% if store_address %}<p class="text-xs text-gray-500">{{ store_address }}</p>{% endif %}
            {% if store_phone %}<p class="text-xs text-gray-500">Telp: {{ store_phone }}</p>{% endif %}
        </div>
        <div class="text-xs text-gray-500 mb-3">
            <div>No: #{{ trx.id }}</div>
            <div>Tgl: {{ trx.created_at }}</div>
            {% if cashier_name %}<div>Kasir: {{ cashier_name }}</div>{% endif %}
            {% if customer_name %}<div>Pelanggan: {{ customer_name }}</div>{% endif %}
        </div>
        <div class="border-t border-dashed border-gray-400 my-2"></div>
        {% for item in items %}
        <div class="flex justify-between text-sm mb-1">
            <span>{{ item.product_name }} × {{ item.quantity }}</span>
            <span>{{ r(item.subtotal) }}</span>
        </div>
        {% endfor %}
        <div class="border-t border-dashed border-gray-400 my-2"></div>
        <div class="flex justify-between text-sm">
            <span>Subtotal</span><span>{{ r(subtotal) }}</span>
        </div>
        {% if trx.discount and trx.discount > 0 %}
        <div class="flex justify-between text-sm">
            <span>Diskon{% if trx.discount_type == 'percent' %} ({{ trx.discount }}%){% endif %}</span>
            <span class="text-red-500">- {{ r(disc_amount) }}</span>
        </div>
        {% endif %}
        {% if trx.tax_amount and trx.tax_amount > 0 %}
        <div class="flex justify-between text-sm">
            <span>PPN</span><span>{{ r(trx.tax_amount) }}</span>
        </div>
        {% endif %}
        <div class="flex justify-between font-bold text-lg">
            <span>TOTAL</span>
            <span>{{ r(trx.total) }}</span>
        </div>
        {% if trx.is_debt %}
        <div class="flex justify-between text-sm text-red-500 font-semibold">
            <span>STATUS</span><span>📝 BELUM LUNAS</span>
        </div>
        {% else %}
        <div class="flex justify-between text-sm mt-1">
            <span>Bayar</span><span>{{ r(trx.payment) }}</span>
        </div>
        <div class="flex justify-between text-sm">
            <span>Kembalian</span><span>{{ r(trx.change_amount) }}</span>
        </div>
        {% endif %}
        <div class="border-t border-dashed border-gray-400 my-2"></div>
        <p class="text-center text-xs text-gray-500 mt-4">{{ store_footer }}</p>
    </div>
    <div class="flex gap-4 mt-6 justify-center no-print">
        <button onclick="window.print()" class="bg-indigo-600 text-white px-6 py-2 rounded-lg">🖨️ Cetak</button>
        <a href="/kasir" class="bg-gray-200 px-6 py-2 rounded-lg">← Kembali</a>
    </div>
    ''', trx=trx, items=items, r=rupiah,
        store_name=store_name, store_address=store_address,
        store_phone=store_phone, store_footer=store_footer,
        cashier_name=cashier_name, customer_name=customer_name,
        subtotal=subtotal, disc_amount=disc_amount)

    return render_template_string(LAYOUT, title=f"Struk #{tid}", page="kasir", content=content, now=now_str())


@app.route("/transaction/delete/<int:tid>", methods=["POST"])
@login_required
def delete_transaction(tid):
    if session.get("user_role") != "admin":
        return "Akses ditolak", 403
    conn = get_db()
    trx = conn.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if trx:
        items = conn.execute("SELECT * FROM transaction_items WHERE transaction_id=?", (tid,)).fetchall()
        for item in items:
            conn.execute("UPDATE products SET stock = stock + ?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (item["quantity"], item["product_id"]))
        conn.execute("DELETE FROM transaction_items WHERE transaction_id=?", (tid,))
        conn.execute("DELETE FROM finance WHERE description LIKE ? AND category='penjualan'", (f"%Penjualan #{tid}",))
        conn.execute("DELETE FROM debts WHERE transaction_id=?", (tid,))
        conn.execute("DELETE FROM returns WHERE transaction_id=?", (tid,))
        conn.execute("DELETE FROM transactions WHERE id=?", (tid,))
        conn.commit()
    conn.close()
    return redirect(url_for("penjualan"))

@app.route("/transaction/edit/<int:tid>", methods=["GET", "POST"])
@login_required
def edit_transaction(tid):
    conn = get_db()
    trx = conn.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if not trx:
        conn.close()
        return redirect(url_for("penjualan"))
    items = conn.execute("SELECT * FROM transaction_items WHERE transaction_id=?", (tid,)).fetchall()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_item":
            item_id = int(request.form.get("item_id", 0))
            new_qty = int(request.form.get("quantity", 1))
            item = conn.execute("SELECT * FROM transaction_items WHERE id=?", (item_id,)).fetchone()
            if item and new_qty > 0:
                qty_diff = new_qty - item["quantity"]
                new_subtotal = item["price"] * new_qty
                conn.execute("UPDATE transaction_items SET quantity=?, subtotal=? WHERE id=?", (new_qty, new_subtotal, item_id))
                conn.execute("UPDATE products SET stock = MAX(0, stock - ?), updated_at=CURRENT_TIMESTAMP WHERE id=?", (qty_diff, item["product_id"]))
                all_items = conn.execute("SELECT * FROM transaction_items WHERE transaction_id=?", (tid,)).fetchall()
                new_total = sum(i["subtotal"] for i in all_items)
                conn.execute("UPDATE transactions SET total=?, change_amount=MAX(0, payment-?) WHERE id=?", (new_total, new_total, tid))
                conn.execute("UPDATE finance SET amount=? WHERE description LIKE ? AND category='penjualan'", (new_total, f"%Penjualan #{tid}"))
                conn.commit()
        return redirect(url_for("edit_transaction", tid=tid))

    subtotal = sum(i["subtotal"] for i in items)
    conn.close()

    content = render_template_string('''
    <div class="max-w-2xl mx-auto">
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="text-lg font-semibold mb-4">✏️ Edit Transaksi #{{ trx.id }}</h3>
            <div class="text-sm text-gray-500 mb-4">{{ trx.created_at }}</div>
            <div class="space-y-3">
                {% for item in items %}
                <div class="flex items-center justify-between border-b pb-3">
                    <div>
                        <div class="font-medium">{{ item.product_name }}</div>
                        <div class="text-sm text-gray-500">{{ r(item.price) }} × {{ item.quantity }} = {{ r(item.subtotal) }}</div>
                    </div>
                    <form method="POST" class="flex gap-2 items-center">
                        <input type="hidden" name="action" value="update_item">
                        <input type="hidden" name="item_id" value="{{ item.id }}">
                        <input type="number" name="quantity" value="{{ item.quantity }}" min="1" class="w-20 border rounded px-2 py-1 text-sm">
                        <button type="submit" class="text-blue-500 hover:underline text-sm">Update</button>
                    </form>
                </div>
                {% endfor %}
            </div>
            <div class="mt-6 pt-4 border-t">
                <div class="flex justify-between text-lg font-bold">
                    <span>Total</span><span>{{ r(trx.total) }}</span>
                </div>
            </div>
            <div class="mt-6 flex gap-4">
                <a href="/penjualan" class="bg-gray-200 px-6 py-2 rounded-lg">← Kembali</a>
                <a href="/receipt/{{ trx.id }}" class="bg-indigo-600 text-white px-6 py-2 rounded-lg">🖨️ Struk</a>
            </div>
        </div>
    </div>
    ''', trx=trx, items=items, subtotal=subtotal, r=rupiah)
    return render_template_string(LAYOUT, title=f"Edit #{tid}", page="penjualan", content=content, now=now_str())

@app.route("/penjualan")
@login_required
def penjualan():
    conn = get_db()

    # Date filter
    start = request.args.get("start", datetime.now().strftime("%Y-%m-%d"))
    end = request.args.get("end", datetime.now().strftime("%Y-%m-%d"))
    period = request.args.get("period", "")

    if period == "today":
        start = end = datetime.now().strftime("%Y-%m-%d")
    elif period == "week":
        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
    elif period == "month":
        start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")

    transactions = conn.execute("""
        SELECT * FROM transactions WHERE DATE(created_at) BETWEEN ? AND ? ORDER BY created_at DESC
    """, (start, end)).fetchall()

    stats = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(total),0) as total
        FROM transactions WHERE DATE(created_at) BETWEEN ? AND ?
    """, (start, end)).fetchone()

    items_sold = conn.execute("""
        SELECT COALESCE(SUM(ti.quantity),0) as qty
        FROM transaction_items ti JOIN transactions t ON t.id=ti.transaction_id
        WHERE DATE(t.created_at) BETWEEN ? AND ?
    """, (start, end)).fetchone()["qty"]

    conn.close()

    content = render_template_string('''
    <!-- Filters -->
    <div class="bg-white rounded-xl shadow p-4 mb-6 no-print">
        <form method="GET" class="flex flex-wrap gap-3 items-end">
            <div>
                <label class="text-sm text-gray-500">Dari</label>
                <input type="date" name="start" value="{{ start }}" class="border rounded-lg px-3 py-2">
            </div>
            <div>
                <label class="text-sm text-gray-500">Sampai</label>
                <input type="date" name="end" value="{{ end }}" class="border rounded-lg px-3 py-2">
            </div>
            <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded-lg">Filter</button>
            <a href="?period=today" class="bg-gray-100 px-3 py-2 rounded-lg text-sm">Hari Ini</a>
            <a href="?period=week" class="bg-gray-100 px-3 py-2 rounded-lg text-sm">7 Hari</a>
            <a href="?period=month" class="bg-gray-100 px-3 py-2 rounded-lg text-sm">Bulan Ini</a>
        </form>
    </div>

    <!-- Export -->
    <div class="flex gap-3 mb-4 no-print">
        <a href="/export/penjualan?start={{ start }}&end={{ end }}" class="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700">📥 Export Penjualan CSV</a>
        <a href="/export/pembukuan?start={{ start }}&end={{ end }}" class="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700">📊 Export Pembukuan CSV</a>
    </div>

    <!-- Stats -->
    <div class="grid grid-cols-3 gap-4 mb-6">
        <div class="bg-white rounded-xl shadow p-4 text-center">
            <div class="text-2xl font-bold text-indigo-600">{{ stats.count }}</div>
            <div class="text-sm text-gray-500">Transaksi</div>
        </div>
        <div class="bg-white rounded-xl shadow p-4 text-center">
            <div class="text-2xl font-bold text-green-600">{{ r(stats.total) }}</div>
            <div class="text-sm text-gray-500">Total Penjualan</div>
        </div>
        <div class="bg-white rounded-xl shadow p-4 text-center">
            <div class="text-2xl font-bold text-blue-600">{{ items_sold }}</div>
            <div class="text-sm text-gray-500">Item Terjual</div>
        </div>
    </div>

    <!-- Table -->
    <div class="bg-white rounded-xl shadow overflow-hidden">
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">#</th>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Waktu</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Total</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Bayar</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Kembali</th>
                    <th class="px-4 py-3 text-center text-sm font-semibold text-gray-600 no-print">Aksi</th>
                </tr>
            </thead>
            <tbody class="divide-y">
                {% for t in transactions %}
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3"><a href="/receipt/{{ t.id }}" class="text-indigo-600 hover:underline">#{{ t.id }}</a></td>
                    <td class="px-4 py-3 text-sm">{{ t.created_at }}</td>
                    <td class="px-4 py-3 text-right font-semibold">{{ r(t.total) }}</td>
                    <td class="px-4 py-3 text-right">{{ r(t.payment) }}</td>
                    <td class="px-4 py-3 text-right">{{ r(t.change_amount) }}</td>
                    <td class="px-4 py-3 text-center no-print">
                        <a href="/transaction/edit/{{ t.id }}" class="text-blue-500 hover:underline text-sm mr-2">✏️</a>
                        {% if session.get('user_role') == 'admin' %}
                        <form method="POST" action="/transaction/delete/{{ t.id }}" style="display:inline" onsubmit="return confirm('Hapus transaksi #{{ t.id }}? Stok akan dikembalikan.')">
                            <button type="submit" class="text-red-500 hover:underline text-sm">🗑️</button>
                        </form>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
                {% if not transactions %}
                <tr><td colspan="6" class="px-4 py-8 text-center text-gray-400">Tidak ada transaksi</td></tr>
                {% endif %}
            </tbody>
        </table>
    </div>
    ''', transactions=transactions, stats=stats, items_sold=items_sold, start=start, end=end, r=rupiah)

    return render_template_string(LAYOUT, title="Riwayat Penjualan", page="penjualan", content=content, now=now_str())


@app.route("/pembukuan", methods=["GET", "POST"])
@login_required
def pembukuan():
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            ftype = request.form["type"]
            amount = int(request.form["amount"])
            desc = request.form.get("description", "")
            cat = request.form.get("category", "")
            conn.execute(
                "INSERT INTO finance (type, amount, description, category) VALUES (?, ?, ?, ?)",
                (ftype, amount, desc, cat)
            )
            conn.commit()

        elif action == "delete":
            fid = int(request.form["id"])
            conn.execute("DELETE FROM finance WHERE id=?", (fid,))
            conn.commit()

        conn.close()
        return redirect(url_for("pembukuan"))

    # Filters
    start = request.args.get("start", datetime.now().replace(day=1).strftime("%Y-%m-%d"))
    end = request.args.get("end", datetime.now().strftime("%Y-%m-%d"))
    period = request.args.get("period", "")

    if period == "today":
        start = end = datetime.now().strftime("%Y-%m-%d")
    elif period == "month":
        start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
    elif period == "year":
        start = datetime.now().replace(month=1, day=1).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")

    records = conn.execute("""
        SELECT * FROM finance WHERE DATE(created_at) BETWEEN ? AND ? ORDER BY created_at DESC
    """, (start, end)).fetchall()

    income_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM finance WHERE type='income' AND DATE(created_at) BETWEEN ? AND ?",
        (start, end)
    ).fetchone()["s"]

    expense_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM finance WHERE type='expense' AND DATE(created_at) BETWEEN ? AND ?",
        (start, end)
    ).fetchone()["s"]

    # Categories breakdown
    categories = conn.execute("""
        SELECT category, type, SUM(amount) as total FROM finance
        WHERE DATE(created_at) BETWEEN ? AND ? AND category != ''
        GROUP BY category, type ORDER BY total DESC
    """, (start, end)).fetchall()

    conn.close()

    content = render_template_string('''
    <!-- Filters -->
    <div class="bg-white rounded-xl shadow p-4 mb-6 no-print">
        <form method="GET" class="flex flex-wrap gap-3 items-end">
            <div>
                <label class="text-sm text-gray-500">Dari</label>
                <input type="date" name="start" value="{{ start }}" class="border rounded-lg px-3 py-2">
            </div>
            <div>
                <label class="text-sm text-gray-500">Sampai</label>
                <input type="date" name="end" value="{{ end }}" class="border rounded-lg px-3 py-2">
            </div>
            <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded-lg">Filter</button>
            <a href="?period=today" class="bg-gray-100 px-3 py-2 rounded-lg text-sm">Hari Ini</a>
            <a href="?period=month" class="bg-gray-100 px-3 py-2 rounded-lg text-sm">Bulan Ini</a>
            <a href="?period=year" class="bg-gray-100 px-3 py-2 rounded-lg text-sm">Tahun Ini</a>
        </form>
    </div>

    <!-- Summary Cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div class="bg-white rounded-xl shadow p-6 text-center">
            <div class="text-sm text-gray-500 mb-1">📥 Pemasukan</div>
            <div class="text-3xl font-bold text-green-600">{{ r(income) }}</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6 text-center">
            <div class="text-sm text-gray-500 mb-1">📤 Pengeluaran</div>
            <div class="text-3xl font-bold text-red-500">{{ r(expense) }}</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6 text-center">
            <div class="text-sm text-gray-500 mb-1">💰 Laba Bersih</div>
            <div class="text-3xl font-bold {{ 'text-green-600' if profit >= 0 else 'text-red-500' }}">{{ r(profit) }}</div>
        </div>
    </div>

    <!-- Add Entry -->
    <div class="bg-white rounded-xl shadow p-4 mb-6 no-print">
        <h3 class="font-semibold mb-3">+ Tambah Catatan</h3>
        <form method="POST" class="flex flex-wrap gap-3 items-end">
            <input type="hidden" name="action" value="add">
            <select name="type" class="border rounded-lg px-3 py-2">
                <option value="income">📥 Pemasukan</option>
                <option value="expense">📤 Pengeluaran</option>
            </select>
            <input name="amount" type="number" min="1" placeholder="Jumlah (Rp)" required class="border rounded-lg px-3 py-2">
            <input name="description" placeholder="Keterangan" class="border rounded-lg px-3 py-2 flex-1 min-w-[200px]">
            <select name="category" class="border rounded-lg px-3 py-2">
                <option value="">-- Kategori --</option>
                <option value="penjualan">Penjualan</option>
                <option value="restocking">Restocking</option>
                <option value="operasional">Operasional</option>
                <option value="listrik">Listrik</option>
                <option value="sewa">Sewa</option>
                <option value="lainnya">Lainnya</option>
            </select>
            <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded-lg">Simpan</button>
        </form>
    </div>

    <!-- Records Table -->
    <div class="bg-white rounded-xl shadow overflow-hidden">
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Tanggal</th>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Tipe</th>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Keterangan</th>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Kategori</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Jumlah</th>
                    <th class="px-4 py-3 text-center text-sm font-semibold text-gray-600 no-print">Aksi</th>
                </tr>
            </thead>
            <tbody class="divide-y">
                {% for rec in records %}
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3 text-sm">{{ rec.created_at[:10] }}</td>
                    <td class="px-4 py-3">
                        <span class="px-2 py-1 rounded text-xs font-semibold {{ 'bg-green-100 text-green-700' if rec.type=='income' else 'bg-red-100 text-red-700' }}">
                            {{ '📥 Masuk' if rec.type=='income' else '📤 Keluar' }}
                        </span>
                    </td>
                    <td class="px-4 py-3">{{ rec.description or '-' }}</td>
                    <td class="px-4 py-3 text-sm text-gray-500">{{ rec.category or '-' }}</td>
                    <td class="px-4 py-3 text-right font-semibold {{ 'text-green-600' if rec.type=='income' else 'text-red-500' }}">
                        {{ '+' if rec.type=='income' else '-' }}{{ r(rec.amount) }}
                    </td>
                    <td class="px-4 py-3 text-center no-print">
                        <form method="POST" class="inline" onsubmit="return confirm('Hapus catatan ini?')">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="id" value="{{ rec.id }}">
                            <button type="submit" class="text-red-400 hover:text-red-600 text-sm">🗑️</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                {% if not records %}
                <tr><td colspan="6" class="px-4 py-8 text-center text-gray-400">Tidak ada catatan</td></tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    <!-- Category Breakdown -->
    {% if categories %}
    <div class="bg-white rounded-xl shadow p-6 mt-6">
        <h3 class="font-semibold mb-3">📊 Breakdown per Kategori</h3>
        <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
            {% for c in categories %}
            <div class="flex justify-between p-2 bg-gray-50 rounded">
                <span class="text-sm">{{ c.category }}</span>
                <span class="text-sm font-semibold {{ 'text-green-600' if c.type=='income' else 'text-red-500' }}">{{ r(c.total) }}</span>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}
    ''', records=records, income=income_total, expense=expense_total,
        profit=income_total - expense_total, categories=categories,
        start=start, end=end, r=rupiah)

    return render_template_string(LAYOUT, title="Pembukuan", page="pembukuan", content=content, now=now_str())


@app.route("/ppob", methods=["GET", "POST"])
@login_required
def ppob():
    conn = get_db()

    # PPOB Product Catalog
    PPOB_PRODUCTS = {
        "token_listrik": {
            "name": "⚡ Token Listrik PLN",
            "items": [
                {"name": "Token Rp 20.000", "nominal": 20000, "cost": 19500, "admin": 1500},
                {"name": "Token Rp 50.000", "nominal": 50000, "cost": 49200, "admin": 2000},
                {"name": "Token Rp 100.000", "nominal": 100000, "cost": 98500, "admin": 2500},
                {"name": "Token Rp 200.000", "nominal": 200000, "cost": 197000, "admin": 3000},
                {"name": "Token Rp 500.000", "nominal": 500000, "cost": 494000, "admin": 3500},
                {"name": "Token Rp 1.000.000", "nominal": 1000000, "cost": 988000, "admin": 5000},
            ]
        },
        "pulsa": {
            "name": "📱 Pulsa HP",
            "items": [
                {"name": "Pulsa Rp 5.000", "nominal": 5000, "cost": 4800, "admin": 1000},
                {"name": "Pulsa Rp 10.000", "nominal": 10000, "cost": 9600, "admin": 1500},
                {"name": "Pulsa Rp 15.000", "nominal": 15000, "cost": 14500, "admin": 1500},
                {"name": "Pulsa Rp 20.000", "nominal": 20000, "cost": 19400, "admin": 1500},
                {"name": "Pulsa Rp 25.000", "nominal": 25000, "cost": 24300, "admin": 1500},
                {"name": "Pulsa Rp 50.000", "nominal": 50000, "cost": 48500, "admin": 2000},
                {"name": "Pulsa Rp 100.000", "nominal": 100000, "cost": 97000, "admin": 2500},
            ]
        },
        "paket_data": {
            "name": "📶 Paket Data",
            "items": [
                {"name": "Data 1GB/30hr", "nominal": 15000, "cost": 13500, "admin": 1500},
                {"name": "Data 2GB/30hr", "nominal": 25000, "cost": 23000, "admin": 2000},
                {"name": "Data 5GB/30hr", "nominal": 50000, "cost": 46000, "admin": 2500},
                {"name": "Data 10GB/30hr", "nominal": 80000, "cost": 74000, "admin": 3000},
                {"name": "Data 25GB/30hr", "nominal": 100000, "cost": 92000, "admin": 3000},
            ]
        },
        "tagihan": {
            "name": "📋 Tagihan & Pembayaran",
            "items": [
                {"name": "BPJS Kesehatan", "nominal": 0, "cost": 0, "admin": 2500},
                {"name": "PDAM", "nominal": 0, "cost": 0, "admin": 2500},
                {"name": "Telkom/IndiHome", "nominal": 0, "cost": 0, "admin": 2500},
                {"name": "TV Berlangganan", "nominal": 0, "cost": 0, "admin": 2500},
            ]
        }
    }

    if request.method == "POST":
        action = request.form.get("action")

        if action == "sell":
            product_type = request.form["product_type"]
            product_name = request.form["product_name"]
            customer_id = request.form["customer_id"]
            selling_price = int(request.form["selling_price"])
            cost_price = int(request.form["cost_price"])
            profit = selling_price - cost_price
            notes = request.form.get("notes", "")

            conn.execute("""
                INSERT INTO ppob_transactions (product_type, product_name, customer_id, selling_price, cost_price, profit, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (product_type, product_name, customer_id, selling_price, cost_price, profit, notes))

            # Auto-record income
            conn.execute("""
                INSERT INTO finance (type, amount, description, category) VALUES ('income', ?, ?, 'ppob')
            """, (profit, f"PPOB: {product_name} - {customer_id}"))

            conn.commit()
            conn.close()
            return redirect(url_for("ppob"))

    # Get PPOB stats
    today = datetime.now().strftime("%Y-%m-%d")
    today_stats = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(profit),0) as profit
        FROM ppob_transactions WHERE DATE(created_at) = ?
    """, (today,)).fetchone()

    month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    month_stats = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(profit),0) as profit
        FROM ppob_transactions WHERE DATE(created_at) >= ?
    """, (month_start,)).fetchone()

    recent = conn.execute("""
        SELECT * FROM ppob_transactions ORDER BY created_at DESC LIMIT 10
    """).fetchall()

    conn.close()

    content = render_template_string('''
    <!-- Stats -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div class="bg-white rounded-xl shadow p-4 text-center">
            <div class="text-2xl font-bold text-yellow-600">{{ today.count }}</div>
            <div class="text-sm text-gray-500">Transaksi Hari Ini</div>
        </div>
        <div class="bg-white rounded-xl shadow p-4 text-center">
            <div class="text-2xl font-bold text-green-600">{{ r(today.profit) }}</div>
            <div class="text-sm text-gray-500">Profit Hari Ini</div>
        </div>
        <div class="bg-white rounded-xl shadow p-4 text-center">
            <div class="text-2xl font-bold text-purple-600">{{ r(month.profit) }}</div>
            <div class="text-sm text-gray-500">Profit Bulan Ini ({{ month.count }} trx)</div>
        </div>
    </div>

    <!-- Product Catalog -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {% for type, cat in products.items() %}
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="font-semibold text-lg mb-4">{{ cat.name }}</h3>
            <div class="space-y-2">
                {% for item in cat['items'] %}
                <div class="flex justify-between items-center p-2 bg-gray-50 rounded hover:bg-gray-100">
                    <div>
                        <div class="font-medium text-sm">{{ item.name }}</div>
                        <div class="text-xs text-gray-400">Modal: {{ r(item.cost) }} | Admin: {{ r(item.admin) }}</div>
                    </div>
                    <div class="text-right">
                        <div class="font-semibold text-green-600">{{ r(item.nominal + item.admin if item.nominal > 0 else item.admin) }}</div>
                        <div class="text-xs text-gray-400">Profit: {{ r(item.nominal + item.admin - item.cost if item.nominal > 0 else item.admin) }}</div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endfor %}
    </div>

    <!-- Quick Sell Form -->
    <div class="bg-white rounded-xl shadow p-6 mb-6">
        <h3 class="font-semibold text-lg mb-4">💰 Catat Transaksi PPOB</h3>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <input type="hidden" name="action" value="sell">
            <div>
                <label class="text-sm text-gray-500">Tipe Produk</label>
                <select name="product_type" id="ppobType" onchange="updateProducts()" class="w-full border rounded-lg px-3 py-2">
                    {% for type, cat in products.items() %}
                    <option value="{{ type }}">{{ cat.name }}</option>
                    {% endfor %}
                </select>
            </div>
            <div>
                <label class="text-sm text-gray-500">Produk</label>
                <select name="product_name" id="ppobProduct" onchange="updatePrice()" class="w-full border rounded-lg px-3 py-2">
                    {% for item in products.token_listrik['items'] %}
                    <option value="{{ item.name }}" data-cost="{{ item.cost }}" data-price="{{ item.nominal + item.admin }}">{{ item.name }}</option>
                    {% endfor %}
                </select>
            </div>
            <div>
                <label class="text-sm text-gray-500">No. Meter/HP</label>
                <input name="customer_id" placeholder="Contoh: 12345678901" required class="w-full border rounded-lg px-3 py-2">
            </div>
            <div>
                <label class="text-sm text-gray-500">Harga Jual (Rp)</label>
                <input name="selling_price" id="sellPrice" type="number" required class="w-full border rounded-lg px-3 py-2">
                <input type="hidden" name="cost_price" id="costPrice">
            </div>
            <div class="md:col-span-2 lg:col-span-4">
                <label class="text-sm text-gray-500">Catatan (opsional)</label>
                <input name="notes" placeholder="Catatan tambahan..." class="w-full border rounded-lg px-3 py-2">
            </div>
            <div class="md:col-span-2 lg:col-span-4">
                <button type="submit" class="bg-yellow-500 text-white px-6 py-3 rounded-lg hover:bg-yellow-600 font-semibold">
                    ⚡ Catat Transaksi
                </button>
            </div>
        </form>
    </div>

    <!-- Recent Transactions -->
    <div class="bg-white rounded-xl shadow overflow-hidden">
        <div class="px-6 py-4 border-b">
            <h3 class="font-semibold">📋 Transaksi Terakhir</h3>
        </div>
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Waktu</th>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">Produk</th>
                    <th class="px-4 py-3 text-left text-sm font-semibold text-gray-600">No. Meter/HP</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Harga</th>
                    <th class="px-4 py-3 text-right text-sm font-semibold text-gray-600">Profit</th>
                </tr>
            </thead>
            <tbody class="divide-y">
                {% for t in recent %}
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3 text-sm">{{ t.created_at[:16] }}</td>
                    <td class="px-4 py-3">{{ t.product_name }}</td>
                    <td class="px-4 py-3 font-mono text-sm">{{ t.customer_id }}</td>
                    <td class="px-4 py-3 text-right">{{ r(t.selling_price) }}</td>
                    <td class="px-4 py-3 text-right text-green-600 font-semibold">+{{ r(t.profit) }}</td>
                </tr>
                {% endfor %}
                {% if not recent %}
                <tr><td colspan="5" class="px-4 py-8 text-center text-gray-400">Belum ada transaksi PPOB</td></tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    <!-- Info -->
    <div class="bg-blue-50 rounded-xl p-6 mt-6">
        <h3 class="font-semibold text-blue-800 mb-2">💡 Tips PPOB</h3>
        <ul class="text-sm text-blue-700 space-y-1">
            <li>• Daftar di <strong>Digiflazz.com</strong> untuk harga terbaik & API otomatis</li>
            <li>• Deposit minimal Rp 10.000, langsung bisa jualan</li>
            <li>• Harga di atas adalah estimasi — sesuaikan dengan platform yang lu pakai</li>
            <li>• Profit terbesar: Token listrik Rp 1.000.000 (bisa Rp 7.000-12.000 per trx)</li>
            <li>• Semakin banyak transaksi, semakin murah harga beli (tier system)</li>
        </ul>
    </div>

    <script>
        const products = {{ products_json|safe }};

        function updateProducts() {
            const type = document.getElementById('ppobType').value;
            const select = document.getElementById('ppobProduct');
            select.innerHTML = '';
            products[type]['items'].forEach(item => {
                const opt = document.createElement('option');
                opt.value = item.name;
                opt.dataset.cost = item.cost;
                opt.dataset.price = item.nominal > 0 ? item.nominal + item.admin : item.admin;
                opt.textContent = item.name;
                select.appendChild(opt);
            });
            updatePrice();
        }

        function updatePrice() {
            const opt = document.getElementById('ppobProduct').selectedOptions[0];
            if (opt) {
                document.getElementById('sellPrice').value = opt.dataset.price;
                document.getElementById('costPrice').value = opt.dataset.cost;
            }
        }

        updatePrice();
    </script>
    ''', products=PPOB_PRODUCTS, products_json=json.dumps(PPOB_PRODUCTS),
        today=today_stats, month=month_stats, recent=recent, r=rupiah)

    return render_template_string(LAYOUT, title="PPOB (Token/Pulsa)", page="ppob", content=content, now=now_str())


@app.route("/users", methods=["GET", "POST"])
@login_required
def users_manage():
    if session.get("user_role") != "admin":
        return "Akses ditolak", 403
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            name = request.form.get("name", "").strip()
            role = request.form.get("role", "kasir")
            if username and password and name:
                try:
                    conn.execute("INSERT INTO users (username, password, role, name) VALUES (?, ?, ?, ?)",
                        (username, generate_password_hash(password), role, name))
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
        elif action == "delete":
            uid = int(request.form.get("user_id", 0))
            if uid != session.get("user_id"):
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
                conn.commit()
        elif action == "reset_password":
            uid = int(request.form.get("user_id", 0))
            new_pw = request.form.get("new_password", "")
            if new_pw:
                conn.execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(new_pw), uid))
                conn.commit()
        return redirect(url_for("users_manage"))

    all_users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()

    content = render_template_string('''
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="font-semibold text-lg mb-4">👥 Daftar User</h3>
            <div class="space-y-3">
            {% for u in all_users %}
            <div class="border rounded-lg p-4 flex justify-between items-center">
                <div>
                    <div class="font-semibold">{{ u.name }}</div>
                    <div class="text-sm text-gray-500">@{{ u.username }} —
                        <span class="px-2 py-0.5 rounded text-xs {{ 'bg-indigo-100 text-indigo-700' if u.role=='admin' else 'bg-gray-100 text-gray-700' }}">{{ u.role }}</span>
                    </div>
                </div>
                <div class="flex gap-2">
                    <form method="POST" class="flex gap-1">
                        <input type="hidden" name="action" value="reset_password">
                        <input type="hidden" name="user_id" value="{{ u.id }}">
                        <input type="password" name="new_password" placeholder="Pass baru" class="border rounded px-2 py-1 text-xs w-24">
                        <button type="submit" class="text-blue-500 text-xs hover:underline">🔑</button>
                    </form>
                    {% if u.id != session.get('user_id') %}
                    <form method="POST" onsubmit="return confirm('Hapus user?')">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="user_id" value="{{ u.id }}">
                        <button type="submit" class="text-red-500 text-xs hover:underline">🗑️</button>
                    </form>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
            </div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="font-semibold text-lg mb-4">➕ Tambah User</h3>
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <div class="space-y-3">
                    <input name="name" required placeholder="Nama lengkap" class="w-full border rounded-lg px-3 py-2">
                    <input name="username" required placeholder="Username" class="w-full border rounded-lg px-3 py-2">
                    <input name="password" type="password" required placeholder="Password" class="w-full border rounded-lg px-3 py-2">
                    <select name="role" class="w-full border rounded-lg px-3 py-2"><option value="kasir">Kasir</option><option value="admin">Admin</option></select>
                    <button type="submit" class="w-full bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-700">Tambah User</button>
                </div>
            </form>
        </div>
    </div>
    ''', all_users=all_users)

    return render_template_string(LAYOUT, title="Kelola User", page="users", content=content, now=now_str())


@app.route("/piutang", methods=["GET", "POST"])
@login_required
def piutang():
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_customer":
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            address = request.form.get("address", "").strip()
            if name:
                conn.execute("INSERT INTO customers (name, phone, address) VALUES (?, ?, ?)", (name, phone, address))
                conn.commit()
        elif action == "pay_debt":
            debt_id = int(request.form.get("debt_id", 0))
            amount = int(request.form.get("amount", 0))
            notes = request.form.get("notes", "")
            if amount > 0:
                debt = conn.execute("SELECT * FROM debts WHERE id=?", (debt_id,)).fetchone()
                if debt:
                    new_paid = debt["paid_amount"] + amount
                    new_remaining = debt["total_amount"] - new_paid
                    new_status = "paid" if new_remaining <= 0 else "partial" if new_paid > 0 else "unpaid"
                    conn.execute("UPDATE debts SET paid_amount=?, remaining=?, status=? WHERE id=?",
                        (new_paid, max(0, new_remaining), new_status, debt_id))
                    conn.execute("INSERT INTO debt_payments (debt_id, amount, notes) VALUES (?, ?, ?)",
                        (debt_id, amount, notes))
                    conn.commit()
        elif action == "delete_customer":
            cid = int(request.form.get("customer_id", 0))
            unpaid = conn.execute("SELECT COUNT(*) as c FROM debts WHERE customer_id=? AND status != 'paid'", (cid,)).fetchone()["c"]
            if unpaid == 0:
                conn.execute("DELETE FROM customers WHERE id=?", (cid,))
                conn.commit()
        return redirect(url_for("piutang"))

    total_unpaid = conn.execute("SELECT COALESCE(SUM(remaining),0) as s FROM debts WHERE status='unpaid'").fetchone()["s"]
    total_partial = conn.execute("SELECT COALESCE(SUM(remaining),0) as s FROM debts WHERE status='partial'").fetchone()["s"]
    total_customers = conn.execute("SELECT COUNT(*) as c FROM customers").fetchone()["c"]

    customer_debts = conn.execute("""
        SELECT c.id, c.name, c.phone,
            COALESCE(SUM(d.remaining),0) as total_remaining,
            COUNT(CASE WHEN d.status != 'paid' THEN 1 END) as unpaid_count
        FROM customers c
        LEFT JOIN debts d ON d.customer_id = c.id
        GROUP BY c.id ORDER BY total_remaining DESC
    """).fetchall()

    debts = conn.execute("""
        SELECT d.*, c.name as customer_name, t.id as trx_id
        FROM debts d
        JOIN customers c ON c.id = d.customer_id
        LEFT JOIN transactions t ON t.id = d.transaction_id
        ORDER BY d.created_at DESC
    """).fetchall()

    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    conn.close()

    content = render_template_string('''
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Piutang Belum Bayar</div>
            <div class="text-2xl font-bold text-red-500 mt-1">{{ r(total_unpaid) }}</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Piutang Sebagian</div>
            <div class="text-2xl font-bold text-yellow-500 mt-1">{{ r(total_partial) }}</div>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Total Pelanggan</div>
            <div class="text-2xl font-bold text-blue-500 mt-1">{{ total_customers }}</div>
        </div>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 space-y-6">
            <div class="bg-white rounded-xl shadow p-6">
                <h3 class="font-semibold text-lg mb-4">👥 Daftar Pelanggan</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead><tr class="border-b"><th class="text-left py-2">Nama</th><th class="text-left py-2">HP</th><th class="text-right py-2">Sisa Hutang</th><th class="text-right py-2">Transaksi</th></tr></thead>
                        <tbody>
                        {% for c in customer_debts %}
                        <tr class="border-b hover:bg-gray-50">
                            <td class="py-2 font-medium">{{ c.name }}</td>
                            <td class="py-2 text-gray-500">{{ c.phone or '-' }}</td>
                            <td class="py-2 text-right {{ 'text-red-500 font-semibold' if c.total_remaining > 0 else 'text-gray-400' }}">{{ r(c.total_remaining) }}</td>
                            <td class="py-2 text-right">{{ c.unpaid_count }}</td>
                        </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="bg-white rounded-xl shadow p-6">
                <h3 class="font-semibold text-lg mb-4">📋 Daftar Piutang</h3>
                <div class="space-y-3">
                {% for d in debts %}
                <div class="border rounded-lg p-4 {{ 'border-red-200 bg-red-50' if d.status=='unpaid' else 'border-yellow-200 bg-yellow-50' if d.status=='partial' else 'border-green-200 bg-green-50' }}">
                    <div class="flex justify-between items-start">
                        <div>
                            <div class="font-semibold">{{ d.customer_name }}</div>
                            <div class="text-xs text-gray-500">#{{ d.trx_id or '-' }} — {{ d.created_at[:16] }}</div>
                        </div>
                        <div class="text-right">
                            <div class="font-bold">{{ r(d.total_amount) }}</div>
                            <div class="text-sm text-red-500">Sisa: {{ r(d.remaining) }}</div>
                            <span class="text-xs px-2 py-1 rounded {{ 'bg-red-100 text-red-700' if d.status=='unpaid' else 'bg-yellow-100 text-yellow-700' if d.status=='partial' else 'bg-green-100 text-green-700' }}">
                                {{ 'Belum Bayar' if d.status=='unpaid' else 'Sebagian' if d.status=='partial' else 'Lunas' }}
                            </span>
                        </div>
                    </div>
                    {% if d.status != 'paid' %}
                    <form method="POST" class="mt-3 flex gap-2">
                        <input type="hidden" name="action" value="pay_debt">
                        <input type="hidden" name="debt_id" value="{{ d.id }}">
                        <input type="number" name="amount" min="1" max="{{ d.remaining }}" placeholder="Jumlah" class="flex-1 border rounded px-3 py-1 text-sm">
                        <input type="text" name="notes" placeholder="Catatan" class="w-32 border rounded px-3 py-1 text-sm">
                        <button type="submit" class="bg-green-600 text-white px-4 py-1 rounded text-sm hover:bg-green-700">💰 Bayar</button>
                    </form>
                    {% endif %}
                </div>
                {% endfor %}
                {% if not debts %}
                <p class="text-gray-400 text-center py-8">Belum ada piutang</p>
                {% endif %}
                </div>
            </div>
        </div>
        <div class="space-y-4">
            <div class="bg-white rounded-xl shadow p-6">
                <h3 class="font-semibold text-lg mb-4">➕ Tambah Pelanggan</h3>
                <form method="POST">
                    <input type="hidden" name="action" value="add_customer">
                    <div class="space-y-3">
                        <input name="name" required placeholder="Nama" class="w-full border rounded-lg px-3 py-2">
                        <input name="phone" placeholder="No. HP" class="w-full border rounded-lg px-3 py-2">
                        <input name="address" placeholder="Alamat" class="w-full border rounded-lg px-3 py-2">
                        <button type="submit" class="w-full bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-700">Tambah</button>
                    </div>
                </form>
            </div>
            <div class="bg-white rounded-xl shadow p-6">
                <h3 class="font-semibold text-sm mb-3 text-gray-600">🗑️ Hapus Pelanggan</h3>
                <form method="POST" onsubmit="return confirm('Yakin hapus?')">
                    <input type="hidden" name="action" value="delete_customer">
                    <select name="customer_id" class="w-full border rounded-lg px-3 py-2 text-sm mb-2">
                        {% for c in customers %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
                    </select>
                    <button type="submit" class="w-full bg-red-500 text-white py-2 rounded-lg text-sm hover:bg-red-600">Hapus</button>
                </form>
            </div>
        </div>
    </div>
    ''', total_unpaid=total_unpaid, total_partial=total_partial, total_customers=total_customers,
        customer_debts=customer_debts, debts=debts, customers=customers, r=rupiah)

    return render_template_string(LAYOUT, title="Piutang", page="piutang", content=content, now=now_str())


@app.route("/retur", methods=["GET", "POST"])
@login_required
def retur():
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "process_return":
            tid = int(request.form.get("transaction_id", 0))
            product_id = int(request.form.get("product_id", 0))
            qty = int(request.form.get("quantity", 0))
            reason = request.form.get("reason", "")
            item = conn.execute("SELECT * FROM transaction_items WHERE transaction_id=? AND product_id=?",
                (tid, product_id)).fetchone()
            if item and qty > 0 and qty <= item["quantity"]:
                amount = item["price"] * qty
                conn.execute("INSERT INTO returns (transaction_id, product_id, product_name, quantity, amount, reason, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tid, product_id, item["product_name"], qty, amount, reason, session.get("user_id")))
                conn.execute("UPDATE products SET stock = stock + ?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (qty, product_id))
                conn.execute("INSERT INTO finance (type, amount, description, category) VALUES ('expense', ?, ?, 'retur')",
                    (amount, f"Retur #{tid} - {item['product_name']} x{qty}"))
                conn.commit()
        return redirect(url_for("retur"))

    returns = conn.execute("SELECT r.*, t.id as trx_id FROM returns r LEFT JOIN transactions t ON t.id = r.transaction_id ORDER BY r.created_at DESC LIMIT 50").fetchall()
    total_returns = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM returns").fetchone()["s"]
    conn.close()

    content = render_template_string('''
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div class="bg-white rounded-xl shadow p-6">
            <div class="text-gray-500 text-sm">Total Retur</div>
            <div class="text-2xl font-bold text-red-500 mt-1">{{ r(total_returns) }}</div>
        </div>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="font-semibold text-lg mb-4">📦 Proses Retur</h3>
            <form method="POST" id="returnForm">
                <input type="hidden" name="action" value="process_return">
                <div class="space-y-3">
                    <div>
                        <label class="text-sm text-gray-600">No. Transaksi</label>
                        <input type="number" name="transaction_id" id="trxIdInput" required placeholder="Nomor transaksi" class="w-full border rounded-lg px-3 py-2" onchange="loadTrxItems()">
                    </div>
                    <div>
                        <label class="text-sm text-gray-600">Barang</label>
                        <select name="product_id" id="productSelect" class="w-full border rounded-lg px-3 py-2" required>
                            <option value="">-- Pilih transaksi dulu --</option>
                        </select>
                    </div>
                    <div>
                        <label class="text-sm text-gray-600">Jumlah Retur</label>
                        <input type="number" name="quantity" id="qtyInput" min="1" value="1" class="w-full border rounded-lg px-3 py-2">
                    </div>
                    <div>
                        <label class="text-sm text-gray-600">Alasan</label>
                        <input type="text" name="reason" placeholder="Rusak/salah beli/dll" class="w-full border rounded-lg px-3 py-2">
                    </div>
                    <button type="submit" class="w-full bg-red-600 text-white py-2 rounded-lg hover:bg-red-700">📦 Proses Retur</button>
                </div>
            </form>
        </div>
        <div class="bg-white rounded-xl shadow p-6">
            <div class="flex justify-between items-center mb-4">
                <h3 class="font-semibold text-lg">📋 Riwayat Retur</h3>
                <a href="/export/retur" class="bg-green-600 text-white px-3 py-1 rounded text-sm hover:bg-green-700">📥 CSV</a>
            </div>
            <div class="space-y-3 max-h-96 overflow-y-auto">
                {% for ret in returns %}
                <div class="border-b pb-3">
                    <div class="flex justify-between">
                        <span class="font-medium">{{ ret.product_name }}</span>
                        <span class="text-red-500 font-semibold">{{ r(ret.amount) }}</span>
                    </div>
                    <div class="text-xs text-gray-500">Trx #{{ ret.trx_id }} × {{ ret.quantity }} — {{ ret.reason or '-' }}</div>
                    <div class="text-xs text-gray-400">{{ ret.created_at[:16] }}</div>
                </div>
                {% endfor %}
                {% if not returns %}<p class="text-gray-400 text-center py-4">Belum ada retur</p>{% endif %}
            </div>
        </div>
    </div>
    <script>
        async function loadTrxItems() {
            const tid = document.getElementById('trxIdInput').value;
            const select = document.getElementById('productSelect');
            if (!tid) { select.innerHTML = '<option value="">-- Pilih transaksi dulu --</option>'; return; }
            try {
                const resp = await fetch('/api/transaction/' + tid + '/items');
                const items = await resp.json();
                select.innerHTML = '<option value="">-- Pilih barang --</option>';
                items.forEach(item => {
                    select.innerHTML += '<option value="' + item.product_id + '">' + item.product_name + ' (max: ' + item.quantity + ')</option>';
                });
                if (items.length === 0) select.innerHTML = '<option value="">Transaksi tidak ditemukan</option>';
            } catch(e) { select.innerHTML = '<option value="">Error loading</option>'; }
        }
    </script>
    ''', returns=returns, total_returns=total_returns, r=rupiah)
    return render_template_string(LAYOUT, title="Retur Barang", page="retur", content=content, now=now_str())

@app.route("/api/transaction/<int:tid>/items")
@login_required
def api_trx_items(tid):
    conn = get_db()
    items = conn.execute("SELECT product_id, product_name, quantity, price FROM transaction_items WHERE transaction_id=?", (tid,)).fetchall()
    conn.close()
    return jsonify([dict(i) for i in items])

@app.route("/export/penjualan")
@login_required
def export_penjualan():
    conn = get_db()
    start = request.args.get("start", datetime.now().strftime("%Y-%m-%d"))
    end = request.args.get("end", datetime.now().strftime("%Y-%m-%d"))
    transactions = conn.execute("""
        SELECT t.*, GROUP_CONCAT(ti.product_name || ' x' || ti.quantity, '; ') as items
        FROM transactions t LEFT JOIN transaction_items ti ON ti.transaction_id = t.id
        WHERE DATE(t.created_at) BETWEEN ? AND ? GROUP BY t.id ORDER BY t.created_at DESC
    """, (start, end)).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Waktu", "Diskon", "PPN", "Total", "Bayar", "Kembali", "Items"])
    for t in transactions:
        writer.writerow([t["id"], t["created_at"], t["discount"] or 0, t["tax_amount"] or 0, t["total"], t["payment"], t["change_amount"], t["items"]])
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=penjualan_{start}_{end}.csv"})

@app.route("/export/pembukuan")
@login_required
def export_pembukuan():
    conn = get_db()
    start = request.args.get("start", datetime.now().strftime("%Y-%m-%d"))
    end = request.args.get("end", datetime.now().strftime("%Y-%m-%d"))
    records = conn.execute("SELECT * FROM finance WHERE DATE(created_at) BETWEEN ? AND ? ORDER BY created_at DESC", (start, end)).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Tanggal", "Tipe", "Jumlah", "Kategori", "Deskripsi"])
    for r in records:
        writer.writerow([r["id"], r["created_at"], r["type"], r["amount"], r["category"] or "", r["description"] or ""])
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pembukuan_{start}_{end}.csv"})

@app.route("/export/retur")
@login_required
def export_retur():
    conn = get_db()
    returns = conn.execute("SELECT r.*, t.id as trx_id FROM returns r LEFT JOIN transactions t ON t.id = r.transaction_id ORDER BY r.created_at DESC").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Tanggal", "Trx ID", "Produk", "Jumlah", "Nominal", "Alasan"])
    for r in returns:
        writer.writerow([r["id"], r["created_at"], r["trx_id"] or "", r["product_name"], r["quantity"], r["amount"], r["reason"] or ""])
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=retur.csv"})

@app.route("/backup")
@login_required
def backup_page():
    import glob
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
    backups = []
    if os.path.exists(backup_dir):
        for f in sorted(glob.glob(os.path.join(backup_dir, "kasir_*.db")), reverse=True):
            size = os.path.getsize(f)
            name = os.path.basename(f)
            backups.append({"name": name, "size": f"{size/1024:.1f} KB", "path": f})

    content = render_template_string('''
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Manual Backup -->
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="text-lg font-semibold mb-4">💾 Backup Manual</h3>
            <p class="text-sm text-gray-500 mb-4">Download database saat ini sebagai file backup</p>
            <a href="/api/backup/download" class="block w-full bg-indigo-600 text-white text-center py-3 rounded-lg hover:bg-indigo-700 font-semibold">
                📥 Download Backup Sekarang
            </a>
        </div>

        <!-- Restore -->
        <div class="bg-white rounded-xl shadow p-6">
            <h3 class="text-lg font-semibold mb-4">♻️ Restore Database</h3>
            <p class="text-sm text-gray-500 mb-4">Upload file backup untuk restore data</p>
            <form method="POST" action="/api/backup/restore" enctype="multipart/form-data" onsubmit="return confirm('⚠️ WARNING: Semua data saat ini akan ditimpa! Lanjutkan?')">
                <input type="file" name="file" accept=".db" required class="w-full border rounded-lg px-3 py-2 mb-3">
                <button type="submit" class="block w-full bg-orange-500 text-white text-center py-3 rounded-lg hover:bg-orange-600 font-semibold">
                    ♻️ Restore dari File
                </button>
            </form>
        </div>
    </div>

    <!-- Auto Backup Info -->
    <div class="bg-white rounded-xl shadow p-6 mt-6">
        <h3 class="font-semibold mb-3">⏰ Auto Backup</h3>
        <p class="text-sm text-gray-600 mb-4">Database di-backup otomatis setiap hari jam 02:00 WIB. Backup disimpan 7 hari terakhir.</p>

        {% if backups %}
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-2 text-left text-sm font-semibold text-gray-600">File</th>
                    <th class="px-4 py-2 text-right text-sm font-semibold text-gray-600">Ukuran</th>
                    <th class="px-4 py-2 text-center text-sm font-semibold text-gray-600">Aksi</th>
                </tr>
            </thead>
            <tbody class="divide-y">
                {% for b in backups %}
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-2 text-sm font-mono">{{ b.name }}</td>
                    <td class="px-4 py-2 text-right text-sm">{{ b.size }}</td>
                    <td class="px-4 py-2 text-center">
                        <a href="/api/backup/download/{{ b.name }}" class="text-indigo-600 hover:underline text-sm">📥 Download</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p class="text-gray-400">Belum ada backup</p>
        {% endif %}
    </div>
    ''', backups=backups)

    return render_template_string(LAYOUT, title="Backup & Restore", page="backup", content=content, now=now_str())


@app.route("/api/backup/download")
@app.route("/api/backup/download/<filename>")
def backup_download(filename=None):
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kasir.db")
    
    if filename:
        # Download specific backup
        backup_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups", filename)
        if os.path.exists(backup_path):
            with open(backup_path, 'rb') as f:
                data = f.read()
            return Response(
                data,
                mimetype="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        return "Backup not found", 404
    else:
        # Download current database
        with open(db_path, 'rb') as f:
            data = f.read()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Response(
            data,
            mimetype="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=kasir_{timestamp}.db"}
        )


@app.route("/api/backup/restore", methods=["POST"])
def backup_restore():
    file = request.files.get("file")
    if not file or not file.filename:
        return "No file uploaded", 400
    
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kasir.db")
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    # Backup current before restore
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_backup = os.path.join(backup_dir, f"kasir_pre_restore_{timestamp}.db")
    if os.path.exists(db_path):
        import shutil
        shutil.copy2(db_path, current_backup)
    
    # Restore
    file.save(db_path)
    
    return redirect(url_for("backup_page"))


@app.route("/api/export/csv")
def export_csv():
    conn = get_db()
    records = conn.execute("SELECT * FROM finance ORDER BY created_at DESC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Tanggal", "Tipe", "Jumlah", "Keterangan", "Kategori"])
    for r in records:
        writer.writerow([r["created_at"], r["type"], r["amount"], r["description"], r["category"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=pembukuan.csv"}
    )


# ─── MAIN ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("🛒 Kasir App berjalan di http://localhost:5050")
    app.run(host="0.0.0.0", port=80, debug=False)
