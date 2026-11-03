import unittest

from backend.server.donationalerts import extract_donation


class DonationAlertsPayloadTests(unittest.TestCase):
    def test_extracts_donation_publication(self):
        channel = "$alerts:donation_42"
        message = {
            "push": {
                "channel": channel,
                "pub": {"data": {
                    "reason": "new",
                    "id": 123,
                    "name": "donation",
                    "username": "Viewer",
                    "message": "Hello!",
                    "amount": 50,
                    "currency": "RUB",
                }},
            }
        }
        self.assertEqual(
            extract_donation(message, channel),
            {"id": "123", "donor": "Viewer", "amount": 50.0,
             "currency": "RUB", "text": "Hello!", "created_at": ""},
        )

    def test_ignores_other_channels(self):
        message = {"push": {"channel": "$alerts:donation_99", "pub": {"data": {
            "id": 123, "name": "donation", "username": "Viewer",
            "amount": 1, "currency": "RUB",
        }}}}
        self.assertIsNone(extract_donation(message, "$alerts:donation_42"))

    def test_rejects_non_donation_or_invalid_amount(self):
        channel = "$alerts:donation_42"
        self.assertIsNone(extract_donation({"push": {"channel": channel,
            "pub": {"data": {"id": 1, "name": "subscription", "amount": 5}}}}, channel))
        self.assertIsNone(extract_donation({"push": {"channel": channel,
            "pub": {"data": {"id": 1, "name": "donation", "amount": "invalid"}}}}, channel))


if __name__ == "__main__":
    unittest.main()
