#!/usr/bin/env python3
"""
Kasir App — Simple POS & Bookkeeping
Flask + SQLite, single file
Port: 5050
"""

import os, sqlite3, json, csv, io
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, render_template_string, jsonify, Response

app = Flask(__name__)
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

# ─── TEMPLATES ────────────────────────────────────────────────────────
LAYOUT = '''
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} — Kasir App</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @media print { .no-print { display: none !important; } }
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
                <a href="/kasir" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='kasir' else '' }}">
                    <span>💳</span> Kasir (POS)
                </a>
                <a href="/penjualan" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='penjualan' else '' }}">
                    <span>📋</span> Riwayat Penjualan
                </a>
                <a href="/pembukuan" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='pembukuan' else '' }}">
                    <span>💰</span> Pembukuan
                </a>
                <a href="/backup" class="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-indigo-700 {{ 'bg-indigo-700' if page=='backup' else '' }}">
                    <span>💾</span> Backup & Restore
                </a>
            </div>
        </nav>

        <!-- Main -->
        <div class="flex-1">
            <!-- Top bar -->
            <div class="bg-white shadow-sm px-6 py-3 flex items-center justify-between no-print">
                <button onclick="document.getElementById('sidebar').classList.toggle('-translate-x-full')" class="lg:hidden text-2xl">☰</button>
                <h1 class="text-xl font-semibold text-gray-800">{{ title }}</h1>
                <span class="text-sm text-gray-500">{{ now }}</span>
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

@app.route("/")
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
        recent=recent, r=rupiah)

    return render_template_string(LAYOUT, title="Dashboard", page="dashboard", content=content, now=now_str())


@app.route("/products", methods=["GET", "POST"])
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
            </thead>
            <tbody class="divide-y">
                {% for p in products %}
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3">{{ p.name }}</td>
                    <td class="px-4 py-3 text-right">{{ r(p.price) }}</td>
                    <td class="px-4 py-3 text-right">
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


@app.route("/import", methods=["GET", "POST"])
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
def kasir():
    conn = get_db()

    if request.method == "POST":
        data = json.loads(request.form.get("cart", "[]"))
        payment = int(request.form.get("payment", 0))

        if not data:
            conn.close()
            return redirect(url_for("kasir"))

        total = sum(item["price"] * item["qty"] for item in data)
        change = payment - total

        if payment < total:
            conn.close()
            return redirect(url_for("kasir"))

        # Create transaction
        cur = conn.execute(
            "INSERT INTO transactions (total, payment, change_amount) VALUES (?, ?, ?)",
            (total, payment, change)
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

        conn.commit()
        conn.close()

        return redirect(url_for("receipt", tid=tid))

    products = conn.execute("SELECT * FROM products WHERE stock > 0 ORDER BY name").fetchall()
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
                    <label class="text-sm text-gray-600">Uang Bayar</label>
                    <input type="number" name="payment" id="paymentInput" min="0" class="w-full border rounded-lg px-3 py-2 text-lg" placeholder="0" oninput="calcChange()">
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
            calcChange();
        }

        function calcChange() {
            const total = cart.reduce((s, i) => s + i.price * i.qty, 0);
            const payment = parseInt(document.getElementById('paymentInput').value) || 0;
            const change = payment - total;
            const row = document.getElementById('changeRow');
            if (payment > 0) {
                row.style.display = 'flex';
                document.getElementById('changeAmount').textContent = formatRupiah(Math.max(0, change));
                document.getElementById('changeAmount').className = change >= 0 ? 'font-semibold text-green-600' : 'font-semibold text-red-500';
            } else {
                row.style.display = 'none';
            }
        }

        function prepareCheckout() {
            if (cart.length === 0) return false;
            const total = cart.reduce((s, i) => s + i.price * i.qty, 0);
            const payment = parseInt(document.getElementById('paymentInput').value) || 0;
            if (payment < total) { showToast('Uang kurang!', 'error'); return false; }
            document.getElementById('cartData').value = JSON.stringify(cart);
            return true;
        }

        function filterProducts() {
            const q = document.getElementById('search').value.toLowerCase();
            document.querySelectorAll('.product-card').forEach(card => {
                card.style.display = card.dataset.name.includes(q) ? '' : 'none';
            });
        }
    </script>
    ''', products=products, r=rupiah)

    return render_template_string(LAYOUT, title="Kasir (POS)", page="kasir", content=content, now=now_str())


@app.route("/receipt/<int:tid>")
def receipt(tid):
    conn = get_db()
    trx = conn.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if not trx:
        conn.close()
        return "Transaksi tidak ditemukan", 404

    items = conn.execute("SELECT * FROM transaction_items WHERE transaction_id=?", (tid,)).fetchall()
    conn.close()

    content = render_template_string('''
    <div class="max-w-md mx-auto bg-white rounded-xl shadow p-6" id="receiptArea">
        <div class="text-center mb-4">
            <h2 class="text-xl font-bold">🛒 Kasir App</h2>
            <p class="text-sm text-gray-500">Struk Pembelian</p>
        </div>
        <div class="text-sm text-gray-500 mb-4">
            <div>No: #{{ trx.id }}</div>
            <div>Tgl: {{ trx.created_at }}</div>
        </div>
        <hr class="my-3">
        {% for item in items %}
        <div class="flex justify-between text-sm mb-1">
            <span>{{ item.product_name }} × {{ item.quantity }}</span>
            <span>{{ r(item.subtotal) }}</span>
        </div>
        {% endfor %}
        <hr class="my-3">
        <div class="flex justify-between font-bold text-lg">
            <span>TOTAL</span>
            <span>{{ r(trx.total) }}</span>
        </div>
        <div class="flex justify-between text-sm mt-1">
            <span>Bayar</span><span>{{ r(trx.payment) }}</span>
        </div>
        <div class="flex justify-between text-sm">
            <span>Kembalian</span><span>{{ r(trx.change_amount) }}</span>
        </div>
        <hr class="my-3">
        <p class="text-center text-sm text-gray-400">Terima kasih! 🙏</p>
    </div>
    <div class="flex gap-4 mt-6 justify-center no-print">
        <button onclick="window.print()" class="bg-indigo-600 text-white px-6 py-2 rounded-lg">🖨️ Cetak</button>
        <a href="/kasir" class="bg-gray-200 px-6 py-2 rounded-lg">← Kembali</a>
    </div>
    ''', trx=trx, items=items, r=rupiah)

    return render_template_string(LAYOUT, title=f"Struk #{tid}", page="kasir", content=content, now=now_str())


@app.route("/penjualan")
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
                </tr>
                {% endfor %}
                {% if not transactions %}
                <tr><td colspan="5" class="px-4 py-8 text-center text-gray-400">Tidak ada transaksi</td></tr>
                {% endif %}
            </tbody>
        </table>
    </div>
    ''', transactions=transactions, stats=stats, items_sold=items_sold, start=start, end=end, r=rupiah)

    return render_template_string(LAYOUT, title="Riwayat Penjualan", page="penjualan", content=content, now=now_str())


@app.route("/pembukuan", methods=["GET", "POST"])
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


@app.route("/backup")
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
