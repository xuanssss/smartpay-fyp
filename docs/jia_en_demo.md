# Jia En presentation scenario

This scenario is synthetic. It uses the real Django models, saved transactions,
hybrid categoriser, dashboard queries, and alert-generation service. It does not
make a payment or contact a bank.

## What the existing application does

1. A transaction is saved with its merchant, amount, timestamp, simulated
   payment method, and MoneyVis-compatible bank transaction type.
2. Categorisation checks the small reviewed domain-rule layer first. If no rule
   applies, the committed SVM predicts a category and confidence from the
   cleaned description, transaction type, relative amount, and day bucket.
3. The original prediction and the final category are stored separately. A
   correction changes only the final category used by analytics and keeps the
   original prediction.
4. The alert service compares a newly recorded payment with the same user's
   saved history. Duplicate detection requires the same merchant within five
   minutes and an amount difference below 5%. Unusual-amount detection requires
   at least three same-merchant historical amounts and a new amount above the
   historical mean plus two sample standard deviations.
5. Dashboard totals are calculated from saved transactions and their final
   categories. For the current month, comparisons use the same elapsed-day
   period from the previous month.

Historical rows are inserted through a controlled backfill path so old
transactions do not create misleading real-time alerts. Every row still passes
through the real categoriser. The S$350 Super Energy payment and second Singtel
payment are then evaluated by the normal alert service.

## Create or reset the account locally

Use an environment variable so the password is not committed or placed in the
command itself:

```bash
export JIA_EN_DEMO_PASSWORD='choose-a-strong-presentation-password'
python manage.py seed_jia_en_demo --as-of 2026-11-15 --dry-run
python manage.py seed_jia_en_demo --as-of 2026-11-15 --reset
```

The login username is `jia_en_demo`. Running the command again without
`--reset` refreshes the account profile/password and leaves the existing
scenario unchanged. `--reset` deletes and recreates only records owned by this
dedicated account. It never resets the database, research dataset, trained SVM,
or another user's records.

To check the saved presentation data without changing it:

```bash
python manage.py seed_jia_en_demo --as-of 2026-11-15 --verify-only
```

## Expected November 2026 result

The command prints the authoritative summary. With the committed code and
`--as-of 2026-11-15`, the expected monthly totals are:

| Month | Transactions | Total |
|---|---:|---:|
| December 2025 | 41 | S$2,629.59 |
| January 2026 | 42 | S$2,722.03 |
| February 2026 | 41 | S$2,560.29 |
| March 2026 | 41 | S$2,654.44 |
| April 2026 | 42 | S$2,651.99 |
| May 2026 | 40 | S$2,607.89 |
| June 2026 | 43 | S$2,740.63 |
| July 2026 | 39 | S$2,605.64 |
| August 2026 | 45 | S$2,742.69 |
| September 2026 | 41 | S$2,682.89 |
| October 2026 | 42 | S$2,731.84 |
| November 2026 through 15 November | 36 | S$1,434.09 |

The completed months now use roughly 85–91% of Jia En's S$3,000 budget. They
include shared-room rent, insurance, utilities, healthcare, groceries,
services, and occasional larger lifestyle purchases. November remains a real
partial month: rent and other expenses normally paid after 15 November have not
been inserted early.

November uses S$1,434.09, or 47.8%, of the S$3,000 budget. The largest
same-period category changes are:

- Bills: S$520.10 versus S$232.20, up 124.0%.
- Dining: S$117.60 versus S$70.60, up 66.6%.
- Online Shopping: S$86.70 versus S$0.00.
- Clothing: S$186.90 versus S$48.00, up 289.4%.

Groceries remain comparatively stable at S$125.00 versus S$123.60 (up 1.1%),
while Public Transport is slightly lower than the same point in October.

The alert service produces three active alerts:

- Unusual bill amount for Super Energy, S$350.
- Possible duplicate payment for the second Singtel S$39.90 payment, recorded
  two minutes after the first with a different submission token.
- High Bills spending because the current Bills total is over 50% higher than
  October.

The committed SVM predicts `Bills` for the S$350 transaction. The exact stored
confidence should be read from the command output or transaction detail page;
it is an actual model inference rather than a scripted value.

## Recommended 3–4 minute walkthrough

1. Log in at `/login/` as `jia_en_demo`. Briefly state that Jia En's twelve
   months of synthetic history are already present, so the demo focuses on
   financial understanding rather than payment entry.
2. Open `/alerts/`. Start with **Unusual bill amount** and explain that SmartPay
   compared S$350 with Jia En's eleven Super Energy bills of S$96–S$106. Expand
   **Why this appeared**. Emphasise that the wording asks for review and does
   not claim fraud or prove the bill is wrong.
3. Click **Super Energy · S$350.00**. Point out the predicted and final `Bills`
   category, the `Machine-learning model` source, actual confidence, SVM
   explanation, and available **Change category** action.
4. Return to `/alerts/` and open **Possible duplicate payment**. Explain that
   the two S$39.90 Singtel records are two minutes apart but have distinct
   submission tokens: SmartPay did not confuse a retried form submission with
   the awareness rule. Optionally use **Mark reviewed** or **Dismiss** only
   after showing that the initial status is Active.
5. Open `/dashboard/?month=2026-11`. Show S$1,434.09 spent and 47.8% of the
   S$3,000 budget. Mention the same-period comparison, not a misleading full
   October-versus-partial-November comparison.
6. Open `/dashboard/analysis/?month=2026-11`. Select Bills to show the S$350
   payment driving the increase, then Dining or Online Shopping to show that
   the dashboard explains broader changes rather than only alerts.
7. Close with: SmartPay lets Jia En spot an unusual bill, review a possible
   duplicate, and understand which categories changed without manually
   comparing every transaction.

## Pre-presentation checklist

Run:

```bash
python manage.py seed_jia_en_demo --as-of 2026-11-15 --verify-only
python manage.py test payments.tests.test_jia_en_demo -v 2
```

Then confirm in the browser:

- Login works for `jia_en_demo`.
- Alerts shows Active unusual-amount, duplicate, and high-Bills alerts.
- Super Energy S$350 shows predicted/final Bills plus real SVM details.
- The two current Singtel S$39.90 transactions are two minutes apart.
- November overview shows S$1,434.09, S$3,000 budget, and 47.8% used.
- Category Analysis shows Bills S$520.10 and useful historical charts.
- No alert was accidentally reviewed or dismissed during rehearsal; run
  `--reset` if a clean status is needed.

## Hosted Render application

Do not point a local command at the production database. In the Render service:

1. Add the secret environment variable `JIA_EN_DEMO_PASSWORD`.
2. Optionally set `JIA_EN_DEMO_AS_OF=2026-11-15` for the fixed presentation
   snapshot.
3. Deploy the updated code. The build script seeds the account only when the
   password variable is present and leaves an existing scenario unchanged.
4. Before the presentation, use the service's Render Shell to run:

   ```bash
   python manage.py seed_jia_en_demo --as-of 2026-11-15 --reset
   python manage.py seed_jia_en_demo --as-of 2026-11-15 --verify-only
   ```

Only use `--reset` after confirming that `jia_en_demo` is the dedicated
fictional presentation account. The command never touches another user's data.
