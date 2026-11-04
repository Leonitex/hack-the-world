"""Phone app endpoint tests. Providers are faked; no network, no keys."""

import io
import socket
import unittest
from unittest.mock import patch

import phone_app
from agent.loop import LoopOutcome
from agent.providers import FakeProvider, ProviderError, ToolCall
from diagnostic_core.models import SessionStatus as S

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class RecordingFake(FakeProvider):
    def __init__(self, script):
        super().__init__(script)
        self.images = []

    def set_image(self, image_data_url):
        self.images.append(image_data_url)

    def stage(self, *entries):
        """Queue additional scripted decisions (e.g. for a later retry)."""
        self._script.extend(entries)


def propose_cause(cause="Cause A"):
    return ToolCall("propose_hypothesis", {"cause": cause})


def request_evidence():
    return ToolCall("request_user_evidence", {
        "action": "Check the indicator light and report what you see.",
        "observations": ["What color is the light?", "Is it steady or blinking?"],
    })


class PhoneAppTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network access forbidden in app tests"))
            guard.start()
            self.addCleanup(guard.stop)
        self.client = phone_app.app.test_client()
        self.client.post("/reset")

    def tearDown(self):
        self.client.post("/reset")

    def start_session(self, problem="Laptop powers on but has no display", script=None, label="Test Provider"):
        fake = RecordingFake(list(script or []))
        with patch("phone_app.create_provider", return_value=(fake, label)):
            response = self.client.post("/start", data={"problem": problem}, follow_redirects=True)
        return response, fake

    def test_index_loads_without_session(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Begin investigation", response.get_data(as_text=True))

    def test_start_needs_problem(self):
        response = self.client.post("/start", data={"problem": "  "}, follow_redirects=True)
        self.assertIn("Describe the device problem first.", response.get_data(as_text=True))
        self.assertIsNone(phone_app.STATE["loop"])

    def test_start_missing_provider_key_friendly(self):
        with patch("phone_app.create_provider", side_effect=ProviderError("No provider key found: set BASETEN_API_KEY or MODEL_API_KEY.")):
            response = self.client.post("/start", data={"problem": "No display"}, follow_redirects=True)
        body = response.get_data(as_text=True)
        self.assertIn("BASETEN_API_KEY", body)
        self.assertIsNone(phone_app.STATE["loop"])

    def test_start_runs_loop_to_needs_input(self):
        response, fake = self.start_session(script=[propose_cause(), request_evidence()])
        body = response.get_data(as_text=True)
        self.assertIn("Do this next", body)
        self.assertIn("Test Provider", body)
        self.assertEqual(phone_app.STATE["loop"].session.snapshot.status, S.NEEDS_INPUT)
        self.assertEqual(len(fake.images), 0)

    def test_bad_photo_rejected_cleanly(self):
        bad = (io.BytesIO(b"not an image"), "evil.exe")
        with patch("phone_app.create_provider") as factory:
            response = self.client.post(
                "/start",
                data={"problem": "No display", "image": bad},
                content_type="multipart/form-data",
                follow_redirects=True,
            )
        self.assertIn("PNG, JPEG, GIF, WebP, or BMP", response.get_data(as_text=True))
        factory.assert_not_called()
        self.assertIsNone(phone_app.STATE["loop"])

    def test_image_validation_unit(self):
        class Upload:
            def __init__(self, name, data):
                self.filename = name
                self._data = data

            def read(self):
                return self._data

        self.assertIsNone(phone_app.image_to_data_url(None))
        self.assertIsNone(phone_app.image_to_data_url(Upload("", b"data")))
        url = phone_app.image_to_data_url(Upload("photo.png", PNG_BYTES))
        self.assertTrue(url.startswith("data:image/png;base64,"))
        with self.assertRaises(ValueError):
            phone_app.image_to_data_url(Upload("photo.txt", b"data"))
        with self.assertRaises(ValueError):
            phone_app.image_to_data_url(Upload("photo.png", b"not image bytes"))
        with self.assertRaises(ValueError):
            phone_app.image_to_data_url(Upload("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * (9 * 1024 * 1024)))

    def test_initial_image_associated_with_evidence(self):
        seen = {}

        def factory(image):
            seen["image"] = image
            return RecordingFake([propose_cause(), request_evidence()]), "Test Provider"

        with patch("phone_app.create_provider", side_effect=factory):
            self.client.post(
                "/start",
                data={"problem": "No display", "image": (io.BytesIO(PNG_BYTES), "photo.png")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )
        self.assertTrue(seen["image"].startswith("data:image/png;base64,"))
        evidence = phone_app.STATE["loop"].session.snapshot.evidence
        self.assertEqual(set(phone_app.STATE["images"]), {evidence[0].id})

    def test_followup_photo_associated_and_forwarded(self):
        _, fake = self.start_session(script=[propose_cause(), request_evidence()])
        fake.stage(propose_cause("Cause B"))
        response = self.client.post(
            "/resume",
            data={"answer": "The light is amber and blinking.", "image": (io.BytesIO(PNG_BYTES), "follow.png")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        evidence = phone_app.STATE["loop"].session.snapshot.evidence
        self.assertEqual(len(phone_app.STATE["images"]), 1)
        stored_id = next(iter(phone_app.STATE["images"]))
        self.assertEqual(evidence[-1].id, stored_id)
        self.assertEqual(len(fake.images), 1)
        self.assertTrue(fake.images[0].startswith("data:image/png;base64,"))

    def test_resume_preserves_session_on_provider_error(self):
        _, fake = self.start_session(script=[propose_cause(), request_evidence()])
        fake.stage(ProviderError("Baseten HTTP 500: {secret blob}"))
        response = self.client.post(
            "/resume", data={"answer": "The light is amber."}, follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertIn("trouble reaching the model", body)
        self.assertNotIn("secret blob", body)
        loop = phone_app.STATE["loop"]
        self.assertIsNotNone(loop)
        snapshot = loop.session.snapshot
        self.assertEqual(snapshot.status, S.INVESTIGATING)
        self.assertTrue(any("amber" in item.statement for item in snapshot.evidence))

    def test_resume_without_session_redirects(self):
        response = self.client.post("/resume", data={"answer": "x"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(phone_app.STATE["loop"])

    def test_retry_continues_with_fresh_budget(self):
        _, fake = self.start_session(script=[propose_cause(), ProviderError("boom")])
        self.assertEqual(phone_app.STATE["last_result"].outcome, LoopOutcome.PROVIDER_ERROR)
        fake.stage(propose_cause("Cause B"), request_evidence())
        response = self.client.post("/retry", follow_redirects=True)
        self.assertIn("Do this next", response.get_data(as_text=True))
        snapshot = phone_app.STATE["loop"].session.snapshot
        self.assertEqual(len(snapshot.hypotheses), 2)
        self.assertEqual(snapshot.turn_count, 4)

    def test_double_resume_rejected_friendly(self):
        _, fake = self.start_session(script=[propose_cause(), request_evidence()])
        fake.stage(propose_cause("Cause B"))
        self.client.post("/resume", data={"answer": "The light is amber."}, follow_redirects=True)
        response = self.client.post("/resume", data={"answer": "Again."}, follow_redirects=True)
        self.assertIn("Evidence rejected:", response.get_data(as_text=True))
        self.assertIsNotNone(phone_app.STATE["loop"])

    def test_reset_clears_state(self):
        self.start_session(script=[propose_cause(), request_evidence()])
        self.assertIsNotNone(phone_app.STATE["loop"])
        self.client.post("/reset", follow_redirects=True)
        self.assertIsNone(phone_app.STATE["loop"])
        self.assertIsNone(phone_app.STATE["provider"])
        self.assertEqual(phone_app.STATE["images"], {})


if __name__ == "__main__":
    unittest.main()
