#!/bin/bash

echo "🚀 Starting setup for Ubuntu..."

# Step 1: Update system packages and install python3-venv if needed
echo "📦 Updating system packages and installing Python venv..."
sudo apt update && sudo apt install -y python3-pip python3-venv

# Step 2: Create a virtual environment
echo "🌱 Creating virtual environment 'venv'..."
python3 -m venv venv

# Step 3: Activate the virtual environment and install requirements
echo "⚙️ Activating virtual environment and installing requirements from requirements.txt..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✅ Setup Complete!"
echo "👉 To run your bot, use the following commands:"
echo "   source venv/bin/activate"
echo "   python3 main.py"
