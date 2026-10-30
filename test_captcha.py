import json
from itertools import chain, repeat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ai_decision
import windows_ui as ui
from test_windows import node


class CaptchaDecisionTests(unittest.TestCase):
    def test_cli_attaches_challenge_image_and_accepts_bounded_answer_steps(self):
        process = Mock()
        process.poll.return_value = 0
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "challenge.png"
            with patch.object(ai_decision, "cli_command", return_value=["codex"]), \
                 patch.object(ai_decision.subprocess, "Popen", return_value=process) as launch:
                job = ai_decision.start({"controls": []}, prompt=ai_decision.CAPTCHA_PROMPT, image=image)
                try:
                    arguments = launch.call_args.args[0]
                    self.assertEqual(arguments[arguments.index("--image") + 1], str(image))
                    self.assertIn("--ephemeral", arguments)
                finally:
                    ai_decision.cancel(job)
        controls = [{"name": "Answer", "role": "EditControl"}]
        for step in ({"action": "click", "points": [[0, 0], [99, 49]]},
                     {"action": "type", "control": 0, "text": "AB12"}):
            with self.subTest(step=step), patch.object(ai_decision, "start", return_value={"deadline": float("inf")}) as start, \
                 patch.object(ai_decision, "result", return_value={"decision": "approve", "response": json.dumps(step)}):
                self.assertEqual(ai_decision.captcha_step(image, controls, 100, 50, 10), step)
                start.assert_called_once_with({"controls": controls, "width": 100, "height": 50},
                                              prompt=ai_decision.CAPTCHA_PROMPT, image=image)

    def test_refusal_and_invalid_or_outside_steps_are_not_executable(self):
        decisions = [{"decision": "no_response", "response": None}]
        for step in ({"action": "click", "points": [[100, 0]]},
                     {"action": "click", "points": [[-1, 5]]},
                     {"action": "type", "control": 0, "text": "answer"},
                     {"action": "type", "control": 1, "text": "answer\n"}):
            decisions.append({"decision": "approve", "response": json.dumps(step)})
        controls = [{"role": "ButtonControl"}, {"role": "EditControl"}]
        for decision in decisions:
            with self.subTest(decision=decision), \
                 patch.object(ai_decision, "start", return_value={"deadline": float("inf")}), \
                 patch.object(ai_decision, "result", return_value=decision):
                with self.assertRaises(RuntimeError):
                    ai_decision.captcha_step(Path("challenge.png"), controls, 100, 50, 10)


class CaptchaRegionTests(unittest.TestCase):
    def test_sample_form_is_never_used_in_place_of_its_captcha_frame(self):
        api = Mock()
        api.ControlsAreSame.side_effect = lambda first, second: first is second
        page = node("DocumentControl", "hCAPTCHA Demo")
        widget = node("DocumentControl", "hCaptcha security challenge")
        widget.GetPattern.return_value.Value = "https://newassets.hcaptcha.com/captcha/checkbox"
        widget.BoundingRectangle = Mock(width=lambda: 300, height=lambda: 80)
        form = node("GroupControl", "Sample Form with hCAPTCHA", [widget])
        form.BoundingRectangle = Mock(width=lambda: 420, height=lambda: 290)
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "chrome_page_controls", return_value=[page, form, widget]):
            self.assertIs(ui.chrome_captcha_region(node("WindowControl"), "https://accounts.hcaptcha.com"), widget)
        form.GetChildren.return_value = []
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "chrome_page_controls", return_value=[page, form]):
            with self.assertRaisesRegex(RuntimeError, "No visible CAPTCHA frame"):
                ui.chrome_captcha_region(node("WindowControl"), "https://accounts.hcaptcha.com")


