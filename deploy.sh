#!/bin/bash
# One-line deploy: bash <(curl -s https://raw.githubusercontent.com/Pujagaul6/kasir-app/main/deploy.sh)
set -e

echo "🚀 Deploying Kasir App..."

# Install dependencies
apt update -qq
apt install -y -qq python3 python3-pip git

# Clone repo
rm -rf /opt/kasir-app
git clone https://github.com/Pujagaul6/kasir-app.git /opt/kasir-app
cd /opt/kasir-app

# Install Python deps
pip3 install flask -q

# Create systemd service
cat > /etc/systemd/system/kasir-app.service << 'EOF'
[Unit]
Description=Kasir App - POS & Bookkeeping
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/kasir-app
ExecStart=$(which python3) /opt/kasir-app/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Fix ExecStart with actual python3 path
PYTHON_PATH=$(which python3)
sed -i "s|\$(which python3)|$PYTHON_PATH|" /etc/systemd/system/kasir-app.service

# Enable and start
systemctl daemon-reload
systemctl enable kasir-app
systemctl start kasir-app

# Setup auto-backup cron
chmod +x /opt/kasir-app/backup.sh
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/kasir-app/backup.sh >> /opt/kasir-app/backups/backup.log 2>&1") | crontab -

# Open firewall port 80
ufw allow 80/tcp 2>/dev/null || true

echo ""
echo "✅ Kasir App deployed successfully!"
echo "🌐 Access: http://$(curl -s ifconfig.me)"
echo ""
echo "Commands:"
echo "  systemctl status kasir-app   # Check status"
echo "  systemctl restart kasir-app  # Restart"
echo "  journalctl -u kasir-app -f   # View logs"
