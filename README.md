# Integrated Bill Payment App with Smart Categorization

A mobile-first Django Final Year Project prototype that joins simulated bill payments with explainable smart categorisation, spending analytics, recurring-bill summaries, and friendly needs-attention alerts.

> This is a simulation for demonstration and evaluation. It does not move money, connect to a bank, or make definitive fraud decisions.

## Problem statement

Payment and superapp transaction histories are often chronological lists. Users can see what happened, but may struggle to understand recurring bills, changes by spending category, or unusual behaviour. Separate budgeting products can offer stronger analytics, creating a gap between everyday payment activity and financial understanding. This project explores a single simulated experience that turns payment records into understandable insights.

## Features

- Registration, email-or-username login, and logout using Django authentication
- Simulated payment creation with ten user-facing payment types
- Rule-first automatic categorisation with confidence and plain-language reasoning
- Optional TF-IDF and Logistic Regression fallback model
- Reverse-chronological transaction history and detailed reasoning view
- User category corrections that retain the original prediction for evaluation
- Monthly totals, month comparison, category chart, top merchants, and largest payments
- Recurring bill detection across at least three months
- Explainable duplicate, unusual amount, unfamiliar high-value, and category-spending alerts
- Alert review and dismissal workflow
- Timing records for categorisation, alert generation, and dashboard loading
- Deterministic presentation-ready demo dataset with more than 60 transactions

## Tech stack

- Python 3.11+
- Django 5.2 LTS (the newest Django line that still supports Python 3.11)
- SQLite
- Django templates, Bootstrap 5 CDN, and Chart.js CDN
- pandas, NumPy, scikit-learn, and joblib

Django 6 requires Python 3.12+, so Django 5.2 is intentionally used to preserve the requested Python 3.11 compatibility.

## Setup

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data
python manage.py train_transaction_model
python manage.py runserver
```

Windows PowerShell activation:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data
python manage.py train_transaction_model
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

## Demo account

- Username: `demo`
- Password: `demo12345`

Running `seed_demo_data` is safe to repeat. It refreshes the demo user's transactions, alerts, recurring summaries, password, categories, and merchant rules while leaving other user accounts alone.

## ML training and evaluation

The labelled sample lives in `data/sample_transactions.csv`. The rule system is always checked first. When no merchant rule matches, the saved ML model may suggest a category; without a trained model, the service uses the selected payment type or `Others` fallback.

Train and save the model:

```bash
python manage.py train_transaction_model
```

This writes `models/transaction_classifier.joblib` and prints:

- Accuracy
- Weighted precision
- Weighted recall
- Weighted F1-score
- Label order and confusion matrix

Re-evaluate the saved model:

```bash
python manage.py evaluate_transaction_model
```

The bundled CSV is deliberately small and exists to demonstrate an end-to-end ML workflow, not to claim production classifier quality. Comments beginning with `# TODO-FYP-TWEAK:` identify dataset, taxonomy, thresholds, wording, and model choices to revisit during the FYP evaluation.

## Tests

```bash
python manage.py test
```

The tests cover exact-rule categorisation, duplicate payment alerts, unfamiliar high-value merchant alerts, dashboard monthly totals, and category correction while preserving the prediction.

## Project structure

```text
accounts/                 authentication and home page
payments/                 transaction models, forms, views, categorisation, ML, commands
analytics/                dashboard and recurring-bill services, performance logs
alerts/                   alert model, rules, status workflow
data/                     small labelled ML dataset
models/                   generated classifier (git-ignored)
templates/                mobile-first Django templates
static/css/               interface styling
smartpay/                 Django project settings and root URLs
```

## Known limitations

- Simulated payment environment only
- No real banking or payment API
- No real or production-level fraud detection
- Small sample dataset for ML
- Rule and model outcomes may be wrong and require user correction
- Alerts are for user awareness, not definitive fraud decisions
- Recurring detection uses a simple amount-variation heuristic rather than a learned temporal model
- CDN assets require an internet connection unless downloaded and served locally
