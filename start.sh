#!/bin/bash
cd "$(dirname "$0")"
echo "📦 Installing dependencies..."
pip3 install flask -q
echo "🚀 Starting Kasir App..."
python3 app.py
