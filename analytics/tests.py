from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from alerts.models import Alert
from analytics.models import MonthlyBudget
from analytics.services.dashboard import (
    get_analysis_cross_filter_data,
    get_budget_summary,
    get_category_breakdown,
    get_category_change_summary,
    get_daily_spending,
    get_merchant_analysis,
    get_month_summary,
    get_monthly_review_data,
    get_period_comparison,
    get_smart_insights,
    get_yearly_spending_trend,
)
from payments.models import Category, Transaction


class DashboardTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("dashboard-user", password="test-password-123")
        self.other_user = User.objects.create_user("other-dashboard-user", password="test-password-123")
        self.category = Category.objects.get(name="Dining", is_active=True)
        self.client.force_login(self.user)

    def make_transaction(self, amount, happened, user=None, merchant="Koufu"):
        return Transaction.objects.create(
            user=user or self.user,
            merchant_name=merchant,
            amount=Decimal(amount),
            transaction_date=timezone.make_aware(happened),
            payment_type=Transaction.PaymentType.FOOD,
            predicted_category=self.category,
            final_category=self.category,
            confidence_score=0.95,
            category_explanation="Test transaction.",
        )

    def test_budget_form_creates_and_updates_one_user_owned_budget(self):
        month = timezone.localdate().replace(day=1)
        MonthlyBudget.objects.create(user=self.other_user, month=month, amount="900.00")
        url = reverse("monthly_budget") + f"?month={month:%Y-%m}"

        response = self.client.post(url, {"month": f"{month:%Y-%m}", "amount": "500.00", "action": "save"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MonthlyBudget.objects.get(user=self.user, month=month).amount, Decimal("500.00"))
        self.assertEqual(MonthlyBudget.objects.get(user=self.other_user, month=month).amount, Decimal("900.00"))

        self.client.post(url, {"month": f"{month:%Y-%m}", "amount": "650.00", "action": "save"})
        self.assertEqual(MonthlyBudget.objects.filter(user=self.user, month=month).count(), 1)
        self.assertEqual(MonthlyBudget.objects.get(user=self.user, month=month).amount, Decimal("650.00"))

    def test_budget_summary_uses_saved_budget_and_real_transactions(self):
        month = date(2026, 9, 1)
        MonthlyBudget.objects.create(user=self.user, month=month, amount="500.00")
        self.make_transaction("100.00", datetime(2026, 9, 5, 12, 0))

        summary = get_budget_summary(self.user, month, today=date(2026, 9, 10))
        self.assertEqual(summary["total"], Decimal("100.00"))
        self.assertEqual(summary["remaining"], Decimal("400.00"))
        self.assertEqual(summary["used_percent"], 20.0)
        self.assertEqual(summary["projected_total"], Decimal("300.00"))
        self.assertEqual(summary["status"], "on_track")

    def test_budget_projection_can_report_at_risk(self):
        month = date(2026, 9, 1)
        MonthlyBudget.objects.create(user=self.user, month=month, amount="500.00")
        self.make_transaction("300.00", datetime(2026, 9, 5, 12, 0))
        summary = get_budget_summary(self.user, month, today=date(2026, 9, 10))
        self.assertEqual(summary["projected_total"], Decimal("900.00"))
        self.assertEqual(summary["status"], "at_risk")

        insight = get_smart_insights(self.user, month, summary)[0]
        self.assertEqual(insight["title"], "Current pace is above budget")
        self.assertEqual(insight["message"], "At your current pace, spending may finish about S$400.00 above budget.")

    def test_overview_renders_saved_budget_values(self):
        month = date(2026, 1, 1)
        MonthlyBudget.objects.create(user=self.user, month=month, amount="500.00")
        self.make_transaction("125.00", datetime(2026, 1, 5, 12, 0))

        response = self.client.get(reverse("dashboard"), {"month": "2026-01"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "S$125.00")
        self.assertContains(response, "Monthly budget")
        self.assertContains(response, "S$500.00")
        self.assertContains(response, "S$375.00")
        self.assertNotContains(response, "budget-overview-metrics")
        self.assertContains(response, "Edit budget")
        self.assertContains(response, "type:'line'")

    def test_budget_change_applies_forward_without_changing_past_months(self):
        june = date(2026, 6, 1)
        august = date(2026, 8, 1)
        september = date(2026, 9, 1)
        october = date(2026, 10, 1)
        MonthlyBudget.objects.create(user=self.user, month=june, amount="300.00")

        before_change = get_budget_summary(self.user, august, today=date(2026, 11, 1))
        self.assertEqual(before_change["budget"].amount, Decimal("300.00"))
        self.assertTrue(before_change["budget_is_inherited"])

        response = self.client.post(
            reverse("monthly_budget") + "?month=2026-09",
            {"month": "2026-09", "amount": "400.00", "action": "save"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_budget_summary(self.user, august)["budget"].amount, Decimal("300.00"))
        self.assertEqual(get_budget_summary(self.user, september)["budget"].amount, Decimal("400.00"))
        self.assertEqual(get_budget_summary(self.user, october)["budget"].amount, Decimal("400.00"))
        self.assertEqual(MonthlyBudget.objects.get(user=self.user, month=june).amount, Decimal("300.00"))

    def test_dashboard_view_menu_is_part_of_primary_navigation(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "desktop-dashboard-dropdown")
        self.assertContains(response, "mobile-dashboard-dropdown")
        self.assertNotContains(response, "dashboard-view-dropdown")

    def test_current_month_comparison_uses_equivalent_days(self):
        month = date(2026, 9, 1)
        self.make_transaction("100.00", datetime(2026, 9, 5, 12, 0))
        self.make_transaction("50.00", datetime(2026, 8, 5, 12, 0))
        self.make_transaction("150.00", datetime(2026, 8, 20, 12, 0))

        comparison = get_period_comparison(self.user, month, today=date(2026, 9, 10))
        self.assertEqual(comparison["previous_total"], Decimal("50.00"))
        self.assertEqual(comparison["change"], 100.0)
        self.assertEqual(comparison["label"], "same point last month")

    def test_insights_are_derived_from_budget_and_spending(self):
        month = timezone.localdate().replace(day=1)
        MonthlyBudget.objects.create(user=self.user, month=month, amount="500.00")
        self.make_transaction("600.00", datetime.combine(month, datetime.min.time()).replace(day=2))

        summary = get_budget_summary(self.user, month)
        insights = get_smart_insights(self.user, month, summary)
        self.assertEqual(insights[0]["title"], "Budget exceeded")
        self.assertIn("S$100.00", insights[0]["message"])
        self.assertTrue(any("Dining" in insight["title"] for insight in insights))

    def test_category_breakdown_calculates_real_spending_shares(self):
        month = date(2026, 1, 1)
        self.make_transaction("75.00", datetime(2026, 1, 5, 12, 0))
        self.make_transaction("25.00", datetime(2026, 1, 6, 12, 0))

        breakdown = get_category_breakdown(self.user, month)

        self.assertEqual(breakdown[0]["total"], Decimal("100.00"))
        self.assertEqual(breakdown[0]["share_percent"], 100.0)

    def test_cross_filter_data_coordinates_category_merchant_alert_and_history(self):
        self.make_transaction("40.00", datetime(2026, 1, 5, 12, 0))
        current = self.make_transaction("70.00", datetime(2026, 2, 5, 12, 0))
        current.item_name = "Chicken Rice"
        current.save(update_fields=["item_name"])
        Alert.objects.create(
            user=self.user,
            transaction=current,
            alert_type=Alert.AlertType.HIGH_CATEGORY,
            severity=Alert.Severity.MEDIUM,
            title="High Dining spending",
            message="Dining increased.",
            explanation="Test explanation.",
        )

        data = get_analysis_cross_filter_data(self.user, date(2026, 2, 1), today=date(2026, 3, 1))
        dining = data["categories"]["Dining"]
        merchant = data["merchants"]["Dining::Koufu"]

        self.assertEqual(dining["difference"], 30.0)
        self.assertEqual(dining["direction"], "up")
        self.assertEqual(dining["merchants"][0]["name"], "Koufu")
        self.assertEqual(dining["alerts"][0]["title"], "High Dining spending")
        self.assertEqual(len(merchant["transactions"]), 1)
        self.assertEqual(merchant["transactions"][0]["id"], current.pk)
        self.assertEqual(
            merchant["transactions"][0]["description"], "Chicken Rice"
        )
        self.assertEqual(merchant["history_values"][-2:], [40.0, 70.0])

    def test_merchant_analysis_compares_with_previous_month(self):
        self.make_transaction("40.00", datetime(2026, 1, 5, 12, 0), merchant="Koufu")
        self.make_transaction("70.00", datetime(2026, 2, 5, 12, 0), merchant="Koufu")

        merchants = get_merchant_analysis(self.user, date(2026, 2, 1))

        self.assertEqual(merchants[0]["difference"], Decimal("30.00"))
        self.assertEqual(merchants[0]["direction"], "up")

    def test_category_change_summary_scales_largest_change(self):
        self.make_transaction("40.00", datetime(2026, 1, 5, 12, 0))
        self.make_transaction("70.00", datetime(2026, 2, 5, 12, 0))

        changes = get_category_change_summary(self.user, date(2026, 2, 1))

        self.assertEqual(changes[0]["difference"], Decimal("30.00"))
        self.assertEqual(changes[0]["bar_percent"], 100.0)

    def test_analysis_comparison_reconciles_with_visible_month_totals(self):
        self.make_transaction("40.00", datetime(2026, 7, 20, 12, 0))
        self.make_transaction("70.00", datetime(2026, 8, 20, 12, 0))

        response = self.client.get(reverse("dashboard_analysis"), {"month": "2026-08"})

        self.assertEqual(response.context["comparison"]["current_total"], Decimal("70.00"))
        self.assertEqual(response.context["comparison"]["difference"], Decimal("30.00"))
        self.assertEqual(response.context["cross_filter_data"]["categories"]["Dining"]["difference"], 30.0)

    def test_current_month_chart_stops_at_today_and_ignores_future_transactions(self):
        month = date(2026, 9, 1)
        self.make_transaction("20.00", datetime(2026, 9, 3, 12, 0))
        self.make_transaction("100.00", datetime(2026, 9, 10, 12, 0))

        daily = get_daily_spending(self.user, month, today=date(2026, 9, 4))
        summary = get_month_summary(self.user, month, today=date(2026, 9, 4))

        self.assertEqual(daily["values"][2], 20.0)
        self.assertEqual(daily["values"][3], 0.0)
        self.assertIsNone(daily["values"][4])
        self.assertIsNone(daily["values"][-1])
        self.assertEqual(summary["total"], Decimal("20.00"))
        self.assertEqual(summary["count"], 1)

    def test_dashboard_views_use_the_selected_month(self):
        selected = date(2026, 1, 1)
        self.make_transaction("123.45", datetime(2026, 1, 8, 12, 0))
        for name in ("dashboard", "dashboard_analysis"):
            response = self.client.get(reverse(name), {"month": "2026-01"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["month"], selected)
        review_redirect = self.client.get(reverse("dashboard_review"), {"month": "2026-01"})
        self.assertRedirects(review_redirect, reverse("dashboard") + "?month=2026-01", fetch_redirect_response=False)
        analysis = self.client.get(reverse("dashboard_analysis"), {"month": "2026-01"})
        self.assertContains(analysis, "S$123.45")
        self.assertContains(analysis, "Category Analysis")
        self.assertContains(analysis, "Select a category to explore its merchants and payments.")
        self.assertNotContains(analysis, "dashboard-summary-strip")
        self.assertContains(analysis, "Dashboard")
        self.assertContains(analysis, "data-category-index=\"0\"")
        self.assertContains(
            analysis, "makeElement('strong', '', transaction.description)"
        )

    def test_analysis_and_review_avoid_duplicate_or_unnecessary_sections(self):
        self.make_transaction("40.00", datetime(2026, 1, 5, 12, 0))
        self.make_transaction("70.00", datetime(2026, 2, 5, 12, 0))

        analysis = self.client.get(reverse("dashboard_analysis"), {"month": "2026-02"})
        self.assertNotContains(analysis, "Top merchants")
        self.assertNotContains(analysis, "change-track")
        self.assertContains(analysis, "change-arrow")
        self.assertNotContains(analysis, "Payments worth reviewing")

        dashboard = self.client.get(reverse("dashboard"), {"month": "2026-02"})
        self.assertContains(dashboard, "What stood out this month")
        self.assertContains(dashboard, "Cumulative spending this month")
        self.assertContains(dashboard, "How February compares")
        self.assertNotContains(dashboard, "Monthly review")
        self.assertNotContains(dashboard, "cumulativeReviewChart")
        self.assertContains(dashboard, "review-moment-card", count=4)
        self.assertContains(dashboard, 'id="reviewMomentDetail" aria-live="polite" hidden')
        self.assertNotContains(dashboard, "if (milestones.length) selectMoment(0)")
        self.assertContains(dashboard, "data-range=\"6\"")
        self.assertContains(dashboard, "data-range=\"12\"")

    def test_monthly_review_metrics_are_derived_from_transaction_timing(self):
        month = date(2026, 2, 1)
        MonthlyBudget.objects.create(user=self.user, month=month, amount="1000.00")
        self.make_transaction("40.00", datetime(2026, 1, 5, 12, 0))
        self.make_transaction("300.00", datetime(2026, 2, 2, 9, 0), merchant="Landlord")
        self.make_transaction("20.00", datetime(2026, 2, 10, 12, 0))
        self.make_transaction("10.00", datetime(2026, 2, 10, 18, 0))

        review = get_monthly_review_data(self.user, month, today=date(2026, 3, 1))

        self.assertEqual(review["headline_total"], Decimal("330.00"))
        self.assertIn("highest-spending month", review["headline"])
        self.assertEqual(review["payment_count"], 3)
        self.assertEqual(review["budget_used_percent"], 33.0)
        self.assertEqual(
            [habit["key"] for habit in review["habits"]],
            ["no-spend-days", "biggest-day", "first-week"],
        )
        self.assertEqual(review["habits"][0]["value"], "26")
        self.assertEqual(len(review["trend"]["labels"]), 12)
        self.assertEqual(review["trend"]["values"][-1], 330.0)
        self.assertEqual(
            [milestone["key"] for milestone in review["milestones"]],
            ["biggest-day", "busiest-day", "passed-previous", "month-total"],
        )
        self.assertTrue(all(milestone["story_title"] for milestone in review["milestones"]))
        self.assertEqual(review["interactions"]["cumulative_values"][-1], 330.0)
        self.assertEqual(len(review["comparisons"]), 3)

    def test_yearly_trend_contains_twelve_real_monthly_totals(self):
        self.make_transaction("25.00", datetime(2025, 1, 5, 12, 0))
        self.make_transaction("75.00", datetime(2025, 12, 5, 12, 0))

        trend = get_yearly_spending_trend(self.user, date(2025, 12, 1), today=date(2026, 1, 1))

        self.assertEqual(len(trend["labels"]), 12)
        self.assertEqual(trend["labels"][0], "Jan 2025")
        self.assertEqual(trend["labels"][-1], "Dec 2025")
        self.assertEqual(trend["values"][0], 25.0)
        self.assertEqual(trend["values"][-1], 75.0)

        response = self.client.get(reverse("dashboard"), {"month": "2025-12"})
        self.assertContains(response, "How December compares")
        self.assertContains(response, "const reviewChart")
        self.assertContains(response, "type:'bar'")

    def test_removing_budget_does_not_remove_another_users_budget(self):
        month = timezone.localdate().replace(day=1)
        MonthlyBudget.objects.create(user=self.user, month=month, amount="500.00")
        MonthlyBudget.objects.create(user=self.other_user, month=month, amount="900.00")
        response = self.client.post(reverse("monthly_budget"), {
            "month": f"{month:%Y-%m}",
            "action": "delete",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MonthlyBudget.objects.filter(user=self.user, month=month).exists())
        self.assertTrue(MonthlyBudget.objects.filter(user=self.other_user, month=month).exists())
