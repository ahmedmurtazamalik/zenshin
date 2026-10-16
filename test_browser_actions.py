import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import app
import windows_ui as ui


class BrowserActionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        self.state = app.load_state(self.path)
        self.state.update(mode="desktop", auto_password=True, auto_terms=True)
        self.monitor = {"path": self.path, "state": self.state, "running": False, "connection": None}
        platform = Mock(wraps=app.os)
        platform.name = "nt"
        for item in (patch.object(app, "os", platform),
                     patch.object(ui, "run", side_effect=lambda operation: operation()),
                     patch.object(ui, "prepare_chrome_site"),
                     patch.object(ui, "open_chrome_password_suggestion"),
                     patch.object(ui, "chrome_signup_request", side_effect=lambda origin, password, terms, label:
                                  {"kind": "password" if password else "terms", "label": label or "Chrome suggested password"}),
                     patch.object(ui, "perform_chrome_signup_request"), patch.object(ui, "reply"),
                     patch.object(ui, "open_chat")):
            item.start()
            self.addCleanup(item.stop)
        self.request = {"action": "password", "site": "https://jobs.example.com/register", "request_id": "password-1"}

    def test_each_action_returns_a_journaled_receipt_without_chat_delivery_or_repeat(self):
        def perform(origin, request):
            saved = app.load_state(self.path)
            self.assertEqual(saved["attempts"]["browser:" + data["request_id"]]["status"], "sending")
        ui.perform_chrome_signup_request.side_effect = perform
        for data in (self.request, {**self.request, "action": "terms", "request_id": "terms-1", "label": "I agree to the Terms"}):
            receipt = app.browser_action(self.monitor, data)
            self.assertTrue(receipt["confirmed"])
            self.assertEqual(receipt["action"], data["action"])
            ui.prepare_chrome_site.assert_called_with(data["site"], open_site=False)
            self.monitor["state"] = app.load_state(self.path)
            self.assertTrue(app.browser_action(self.monitor, data)["replayed"])
        self.assertEqual(ui.perform_chrome_signup_request.call_count, 2)
        ui.chrome_signup_request.assert_called_with("https://jobs.example.com", password=False,
                                                    terms=True, label="I agree to the Terms")
        ui.reply.assert_not_called()
        ui.open_chat.assert_not_called()
        with self.assertRaisesRegex(ValueError, "different browser action"):
            app.browser_action(self.monitor, {**self.request, "site": "https://other.example.com"})

    def test_preview_disabled_action_and_linux_never_inspect_chrome(self):
        self.state["mode"] = "preview"
        with self.assertRaisesRegex(ValueError, "Enable"):
            app.browser_action(self.monitor, self.request)
        self.state.update(mode="desktop", auto_password=False)
        with self.assertRaisesRegex(ValueError, "Enable"):
            app.browser_action(self.monitor, self.request)
        self.state["auto_password"] = True
        with patch.object(app.os, "name", "posix"):
            with self.assertRaisesRegex(ValueError, "Windows"):
                app.browser_action(self.monitor, self.request)
        ui.run.assert_not_called()
        self.assertEqual(self.state["attempts"], {})

    def test_uncertain_action_blocks_retries_after_restart_even_with_another_id(self):
        ui.perform_chrome_signup_request.side_effect = RuntimeError("Selection was not confirmed")
        with self.assertRaisesRegex(RuntimeError, "do not retry"):
            app.browser_action(self.monitor, self.request)
        self.monitor["state"] = app.load_state(self.path)
        for data in (self.request, {**self.request, "request_id": "new-id"}):
            with self.assertRaises(RuntimeError):
                app.browser_action(self.monitor, data)
        ui.perform_chrome_signup_request.assert_called_once()
        self.assertEqual(self.monitor["state"]["attempts"]["browser:password-1"]["status"], "uncertain")

    def test_missing_or_unmatched_terms_label_never_activates_a_control(self):
        with self.assertRaisesRegex(ValueError, "exact checkbox label"):
            app.browser_action(self.monitor, {**self.request, "action": "terms"})
        ui.chrome_signup_request.return_value = None
        ui.chrome_signup_request.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "not available"):
            app.browser_action(self.monitor, {**self.request, "action": "terms", "label": "Other terms"})
        ui.perform_chrome_signup_request.assert_not_called()

    def test_monitor_does_not_interpret_password_refusals_as_browser_requests(self):
        self.state["targets"] = [{"id": "chat", "name": "Job search"}]
        thread = {"name": "Job search", "id": "chat", "turns": [{"id": "turn", "status": "completed", "items": [
            {"type": "agentMessage", "id": "reply", "text": "I cannot enter the password at https://jobs.example.com"}]}]}
        desktop = Mock()
        desktop.approval_cards.return_value = []
        desktop.conversation_pending.return_value = False
        self.monitor["previews"] = []
        with patch.object(app, "rpc", return_value={"thread": thread}):
            app.check_desktop(self.monitor, desktop)
        desktop.chrome_signup_request.assert_not_called()
        desktop.perform_chrome_signup_request.assert_not_called()

    def test_stdio_client_receives_actual_http_action_results_and_errors(self):
        app.save_state(self.path, self.state)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        servers, ready = [], threading.Event()
        server_class = app.ThreadingHTTPServer
        def create_server(*args):
            server = server_class(*args)
            servers.append(server)
            ready.set()
            return server
        messages = [
            {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}}},
            {"method": "notifications/initialized"}, {"id": 2, "method": "tools/list"},
            {"id": 3, "method": "tools/call", "params": {"name": "select_chrome_password", "arguments": {
                "site": self.request["site"], "request_id": "mcp-password"}}},
            {"id": 4, "method": "tools/call", "params": {"name": "check_chrome_terms", "arguments": {
                "site": self.request["site"], "request_id": "mcp-terms", "label": "I agree to the Terms"}}},
            {"id": 5, "method": "tools/call", "params": {"name": "check_chrome_terms", "arguments": {
                "site": self.request["site"], "request_id": "missing-label"}}},
            {"id": 6, "method": "tools/call", "params": {"name": "check_chrome_terms", "arguments": {
                "site": self.request["site"], "request_id": "absent-terms", "label": "Absent terms"}}},
        ]
        available = ui.chrome_signup_request.side_effect
        ui.chrome_signup_request.side_effect = lambda origin, password, terms, label: (
            None if label == "Absent terms" else available(origin, password, terms, label))
        with patch.object(app, "ThreadingHTTPServer", side_effect=create_server), \
             patch("sys.argv", ["app.py", "--port", str(port), "--state", str(self.path)]), \
             patch("builtins.print"), patch.object(ui, "shutdown"), patch.object(app, "close_connection") as close:
            worker = threading.Thread(target=app.main)
            worker.start()
            try:
                self.assertTrue(ready.wait(2))
                process = subprocess.run([sys.executable, "-B", str(app.ROOT / "zenshin_mcp.py"), "--port", str(port)],
                    input="".join(json.dumps({"jsonrpc": "2.0", **message}) + "\n" for message in messages),
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stderr)
                replies = {reply["id"]: reply["result"] for reply in map(json.loads, process.stdout.splitlines())}
                self.assertEqual(len(replies[2]["tools"]), 2)
                for identity in (3, 4):
                    self.assertFalse(replies[identity]["isError"])
                    self.assertTrue(replies[identity]["structuredContent"]["confirmed"])
                self.assertTrue(replies[5]["isError"])
                self.assertTrue(replies[6]["isError"])
                self.assertIn("do not retry", replies[6]["content"][0]["text"])
                self.assertEqual(ui.perform_chrome_signup_request.call_count, 2)
                self.assertEqual(len(app.load_state(self.path)["attempts"]), 3)
                close.assert_not_called()
            finally:
                if servers:
                    servers[0].shutdown()
                worker.join(2)


if __name__ == "__main__":
    unittest.main()
