#!/usr/bin/env bash
# Build script for Render deployment (runs from backend/ root)
# exit on error
set -o errexit

# Install Python dependencies
pip install -r requirements.txt

# Collect static files
python manage.py collectstatic --no-input

# Run migrations
python manage.py migrate

# Create media directories
mkdir -p media/firmware

echo "Build completed successfully!"