class NativeCaptchaTests(unittest.TestCase):
    def test_capture_rejects_account_controls_before_creating_an_image(self):
        api = Mock()
        api.ControlsAreSame.side_effect = lambda first, second: first is second
        browser = node("WindowControl")
        api.GetForegroundControl.return_value = browser
        browser.BoundingRectangle = Mock(left=0, top=0, right=1000, bottom=800)
        for control in (node("EditControl", "Email address"), node("ButtonControl", "Register account")):
            with self.subTest(role=control.ControlTypeName):
                region = node("GroupControl", "CAPTCHA", [control])
                region.BoundingRectangle = Mock(left=10, top=20, right=400, bottom=300)
                with patch.object(ui, "automation", return_value=api):
                    with self.assertRaisesRegex(RuntimeError, "account controls"):
                        self.capture(browser, region, Path("unused.png"))
                region.CaptureToImage.assert_not_called()

    def setUp(self):
        self.capture = ui.chrome_captcha_snapshot
        self.browser = node("WindowControl", "Registration")
        self.answer = node("EditControl", "CAPTCHA answer")
        self.answer.GetPattern.return_value.IsReadOnly = False
        self.tile = node("ButtonControl", "Challenge tile")
        self.region = node("GroupControl", "CAPTCHA", [self.tile, self.answer])
        self.region.BoundingRectangle = Mock(left=100, top=200, right=400, bottom=400)
        self.api = Mock()
        self.api.ControlsAreSame.side_effect = lambda first, second: first is second
        self.api.GetForegroundControl.return_value = self.browser
        self.api.ControlFromPoint.return_value = self.tile
        self.pixels = b"unsolved challenge"
        self.bounds = (100, 200, 400, 400)
        def snapshot(browser, region, path):
            path.write_bytes(self.pixels)
            controls = [self.tile, self.answer]
            return self.bounds, controls, [{"name": control.Name, "role": control.ControlTypeName} for control in controls]
        for name, arguments in (
                ("automation", {"return_value": self.api}),
                ("chrome_password_suggestion", {"return_value": (self.browser, None)}),
                ("chrome_captcha_region", {"return_value": self.region}),
                ("chrome_captcha_snapshot", {"side_effect": snapshot}),
                ("prepare_chrome_site", {})):
            fixture = patch.object(ui, name, **arguments)
            fixture.start()
            self.addCleanup(fixture.stop)
        sleeping = patch.object(ui.time, "sleep")
        sleeping.start()
        self.addCleanup(sleeping.stop)

    def test_click_or_captcha_answer_is_followed_by_explicit_stable_verification(self):
        for step in ({"action": "click", "points": [[10, 20]]},
                     {"action": "type", "control": 1, "text": "AB12"}):
            with self.subTest(step=step):
                self.api.Click.reset_mock()
                self.answer.GetPattern.return_value.SetValue.reset_mock()
                self.pixels = b"unsolved challenge"
                def accepted(*args, **kwargs):
                    self.pixels = b"verified widget"
                self.api.Click.side_effect = accepted
                self.answer.GetPattern.return_value.SetValue.side_effect = accepted
                with patch.object(ai_decision, "captcha_step", side_effect=[step, {"action": "verified"}]):
                    result = ui.solve_chrome_captcha("https://signup.example.com/register")
                self.assertIn("confirmed", result["message"])
                if step["action"] == "click":
                    self.api.Click.assert_called_once_with(110, 220, waitTime=.2)
                    self.answer.GetPattern.return_value.SetValue.assert_not_called()
                else:
                    self.answer.GetPattern.return_value.SetValue.assert_called_once_with("AB12")
                    self.api.Click.assert_not_called()

    def test_changed_screenshot_is_reanalysed_before_any_input(self):
        capture = ui.chrome_captcha_snapshot.side_effect
        captures = 0
        def changed(browser, region, path):
            nonlocal captures
            captures += 1
            if captures == 2:
                self.pixels = b"replacement tiles"
            return capture(browser, region, path)
        ui.chrome_captcha_snapshot.side_effect = changed
        self.api.Click.side_effect = lambda *args, **kwargs: setattr(self, "pixels", b"verified widget")
        with patch.object(ai_decision, "captcha_step", side_effect=[
                {"action": "click", "points": [[10, 20]]},
                {"action": "click", "points": [[30, 40]]},
                {"action": "verified"}]) as analyze:
            ui.solve_chrome_captcha("https://signup.example.com/register")
        self.assertEqual(analyze.call_count, 3)
        self.api.Click.assert_called_once_with(130, 240, waitTime=.2)

    def test_analysis_stop_reports_deadline_browser_or_region_change_without_input(self):
        for failure, message in (("deadline", "deadline expired"),
                                 ("browser", "browser changed"),
                                 ("region", "region changed")):
            with self.subTest(failure=failure):
                clock = [0.0]
                def analyze(*args):
                    clock[0] = 91.0 if failure == "deadline" else 2.5
                    return {"action": "click", "points": [[10, 20]]}
                ui.chrome_password_suggestion.side_effect = (
                    [(self.browser, None), (self.browser, None), (None, None)]
                    if failure == "browser" else None)
                ui.chrome_captcha_region.side_effect = (
                    [self.region, node("GroupControl", "Replacement CAPTCHA")]
                    if failure == "region" else None)
                with patch.object(ui.time, "monotonic", side_effect=lambda: clock[0]), \
                     patch.object(ai_decision, "captcha_step", side_effect=analyze):
                    with self.assertRaisesRegex(RuntimeError, message) as stopped:
                        ui.solve_chrome_captcha("https://signup.example.com/register")
                self.assertIn("AI analysis: " + ("91.0s" if failure == "deadline" else "2.5s"),
                              str(stopped.exception))
                self.api.Click.assert_not_called()
                self.answer.GetPattern.return_value.SetValue.assert_not_called()

    def test_waits_for_native_chrome_activation_before_capturing(self):
        self.browser.BoundingRectangle = Mock(left=0, top=0, right=1000, bottom=800)
        self.api.GetForegroundControl.side_effect = chain([None], repeat(self.browser))
        self.region.CaptureToImage.side_effect = lambda path: Path(path).write_bytes(self.pixels)
        ui.chrome_captcha_snapshot.side_effect = self.capture
        self.api.Click.side_effect = lambda *args, **kwargs: setattr(self, "pixels", b"verified widget")
        with patch.object(ai_decision, "captcha_step", side_effect=[
                {"action": "click", "points": [[10, 20]]}, {"action": "verified"}]):
            self.assertIn("confirmed", ui.solve_chrome_captcha("https://signup.example.com/register")["message"])

    def test_site_overlay_missing_widget_or_password_target_never_receives_input(self):
        for failure in ("site", "overlay", "missing", "disappeared", "password"):
            with self.subTest(failure=failure):
                self.api.Click.reset_mock()
                self.answer.GetPattern.return_value.SetValue.reset_mock()
                self.api.ControlFromPoint.return_value = self.tile
                self.answer.IsPassword = failure == "password"
                ui.chrome_password_suggestion.side_effect = None
                ui.chrome_captcha_region.side_effect = None
                if failure == "site":
                    ui.chrome_password_suggestion.side_effect = [(self.browser, None), (self.browser, None), (None, None)]
                elif failure == "overlay":
                    self.api.ControlFromPoint.return_value = node("ButtonControl", "Register account")
                elif failure == "missing":
                    ui.chrome_captcha_region.side_effect = RuntimeError("No visible CAPTCHA frame")
                elif failure == "disappeared":
                    ui.chrome_captcha_region.side_effect = [self.region, RuntimeError("No visible CAPTCHA frame")]
                step = ({"action": "type", "control": 1, "text": "AB12"} if failure == "password" else
                        {"action": "verified"} if failure == "disappeared" else
                        {"action": "click", "points": [[10, 20]]})
                with patch.object(ai_decision, "captcha_step", return_value=step):
                    with self.assertRaises(RuntimeError):
                        ui.solve_chrome_captcha("https://signup.example.com/register")
                self.api.Click.assert_not_called()
                self.answer.GetPattern.return_value.SetValue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
