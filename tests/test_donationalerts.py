import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.server.donationalerts import (
    DonationAlerts, _is_presence_notification, _parse_donation_publication, extract_donation,
)


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

    def test_extracts_legacy_centrifugo_result_envelope(self):
        channel = "$alerts:donation_42"
        message = {
            "result": {
                "type": 1,
                "channel": channel,
                "data": {
                    "seq": 17,
                    "data": {
                        "id": 456,
                        "name": "donation",
                        "username": "LegacyViewer",
                        "message_type": "text",
                        "message": "Сообщение из старого формата",
                        "amount": 75,
                        "currency": "RUB",
                        "amount_in_user_currency": 75,
                    },
                },
            },
        }
        self.assertEqual(
            extract_donation(message, channel),
            {"id": "456", "donor": "LegacyViewer", "amount": 75.0,
             "currency": "RUB", "text": "Сообщение из старого формата",
             "created_at": ""},
        )

    def test_ignores_centrifugo_join_leave_presence_push(self):
        channel = "$alerts:donation_42"
        # This is the initial channel-presence notification, not a donation.
        message = {"push": {"type": 1, "channel": channel,
                            "data": {"info": {"user": "42", "client": "connection-id"}}}}
        push = message["push"]
        self.assertTrue(_is_presence_notification(push))
        self.assertIsNone(extract_donation(message, channel))

    def test_presence_detector_does_not_hide_real_publications(self):
        channel = "$alerts:donation_42"
        message = {"push": {"type": 1, "channel": channel,
            "pub": {"data": {"id": 99, "amount": 25,
                             "info": {"user": "42", "client": "sender"}}}}}
        self.assertFalse(_is_presence_notification(message["push"]))
        self.assertEqual(extract_donation(message, channel)["id"], "99")

    def test_parser_exposes_safe_rejection_reason(self):
        channel = "$alerts:donation_42"
        message = {"push": {"channel": channel, "pub": {"data": {
            "id": 123, "name": "donation",
        }}}}
        donation, reason = _parse_donation_publication(message, channel)
        self.assertIsNone(donation)
        self.assertEqual(reason, "amount отсутствует или не является числом")

    def test_runtime_diagnostic_counters_are_exposed(self):
        with TemporaryDirectory() as folder:
            client = DonationAlerts(config_path=Path(folder) / "donationalerts.json")
            client._record_ws_message()
            client._record_ws_message(channel_publication=True)
            client._record_publication_result(None, "нет amount")
            client._record_publication_result({"id": "123"}, "")
            status = client.status()
            client.close()
        self.assertEqual(status["ws_messages_received"], 2)
        self.assertEqual(status["channel_publications_received"], 1)
        self.assertEqual(status["presence_events_ignored"], 0)
        self.assertEqual(status["donations_parsed"], 1)
        self.assertEqual(status["donations_rejected"], 1)
        self.assertEqual(status["last_rejection_reason"], "нет amount")

    def test_presence_events_are_counted_separately_from_publications_and_rejections(self):
        with TemporaryDirectory() as folder:
            client = DonationAlerts(config_path=Path(folder) / "donationalerts.json")
            client._record_ws_message(presence_event=True)
            status = client.status()
            client.close()
        self.assertEqual(status["ws_messages_received"], 1)
        self.assertEqual(status["channel_publications_received"], 0)
        self.assertEqual(status["presence_events_ignored"], 1)
        self.assertEqual(status["donations_rejected"], 0)
        self.assertEqual(status["last_rejection_reason"], "")

    def test_donation_channel_does_not_require_resource_name_but_rejects_invalid_amount(self):
        channel = "$alerts:donation_42"
        # The private channel identifies the event type; real publications may
        # omit the resource name entirely.
        self.assertIsNotNone(extract_donation({"push": {"channel": channel,
            "pub": {"data": {"id": 1, "amount": 5}}}}, channel))
        self.assertIsNone(extract_donation({"push": {"channel": channel,
            "pub": {"data": {"id": 1, "amount": "invalid"}}}}, channel))


if __name__ == "__main__":
    unittest.main()
