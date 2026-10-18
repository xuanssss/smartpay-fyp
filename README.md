# Integrated Bill Payment App with Smart Categorization

A mobile-first Django Final Year Project prototype that joins simulated bill payments with explainable smart categorisation, spending analytics, and friendly needs-attention alerts.

This is a simulation for demonstration and evaluation. It does not move money, connect to a bank, or make definitive fraud decisions.

## Problem statement

Payment and superapp transaction histories are often chronological lists. Users can see what happened, but may struggle to understand changes by spending category or unusual behaviour. Separate budgeting products can offer stronger analytics, creating a gap between everyday payment activity and financial understanding. This project explores a single simulated experience that turns payment records into understandable insights.

## Features

- Registration, email-or-username login, and logout using Django authentication
- Simulated payment creation with ten user-facing payment types
- Selective high-confidence domain rules followed by SVM categorisation with plain-language reasoning
- Reverse-chronological transaction history and detailed reasoning view
- User category corrections that retain the original prediction for evaluation
- Dashboard views for monthly overview, spending analysis, and monthly review
- User-managed budget changes that carry into future months while preserving past monthly budgets, with calculated progress and pace-based projections
- Data-derived daily spending, category movement, merchant, payment, and alert summaries
- Explainable smart insights generated from saved budgets, transactions, comparisons, and active alerts
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
python manage.py evaluate_transaction_model
python manage.py seed_demo_data
python manage.py runserver
```

Windows PowerShell activation:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py evaluate_transaction_model
python manage.py seed_demo_data
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

## Demo account

- Username: `demo`
- Password: `demo12345`

Running `seed_demo_data` is safe to repeat. It refreshes the demo user's transactions, alerts, monthly budget, password, and categories while leaving other user accounts alone. A saved budget applies from its selected month onward until the user saves another change; earlier months keep their previous amount. A user can edit or remove a budget change from Dashboard → Set/Edit budget.

## ML training and evaluation

The labelled model dataset is `data/moneyvis_singapore_quality_checked.csv`. A reproducible stratified 80/20 split is used with random seed 42. New payments first pass through a deliberately small, reviewable set of high-confidence domain rules in `payments/services/domain_rules.py`. These rules describe reusable merchant families and contextual patterns rather than individual transactions: stable merchants such as Amazon or FairPrice can map directly, while multi-service merchants such as Grab or Gojek require explicit food or ride wording. Ambiguous and unmatched payments are passed to the committed linear SVM in `models/transaction_classifier.joblib`. There are no broad payment-type or `Other` fallbacks, and legacy database `MerchantRule` rows are not used. Initial setup and deployment validate this committed classifier rather than retraining it.

The ML dependency versions are pinned in `requirements.txt`. Each trained model
also records its scikit-learn, SciPy, NumPy, pandas, and joblib versions in the
saved metadata so a deployed model can be traced to its training environment.

The separate MoneyVis research-cleaning workflow lives in `data/moneyvis_data_cleaning.ipynb`. It rebuilds 3,859 cleaned debit-expense records across 18 mapped categories directly from the original workbook, including Mortgage and Rent records mapped to `Housing` and excluding all `FEE` transactions. It writes a full auditable dataset to `data/moneyvis_cleaned_debit_purchases.csv` and a reduced synthesis input containing five substantive fields plus a non-model mapping identifier to `data/moneyvis_synthesis_input.csv`. The final Singapore-localised output is `data/moneyvis_singapore_quality_checked.csv`; its `source_row_id` preserves one-to-one traceability to the synthesis input. Reproducible structural and description-quality checks are contained in `data/moneyvis_synthesis_quality_check.ipynb`. The train-only word TF-IDF, character TF-IDF, category lexicon, SGD amount-percentile, day-bucket and one-hot transformations are implemented in `payments/services/ml_features.py` and demonstrated in `data/moneyvis_feature_engineering.ipynb`. The reproducible SVM experiment and per-category results are recorded in `data/moneyvis_machine_learning.ipynb`. The current workflow does not generate a separate Singapore benchmark.

Retrain and replace the committed model after changing the dataset, feature pipeline, classifier, or pinned ML dependencies:

```bash
python manage.py train_transaction_model
```

This command is not required for ordinary setup or deployment. It writes `models/transaction_classifier.joblib`, which must be reviewed and committed together with the related dataset or code change. The saved bundle contains the fitted word and character TF-IDF vocabularies, category lexicons, SGD amount-percentile boundaries, day buckets, one-hot encoders, and SVM. App inference therefore uses the exact transformations fitted during training. The command prints:

- Accuracy
- Macro-averaged precision
- Macro-averaged recall
- Macro-averaged F1-score
- Label order and confusion matrix

Re-evaluate the saved model:

```bash
python manage.py evaluate_transaction_model
```

Apply the current hybrid categoriser to all existing transactions:

```bash
python manage.py recategorise_transactions --dry-run
python manage.py recategorise_transactions
```

The command updates predictions atomically and preserves any final category that
a user has manually corrected.

The app converts its available payment information into the model schema: merchant/item/transaction wording is cleaned into `description_clean`; the selected payment method is mapped to a MoneyVis-compatible transaction code; the entered app amount is already SGD; and the transaction timestamp supplies the day bucket. The audit identifier and target category are never supplied to prediction.

## Tests

```bash
python manage.py test
```

The tests cover selective domain-rule boundaries, SVM fallback and structured feature delivery, duplicate payment alerts, unfamiliar high-value merchant alerts, dashboard totals and comparisons, user-owned budget changes, derived smart insights, and category correction while preserving the prediction.

## Deploying on Render

The included `render.yaml` provisions a Render web service and PostgreSQL
database. Production uses Gunicorn with one worker and two threads, a
memory-conscious configuration for Render's 512 MB free instance. WhiteNoise
serves collected static files. Local development continues to use SQLite when
`DATABASE_URL` is not set.

1. Push the project to a Git repository, including the labelled CSV and the
   evaluated `models/transaction_classifier.joblib` bundle.
2. In Render, create a new Blueprint and select the repository.
3. Apply the resources described by `render.yaml`.
4. Wait for the build to migrate the database, validate the committed
   classifier against the labelled dataset and pinned dependency versions,
   seed the demo account only if it is missing, and collect static files.
5. Open the generated Render URL and log in with the demo account above.

Render generates the production secret key and supplies `DATABASE_URL` and
`RENDER_EXTERNAL_HOSTNAME`. To use a custom domain, add its hostname to the
comma-separated `ALLOWED_HOSTS` environment variable and its full HTTPS origin
to `CSRF_TRUSTED_ORIGINS`.

The free Render web service can sleep while idle, and free PostgreSQL is for
short-lived evaluation. Select paid plans in `render.yaml` or the Render
dashboard when the app must remain continuously available or retain data beyond
the free database period.

## Project structure

```text
accounts/                 authentication and home page
payments/                 transaction models, forms, views, categorisation, ML, commands
analytics/                dashboard analytics, budgets, and performance logs
alerts/                   alert model, rules, status workflow
data/                     MoneyVis cleaning, quality-check, feature, and ML research artefacts
models/                   evaluated classifier committed for deployment
templates/                mobile-first Django templates
static/css/               interface styling
smartpay/                 Django project settings and root URLs
```

## Known limitations

- Simulated payment environment only
- No real banking or payment API
- No real or production-level fraud detection
- Small sample dataset for ML
- Model outcomes may be wrong and require user correction
- Alerts are for user awareness, not definitive fraud decisions
- Budget projections use the current daily spending pace and are estimates, not financial advice
- Smart insights are deterministic summaries of recorded app data rather than generative financial advice
- CDN assets require an internet connection unless downloaded and served locally
