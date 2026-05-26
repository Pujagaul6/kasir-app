# 🛒 Kasir App - POS & Bookkeeping

Aplikasi kasir sederhana untuk toko/UMKM. Web-based, bisa diakses dari HP/PC.

## Features

- **📊 Dashboard** - Ringkasan penjualan hari ini, nilai stok, laba bulanan
- **📦 Produk & Stok** - Kelola barang, stok masuk/keluar, import CSV
- **💳 Kasir (POS)** - Cari barang, keranjang, bayar, cetak struk
- **📋 Riwayat Penjualan** - Filter per tanggal, detail transaksi
- **💰 Pembukuan** - Catat income/expense, laba bersih, export CSV
- **💾 Backup & Restore** - Auto-backup harian, manual download/restore

## One-Line Deploy

```bash
bash <(curl -s https://raw.githubusercontent.com/Pujagaul6/kasir-app/main/deploy.sh)
```

## Manual Install

```bash
git clone https://github.com/Pujagaul6/kasir-app.git
cd kasir-app
pip3 install flask
python3 app.py
```

Access: http://localhost:80

## Tech Stack

- Python 3 + Flask
- SQLite (no database server needed)
- Tailwind CSS (CDN)
- Systemd service (auto-start)

## Data

- Database: `kasir.db` (SQLite)
- Backups: `backups/` folder (auto daily at 02:00)
- Products CSV: `produk.csv`

## Commands

```bash
# Service management
sudo systemctl status kasir-app
sudo systemctl restart kasir-app
sudo systemctl stop kasir-app

# View logs
sudo journalctl -u kasir-app -f

# Manual backup
./backup.sh
```

## License

Free to use.
