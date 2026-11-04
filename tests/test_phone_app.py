"""Phone app endpoint tests. Providers are faked; no network, no keys."""

import io
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

import phone_app
from agent.loop import LoopOutcome
from agent.providers import FakeProvider, ProviderError, ToolCall
from diagnostic_core.models import SessionStatus as S
from history_store import HistoryStore

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
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_store = phone_app._STORE
        phone_app._STORE = HistoryStore(os.path.join(self._tmp.name, "history.db"))
        self.client = phone_app.app.test_client()
        self.client.post("/reset")

    def tearDown(self):
        self.client.post("/reset")
        phone_app._STORE = self._old_store

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

    def test_retry_continues_same_session_with_fresh_advance(self):
        _, fake = self.start_session(script=[propose_cause(), ProviderError("boom")])
        self.assertEqual(phone_app.STATE["last_result"].outcome, LoopOutcome.PROVIDER_ERROR)
        session_id = phone_app.STATE["loop"].session.snapshot.id
        self.assertEqual(phone_app.STATE["last_result"].steps_used, 14)
        fake.stage(propose_cause("Cause B"), request_evidence())
        response = self.client.post("/retry", follow_redirects=True)
        self.assertIn("Do this next", response.get_data(as_text=True))
        snapshot = phone_app.STATE["loop"].session.snapshot
        self.assertEqual(snapshot.id, session_id)
        self.assertEqual(len(snapshot.hypotheses), 2)
        self.assertEqual(snapshot.turn_count, 4)
        self.assertEqual(phone_app.STATE["last_result"].steps_used, 16)

    def test_orb_error_and_accessibility_hooks_present(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("body.error .orb-core", body)
        self.assertIn('aria-live="polite"', body)
        self.assertIn('aria-label="Voice input"', body)
        self.assertIn("prefers-reduced-motion", body)
        self.assertIn('querySelector(".card.error")', body)
        self.assertIn("permissions", body)

    def test_evidence_provenance_visible_on_demand(self):
        self.start_session(script=[propose_cause(), request_evidence()])
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Source: user_text", body)
        self.assertIn("channel: phone_ui", body)
        self.assertIn("kind: initial_problem", body)

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
        self.assertIsNone(phone_app.STATE["history_session_id"])


    def test_resume_continues_after_start_consumes_advance(self):
        # Issue #6 repro: the start phase may spend its whole advance, but
        # Submit & continue must still reach a new actionable step.
        script = [propose_cause(f"Cause {index}") for index in range(13)]
        script.append(request_evidence())
        response, fake = self.start_session(script=script)
        self.assertIn("Do this next", response.get_data(as_text=True))
        self.assertEqual(phone_app.STATE["last_result"].outcome, LoopOutcome.NEEDS_INPUT)
        calls_before = fake.decide_calls
        fake.stage(propose_cause("Cause after resume"), request_evidence())
        response = self.client.post(
            "/resume", data={"answer": "The indicator light is steady green."},
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertGreater(fake.decide_calls, calls_before)
        self.assertEqual(phone_app.STATE["last_result"].outcome, LoopOutcome.NEEDS_INPUT)
        self.assertIn("Do this next", body)

    def test_second_and_third_user_turns_keep_progressing(self):
        _, fake = self.start_session(script=[propose_cause(), request_evidence()])
        for turn in ("First observation recorded.", "Second observation recorded."):
            fake.stage(propose_cause(f"Cause for {turn}"), request_evidence())
            response = self.client.post(
                "/resume", data={"answer": turn}, follow_redirects=True)
            self.assertIn("Do this next", response.get_data(as_text=True))
            self.assertEqual(
                phone_app.STATE["last_result"].outcome, LoopOutcome.NEEDS_INPUT)
        session = phone_app.STATE["loop"].session.snapshot
        self.assertEqual(len(session.evidence), 3)
        self.assertGreaterEqual(len(session.hypotheses), 3)


    def test_resume_shows_reassessment_note(self):
        _, fake = self.start_session(script=[propose_cause(), request_evidence()])
        fake.stage(propose_cause("Cause B"), request_evidence())
        response = self.client.post(
            "/resume", data={"answer": "The light is steady green."},
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertIn("New evidence recorded", body)
        self.assertIn("reassessed", body)
        self.assertIn("2 steps this round", body)

    def test_session_budget_exhaustion_asks_for_fresh_start(self):
        _, fake = self.start_session(script=["garbage"] * 60)
        self.assertEqual(
            phone_app.STATE["last_result"].outcome, LoopOutcome.ADVANCE_EXHAUSTED)
        for _ in range(4):
            self.client.post("/retry", follow_redirects=True)
        result = phone_app.STATE["last_result"]
        self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(fake.decide_calls, 60)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("full step budget", body)
        self.assertNotIn("Try again", body)
        self.client.post("/retry", follow_redirects=True)
        self.assertEqual(fake.decide_calls, 60)
        self.assertEqual(phone_app.STATE["loop"].session.snapshot.turn_count, 1)


    def test_timeline_records_real_events(self):
        response, fake = self.start_session(script=[propose_cause(), request_evidence()])
        body = response.get_data(as_text=True)
        self.assertIn("Session started", body)
        self.assertIn("New cause considered", body)
        self.assertIn("Test requested", body)
        titles = [entry["title"] for entry in phone_app.STATE["timeline"]]
        self.assertEqual(titles[0], "Session started")
        self.assertTrue(titles[1].startswith("New cause considered ("))
        self.assertEqual(titles[2], "Test requested")
        fake.stage(propose_cause("Cause B"), request_evidence())
        response = self.client.post(
            "/resume", data={"answer": "The light is steady green."},
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        titles = [entry["title"] for entry in phone_app.STATE["timeline"]]
        self.assertIn("You reported", titles)
        self.assertIn("The light is steady green.", body)
        recorded = [title for title in titles if title.startswith("Evidence recorded (")]
        self.assertEqual(len(recorded), 1)
        resumed = phone_app.STATE["loop"].session.snapshot
        self.assertIn(resumed.evidence[-1].id, recorded[0])
        self.assertIn("Cause B", body)

    def test_premium_assistant_hooks_present(self):
        self.start_session(script=[propose_cause(), request_evidence()])
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('<svg class="orb-svg"', body)
        self.assertIn("orbCoreError", body)
        self.assertIn("orb-sweep", body)
        self.assertIn('id="orbSub"', body)
        self.assertIn("zone-assistant", body)
        self.assertIn("zone-timeline", body)
        self.assertIn("zone-tech", body)
        self.assertIn('id="stopButton"', body)
        self.assertIn("dataset.submitted", body)
        self.assertIn('charset="utf-8"', body)
        self.assertIn("grid-template-areas", body)

    def test_draft_problem_preserved_on_start_error(self):
        problem = "Laptop powers on but the screen stays black"
        with patch("phone_app.create_provider", side_effect=ProviderError("No provider key found.")):
            response = self.client.post("/start", data={"problem": problem}, follow_redirects=True)
        body = response.get_data(as_text=True)
        self.assertIn("Something needs attention", body)
        self.assertIn(problem, body)
        self.assertIn("Begin investigation", body)

    def test_draft_answer_preserved_on_photo_error(self):
        self.start_session(script=[propose_cause(), request_evidence()])
        answer = "The light is amber and blinking."
        response = self.client.post(
            "/resume",
            data={"answer": answer, "image": (io.BytesIO(b"not an image"), "evil.exe")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertIn("PNG, JPEG, GIF, WebP, or BMP", body)
        self.assertIn(answer, body)
        loop = phone_app.STATE["loop"]
        self.assertIsNotNone(loop)
        self.assertEqual(loop.session.snapshot.status, S.NEEDS_INPUT)


    def test_new_investigation_archives_previous_without_deleting(self):
        self.start_session(problem="First problem", script=[propose_cause(), request_evidence()])
        first_id = phone_app.STATE["history_session_id"]
        self.assertIsNotNone(first_id)
        self.start_session(problem="Second problem", script=[propose_cause(), request_evidence()])
        second_id = phone_app.STATE["history_session_id"]
        self.assertNotEqual(first_id, second_id)
        store = phone_app.get_store()
        sessions = {s["id"]: s for s in store.list_sessions()}
        self.assertEqual(set(sessions), {first_id, second_id})
        self.assertEqual(sessions[first_id]["archived"], 1)
        self.assertEqual(sessions[second_id]["archived"], 0)
        first_titles = [e["title"] for e in store.get_events(first_id)]
        self.assertIn("Session started", first_titles)
        self.assertIn("Test requested", first_titles)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Investigation 1", body)
        self.assertIn("Investigation 2", body)

    def test_archive_view_is_read_only(self):
        self.start_session(problem="First", script=[propose_cause(), request_evidence()])
        first_id = phone_app.STATE["history_session_id"]
        self.start_session(problem="Second", script=[propose_cause(), request_evidence()])
        live_loop = phone_app.STATE["loop"]
        response = self.client.get(f"/history/{first_id}")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("archived · read-only", body)
        self.assertIn("Test requested", body)
        self.assertIn("Back to live investigation", body)
        self.assertNotIn("Submit & continue", body)
        self.assertNotIn('id="resumeForm"', body)
        self.assertNotIn('id="answerInput"', body)
        self.assertIs(phone_app.STATE["loop"], live_loop)
        self.assertEqual(phone_app.STATE["loop"].session.snapshot.problem, "Second")

    def test_history_parity_no_fabrication(self):
        _, fake = self.start_session(script=[propose_cause(), request_evidence()])
        fake.stage(propose_cause("Cause B"), request_evidence())
        self.client.post("/resume", data={"answer": "The light is steady green."},
                         follow_redirects=True)
        memory = [(e["kind"], e["title"], e["detail"]) for e in phone_app.STATE["timeline"]]
        stored = [(e["kind"], e["title"], e["detail"]) for e in phone_app.get_store().get_events(
            phone_app.STATE["history_session_id"])]
        self.assertEqual(stored, memory)
        self.assertGreater(len(stored), 4)

    def test_restart_reopen_keeps_history(self):
        self.start_session(script=[propose_cause(), request_evidence()])
        hid = phone_app.STATE["history_session_id"]
        reopened = HistoryStore(phone_app.get_store().path)
        events = reopened.get_events(hid)
        self.assertEqual([e["title"] for e in events],
                         [e["title"] for e in phone_app.STATE["timeline"]])
        self.assertEqual(reopened.get_session(hid)["archived"], 1)

    def test_photo_bytes_never_persisted(self):
        def factory(image):
            return RecordingFake([propose_cause(), request_evidence()]), "Test Provider"

        with patch("phone_app.create_provider", side_effect=factory):
            self.client.post(
                "/start",
                data={"problem": "No display", "image": (io.BytesIO(PNG_BYTES), "photo.png")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )
        hid = phone_app.STATE["history_session_id"]
        events = phone_app.get_store().get_events(hid)
        photos = [e for e in events if e["kind"] == "photo"]
        self.assertEqual(len(photos), 1)
        self.assertIn("not stored", photos[0]["detail"])
        blob = "\n".join(e["title"] + e["detail"] for e in events)
        self.assertNotIn("base64", blob)
        self.assertIn("Photo attached", self.client.get("/").get_data(as_text=True))

    def test_rename_session(self):
        self.start_session(script=[propose_cause(), request_evidence()])
        hid = phone_app.STATE["history_session_id"]
        response = self.client.post(f"/history/{hid}/rename", data={"name": "Front desk PC"},
                                    follow_redirects=True)
        self.assertIn("Front desk PC", response.get_data(as_text=True))
        self.assertEqual(phone_app.get_store().get_session(hid)["name"], "Front desk PC")
        response = self.client.post(f"/history/{hid}/rename", data={"name": "   "},
                                    follow_redirects=True)
        self.assertIn("must not be empty", response.get_data(as_text=True))
        self.assertEqual(phone_app.get_store().get_session(hid)["name"], "Front desk PC")

    def test_unknown_history_redirects_with_error(self):
        response = self.client.post("/history/nope/rename", data={"name": "x"},
                                    follow_redirects=True)
        self.assertIn("Investigation not found.", response.get_data(as_text=True))
        response = self.client.get("/history/nope", follow_redirects=True)
        self.assertIn("Investigation not found.", response.get_data(as_text=True))


    def test_cinematic_orb_layers_present(self):
        self.start_session(script=[propose_cause(), request_evidence()])
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("orb-spin-d", body)
        self.assertIn("orb-inner", body)
        self.assertIn("orb-scanline", body)
        self.assertIn("completeBurst", body)
        self.assertIn("body.completed .orb-core", body)
        self.assertIn("bg-glow-a", body)
        self.assertIn("bg-glow-b", body)
        self.assertIn("onboundary", body)
        self.assertIn("word-pop", body)
        self.assertIn('querySelector(".card.final")', body)

    def test_motion_respects_reduced_motion(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("prefers-reduced-motion", body)
        self.assertIn(".orb-scanline { opacity:0 !important; }", body)


if __name__ == "__main__":
    unittest.main()
