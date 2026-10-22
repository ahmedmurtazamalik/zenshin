import json
from http.client import RemoteDisconnected
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

import app
import windows_ui as ui
import zenshin_mcp


class BrowserActionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        self.state = app.load_state(self.path)
        self.state.update(auto_password=True, auto_terms=True)
        self.monitor = {"path": self.path, "state": self.state, "running": True, "connection": None}
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
            saved = app.load_state(self.path)
            logged = saved["activity"][-1]
            self.assertEqual(logged["status"], "sent")
            self.assertEqual(logged["request"], {
                "action": data["action"], "site": data["site"], "label": data.get("label", "")})
            ui.prepare_chrome_site.assert_called_with(data["site"], open_site=False)
            self.monitor["state"] = saved
            self.assertTrue(app.browser_action(self.monitor, data)["replayed"])
        self.assertEqual(ui.perform_chrome_signup_request.call_count, 2)
        ui.chrome_signup_request.assert_called_with("https://jobs.example.com", password=False,
                                                    terms=True, label="I agree to the Terms")
        ui.reply.assert_not_called()
        ui.open_chat.assert_not_called()
        with self.assertRaisesRegex(ValueError, "different browser action"):
            app.browser_action(self.monitor, {**self.request, "site": "https://other.example.com"})

    def test_paused_disabled_action_and_linux_never_inspect_chrome(self):
        self.monitor["running"] = False
        with self.assertRaisesRegex(ValueError, "Start monitoring"):
            app.browser_action(self.monitor, self.request)
        self.monitor["running"] = True
        self.state["auto_password"] = False
        with self.assertRaisesRegex(ValueError, "Enable"):
            app.browser_action(self.monitor, self.request)
        self.state["auto_password"] = True
        with patch.object(app.os, "name", "posix"):
            with self.assertRaisesRegex(ValueError, "Windows"):
                app.browser_action(self.monitor, self.request)
        ui.run.assert_not_called()
        self.assertEqual(self.state["attempts"], {})

    def test_uncertain_action_blocks_same_request_after_restart_but_allows_a_new_action(self):
        ui.perform_chrome_signup_request.side_effect = RuntimeError("Selection was not confirmed")
        with self.assertRaisesRegex(RuntimeError, "do not retry"):
            app.browser_action(self.monitor, self.request)
        self.assertTrue(self.monitor["running"])
        self.monitor["state"] = app.load_state(self.path)
        with self.assertRaisesRegex(RuntimeError, "already"):
            app.browser_action(self.monitor, self.request)
        ui.perform_chrome_signup_request.assert_called_once()
        self.assertEqual(self.monitor["state"]["attempts"]["browser:password-1"]["status"], "uncertain")
        ui.perform_chrome_signup_request.side_effect = None
        receipt = app.browser_action(self.monitor, {
            "action": "terms", "site": "https://other.example.com/register",
            "request_id": "terms-2", "label": "I agree to the Terms"})
        self.assertTrue(receipt["confirmed"])
        self.assertEqual(ui.perform_chrome_signup_request.call_count, 2)

    def test_terms_label_is_optional_but_missing_agreement_never_activates_a_control(self):
        receipt = app.browser_action(self.monitor, {**self.request, "action": "terms", "request_id": "no-label"})
        self.assertTrue(receipt["confirmed"])
        ui.chrome_signup_request.assert_called_with("https://jobs.example.com", password=False, terms=True, label=None)
        ui.perform_chrome_signup_request.reset_mock()
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
        with patch.object(app, "rpc", return_value={"thread": thread}), \
             patch.object(app, "analyze_request") as analyze:
            app.check_desktop(self.monitor, desktop)
        analyze.assert_not_called()
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
                with urlopen(Request(f"http://127.0.0.1:{port}/api/start", data=b"{}",
                                     headers={"Content-Type": "application/json"}), timeout=2) as response:
                    self.assertTrue(json.load(response)["running"])
                process = subprocess.run([sys.executable, "-B", str(app.ROOT / "zenshin_mcp.py"), "--port", str(port)],
                    input="".join(json.dumps({"jsonrpc": "2.0", **message}) + "\n" for message in messages),
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stderr)
                replies = {reply["id"]: reply["result"] for reply in map(json.loads, process.stdout.splitlines())}
                self.assertIn("Use Zenshin automatically", replies[1]["instructions"])
                self.assertIn("standing authorization", replies[1]["instructions"])
                self.assertEqual(len(replies[2]["tools"]), 2)
                for identity in (3, 4):
                    self.assertFalse(replies[identity]["isError"])
                    self.assertTrue(replies[identity]["structuredContent"]["confirmed"])
                self.assertFalse(replies[5]["isError"])
                self.assertTrue(replies[6]["isError"])
                self.assertIn("do not retry", replies[6]["content"][0]["text"])
                self.assertEqual(ui.perform_chrome_signup_request.call_count, 3)
                self.assertEqual(len(app.load_state(self.path)["attempts"]), 4)
                # A client can time out after the native action has completed.
                end_headers = app.BaseHTTPRequestHandler.end_headers
                def disconnected_headers(handler):
                    if handler.path == "/api/browser-action":
                        raise ConnectionResetError("Test client disconnected before response headers")
                    return end_headers(handler)
                with patch.object(app.BaseHTTPRequestHandler, "end_headers", autospec=True,
                                  side_effect=disconnected_headers):
                    with self.assertRaises(RemoteDisconnected):
                        urlopen(Request(f"http://127.0.0.1:{port}/api/browser-action",
                                        data=json.dumps({**self.request, "request_id": "disconnected-client"}).encode(),
                                        headers={"Content-Type": "application/json"}), timeout=2)
                with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as response:
                    current = json.load(response)
                self.assertTrue(current["running"])
                self.assertEqual(current["activity"][-1]["status"], "sent")
                close.assert_not_called()
            finally:
                if servers:
                    servers[0].shutdown()
                worker.join(2)


class CodexGuidanceTests(unittest.TestCase):
    def test_updates_active_instructions_block_without_changing_personal_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            agents.write_bytes(b"Keep my default instructions.\r\n")
            override = root / "AGENTS.override.md"
            before, after = b"# Personal instructions\r\n\r\n", b"\r\n\r\nKeep this ending.\r\n"
            override.write_bytes(before + b"<!-- Zenshin instructions: begin -->\r\nOld guidance\r\n"
                                 b"<!-- Zenshin instructions: end -->" + after)
            with patch.dict(zenshin_mcp.os.environ, {"CODEX_HOME": directory}):
                self.assertEqual(zenshin_mcp.install_codex_guidance(), override)
                installed = override.read_bytes()
                zenshin_mcp.install_codex_guidance()
                self.assertEqual(override.read_bytes(), installed)
            self.assertTrue(installed.startswith(before))
            self.assertTrue(installed.endswith(after))
            self.assertEqual(installed.count(b"<!-- Zenshin instructions: begin -->"), 1)
            self.assertIn(b"Use Zenshin automatically", installed)
            self.assertEqual(agents.read_bytes(), b"Keep my default instructions.\r\n")


if __name__ == "__main__":
    unittest.main()
