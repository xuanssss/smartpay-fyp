from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class HomePageTests(TestCase):
    def test_home_omits_removed_recurring_bill_summary(self):
        user = get_user_model().objects.create_user(
            username="home-test", password="test-password-123"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Recurring bills")
        self.assertNotContains(response, "Patterns across months")
        self.assertNotIn("recurring_count", response.context)
        self.assertContains(response, 'class="summary-item"', count=2)
