#!/usr/bin/env bash
# exit on error
set -o errexit
python create_admin.py
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate