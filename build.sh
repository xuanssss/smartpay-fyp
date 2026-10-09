#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py train_transaction_model
python manage.py seed_demo_data --if-missing
python manage.py collectstatic --noinput
