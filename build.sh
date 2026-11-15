#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py evaluate_transaction_model
python manage.py seed_demo_data --if-missing
if [[ -n "${JIA_EN_DEMO_PASSWORD:-}" ]]; then
    python manage.py seed_jia_en_demo
fi
python manage.py collectstatic --noinput
