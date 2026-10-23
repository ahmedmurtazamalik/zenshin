import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import zenshin_mcp


class ChatSetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        self.state = app.load_state(self.path)
        self.state.update(auto_password=True, auto_terms=True,
                          targets=[{"id": "first", "name": "First chat"},
                                   {"id": "second", "name": "Second chat"}])
        self.monitor = {"state": self.state, "path": self.path, "running": True, "connection": None}
        self.ui = Mock()
        self.ui.chat_setup_ready.return_value = True
        self.ui.approval_cards.return_value = []
        self.ui.conversation_pending.return_value = False
        self.threads = {target["id"]: {**target, "turns": []} for target in self.state["targets"]}
        read = patch.object(app, "rpc", side_effect=lambda _connection, _method, params:
                            {"thread": self.threads[params["threadId"]]})
        read.start()
        self.addCleanup(read.stop)
        desktop = patch.object(app, "poll_desktop", side_effect=lambda monitor: app.check_desktop(monitor, self.ui))
        desktop.start()
        self.addCleanup(desktop.stop)

    def poll(self):
        app.poll(self.monitor)

    def restart(self):
        self.state = app.load_state(self.path)
        self.monitor["state"] = self.state

    def test_setup_once_per_selected_chat_survives_restart_reselection_and_rename(self):
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 1)
        self.restart()
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 2)
        self.state["targets"] = []
        self.poll()
        self.state["targets"] = [{"id": "first", "name": "Renamed chat"}]
        self.threads["first"]["name"] = "Renamed chat"
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 2)
        self.state["targets"].append({"id": "new", "name": "New chat"})
        self.threads["new"] = {"id": "new", "name": "New chat", "turns": []}
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_args.args[0], "New chat")
        self.assertEqual(self.ui.send_chat_setup.call_count, 3)

    def test_action_changes_update_each_chat_including_revocation_and_return_to_previous_settings(self):
        self.state["targets"] = self.state["targets"][:1]
        self.poll()
        self.state.update(auto_password=False, auto_terms=False, auto_captcha=True)
        self.poll()
        self.restart()
        self.state.update(auto_password=True, auto_terms=True, auto_captcha=False)
        self.poll()
        self.state.update(auto_password=False, auto_terms=False)
        self.poll()
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 4)
        prompts = [call.args[2] for call in self.ui.send_chat_setup.call_args_list]
        self.assertEqual(prompts[0], prompts[2])
        self.assertIn("CAPTCHA solving: ENABLED", prompts[1])
        self.assertIn("Password filling: DISABLED", prompts[-1])
        self.assertIn("Terms agreement checkboxes: DISABLED", prompts[-1])
        self.assertIn("CAPTCHA solving: DISABLED", prompts[-1])
        self.assertEqual(self.state["chrome_setups"]["first"]["revision"], 4)
        self.assertEqual(len(self.state["attempts"]), 4)

    def test_paused_busy_and_draft_wait_without_journaling_then_send_latest_settings(self):
        self.monitor["running"] = False
        self.poll()
        self.ui.open_chat.assert_not_called()
        self.monitor["running"] = True
        self.threads["first"]["turns"] = [{"id": "working", "status": "inProgress", "items": []}]
        self.ui.chat_setup_ready.return_value = False
        self.poll()
        self.assertEqual(self.state["attempts"], {})
        self.assertIn("empty composer", self.monitor["progress"]["detail"])
        self.state.update(auto_password=False, auto_terms=False)
        self.state.update(auto_password=True, auto_terms=True)
        self.threads["first"]["turns"][-1].update(status="completed", items=[
            {"type": "userMessage", "content": [{"text": "Please continue"}]}])
        self.ui.chat_setup_ready.return_value = True
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_args.args[1], "Please continue")
        self.assertEqual(len(self.state["attempts"]), 1)

    def test_journal_precedes_send_and_uncertain_delivery_is_not_retried_after_restart(self):
        self.state["targets"] = self.state["targets"][:1]

        def send(*_args, **_kwargs):
            saved = app.load_state(self.path)
            self.assertEqual(saved["attempts"]["chrome-setup:first:1"]["status"], "sending")
            self.assertTrue(saved["chrome_setups"]["first"]["actions"]["auto_password"])
            raise RuntimeError("Send result unavailable")

        self.ui.send_chat_setup.side_effect = send
        self.poll()
        self.restart()
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 1)
        self.assertEqual(self.state["attempts"]["chrome-setup:first:1"]["status"], "uncertain")
        self.ui.send_chat_setup.side_effect = None
        self.state["auto_password"] = False
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 2)

    def test_prewrite_deferral_retries_same_setup_after_restart_then_stops_after_success(self):
        self.state["targets"] = self.state["targets"][:1]
        self.ui.send_chat_setup.return_value = False
        self.poll()
        self.assertEqual(self.state["attempts"]["chrome-setup:first:1"]["status"], "waiting")
        self.restart()
        self.ui.send_chat_setup.return_value = True
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 2)
        self.assertEqual(self.state["chrome_setups"]["first"]["revision"], 1)
        self.assertEqual(len(self.state["attempts"]), 1)
        self.assertEqual(self.state["attempts"]["chrome-setup:first:1"]["status"], "sent")
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 2)

    def test_legacy_prewrite_draft_error_recovers_same_setup_revision(self):
        self.state["targets"] = self.state["targets"][:1]
        actions = {key: bool(self.state[key]) for key in ("auto_password", "auto_terms", "auto_captcha")}
        self.state["chrome_setups"] = {"first": {"actions": actions, "revision": 1}}
        self.state["attempts"]["chrome-setup:first:1"] = {
            "kind": "chrome_setup", "thread_id": "first", "name": "First chat", "time": 1,
            "text": "Set up Chrome actions", "response": zenshin_mcp.chrome_setup_prompt(self.state),
            "status": "uncertain", "error": "The composer contains a draft; reply manually"}
        app.save_state(self.path, self.state)
        self.restart()
        self.ui.send_chat_setup.return_value = True
        self.poll()
        self.assertEqual(self.ui.send_chat_setup.call_count, 1)
        self.assertEqual(self.state["chrome_setups"]["first"]["revision"], 1)
        self.assertEqual(len(self.state["attempts"]), 1)
        self.assertEqual(self.state["attempts"]["chrome-setup:first:1"]["status"], "sent")

    def test_event_error_confirms_only_a_new_user_echo_even_in_initially_empty_chat(self):
        self.state["targets"] = self.state["targets"][:1]

        def delivered(_name, _latest, response, **_kwargs):
            self.threads["first"]["turns"].append({"id": "setup", "items": [
                {"type": "userMessage", "content": [{"text": response + "\n"}]}]})
            raise RuntimeError("Event subscriber failed after Send")

        self.ui.send_chat_setup.side_effect = delivered
        self.poll()
        attempt = self.state["attempts"]["chrome-setup:first:1"]
        self.assertEqual(attempt["status"], "sent")
        self.assertEqual(attempt["reply_confirmed_by"], "app_server")
        self.state["auto_password"] = False
        self.ui.send_chat_setup.side_effect = RuntimeError("No new echo")
        self.poll()
        self.assertEqual(self.state["attempts"]["chrome-setup:first:2"]["status"], "uncertain")

    def test_prompt_contains_current_actions_and_native_execution_limits_in_one_paragraph(self):
        prompt = zenshin_mcp.chrome_setup_prompt(self.state)
        for text in ("Password filling: ENABLED (select_chrome_password)",
                     "Terms agreement checkboxes: ENABLED (check_chrome_terms)",
                     "CAPTCHA solving: DISABLED (solve_chrome_captcha)", "replace any earlier",
                     "No acknowledgment", "Codex CLI for analysis only", "Never read or return passwords",
                     "Terms bundled with marketing consent are allowed", "separate marketing opt-ins"):
            self.assertIn(text, prompt)
        self.assertNotIn("\n", prompt)


if __name__ == "__main__":
    unittest.main()
