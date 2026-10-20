import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import app
import windows_ui as ui


def node(role, name="", children=()):
    control = Mock()
    control.ControlTypeName, control.Name = role, name
    control.IsEnabled, control.IsOffscreen = True, False
    control.GetChildren.return_value = list(children)
    for child in children:
        child.GetParentControl.return_value = control
    return control


class PipeTests(unittest.TestCase):
    def test_chat_history_can_arrive_after_ten_seconds(self):
        process = Mock()
        connection = {"process": process, "next_id": 0, "buffer": b""}
        now = 0

        def ready(_pipe):
            nonlocal now
            now = 11
            return True

        with patch.object(app.time, "monotonic", side_effect=lambda: now), \
             patch.object(app, "pipe_ready", side_effect=ready), \
             patch.object(app.os, "read", return_value=b'{"id":1,"result":{"thread":{"id":"selected"}}}\n'):
            result = app.rpc(connection, "thread/read", {"threadId": "selected", "includeTurns": True})
        self.assertEqual(result["thread"]["id"], "selected")

    def test_unresponsive_server_reports_operation_and_still_times_out(self):
        from itertools import count
        for method, timeout in [("thread/read", 60), ("thread/list", 10)]:
            with self.subTest(method=method):
                connection = {"process": Mock(), "next_id": 0, "buffer": b""}
                with patch.object(app.time, "monotonic", side_effect=count(0, 5)), \
                     patch.object(app, "pipe_ready", return_value=False):
                    with self.assertRaisesRegex(RuntimeError, rf"{timeout} seconds \({method}\)"):
                        app.rpc(connection, method, {})

    def test_rpc_reads_split_utf8_messages_notifications_and_reports_eof(self):
        script = '''import json,sys,time
sys.stdin.buffer.readline()
sys.stdout.buffer.write(b'{"method":"notice"}\\n')
sys.stdout.buffer.flush()
message=json.dumps({"id":1,"result":{"name":"caf\\u00e9 \\u0627"}},ensure_ascii=False).encode()
sys.stdout.buffer.write(message[:8]);sys.stdout.buffer.flush();time.sleep(.03)
sys.stdout.buffer.write(message[8:]+b'\\n');sys.stdout.buffer.flush()
sys.stdin.buffer.readline()
sys.stderr.write('test server stopped');sys.stderr.flush()
'''
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=errors)
            connection = {"process": process, "errors": errors, "next_id": 0, "buffer": b""}
            try:
                self.assertEqual(app.rpc(connection, "thread/read", {})["name"], "café ا")
                with self.assertRaisesRegex(RuntimeError, "test server stopped"):
                    app.rpc(connection, "thread/read", {})
            finally:
                app.close_connection(connection)


class AutomationLifetimeTests(unittest.TestCase):
    def test_requests_share_one_mta_until_server_shutdown(self):
        api = Mock()
        api.comtypes.COMError = OSError
        lifecycle = []
        api.comtypes.CoInitializeEx.side_effect = lambda mode: lifecycle.append(("init", mode, threading.get_ident()))
        api.comtypes.CoUninitialize.side_effect = lambda: lifecycle.append(("exit", threading.get_ident()))
        owners = []
        with patch.object(ui, "automation", return_value=api):
            try:
                for _ in range(3):
                    request = threading.Thread(target=lambda: owners.append(ui.run(threading.get_ident)))
                    request.start()
                    request.join(2)
                    self.assertFalse(request.is_alive())
                self.assertEqual(len(owners), 3)
                self.assertEqual(len(set(owners)), 1)
                self.assertEqual(lifecycle, [("init", 0, owners[0])])
                self.assertIsNotNone(api.uiautomation._AutomationClient._instance)
            finally:
                ui.shutdown()
        self.assertEqual(lifecycle[-1], ("exit", owners[0]))
        self.assertIsNone(api.uiautomation._AutomationClient._instance)


class ChromeServerTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows-only action")
    def test_password_action_works_without_codex_and_returns_errors_without_disconnect(self):
        import json
        from pathlib import Path
        import threading
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        servers, ready = [], threading.Event()
        server_class = app.ThreadingHTTPServer
        def create_server(*args):
            server = server_class(("127.0.0.1", 0), args[1])
            servers.append(server)
            ready.set()
            return server
        def post(path="chrome-password", data=None):
            with urlopen(Request(base + "/api/" + path,
                                 data=json.dumps(data or {"site": "https://jobs.example.com"}).encode(),
                                 headers={"Content-Type": "application/json", "Host": "127.0.0.1:8765"}),
                         timeout=2) as response:
                return json.load(response)

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app, "ThreadingHTTPServer", side_effect=create_server), \
             patch("sys.argv", ["app.py", "--state", str(Path(directory) / "state.json")]), \
             patch("builtins.print"), patch.object(ui, "run", side_effect=lambda operation, *args, **kwargs: operation(*args, **kwargs)), \
             patch.object(ui, "prepare_chrome_site", return_value={"message": "Ready"}) as prepare, \
             patch.object(ui, "open_chrome_password_suggestion"), \
             patch.object(ui, "accept_chrome_password", return_value={"message": "Selected"}) as accept:
            worker = threading.Thread(target=app.main, daemon=True)
            worker.start()
            try:
                self.assertTrue(ready.wait(2))
                base = f"http://127.0.0.1:{servers[0].server_port}"
                with self.assertRaises(HTTPError) as error:
                    post("chrome-prepare", {"site": "https://jobs.example.com", "thread_id": "retired-chat"})
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
                prepare.assert_not_called()
                self.assertEqual(post("chrome-prepare"), {"message": "Ready"})
                prepare.assert_called_once_with("https://jobs.example.com")
                accept.assert_not_called()
                self.assertEqual(post(), {"message": "Selected"})
                accept.assert_called_once_with("https://jobs.example.com")
                accept.side_effect = RuntimeError("No suggestion appeared")
                with patch.object(app, "close_connection") as disconnect:
                    with self.assertRaises(HTTPError) as error:
                        post()
                    self.assertEqual(error.exception.code, 503)
                    self.assertEqual(json.load(error.exception), {"error": "No suggestion appeared"})
                    error.exception.close()
                    disconnect.assert_not_called()
                accept.reset_mock()
                prepare.side_effect = RuntimeError("Chrome site is not ready")
                with self.assertRaises(HTTPError) as error:
                    post()
                self.assertEqual(error.exception.code, 503)
                error.exception.close()
                accept.assert_not_called()
            finally:
                if servers:
                    servers[0].shutdown()
                worker.join(2)


class WindowsControlsTests(unittest.TestCase):
    def chrome_form(self, address="https://jobs.example.com/register"):
        api = Mock()
        api.ControlsAreSame.side_effect = lambda first, second: first is second
        address_bar = node("EditControl", "Address and search bar")
        address_bar.GetPattern.return_value.Value = address
        suggestion = node("MenuItemControl", "Use strong password disposable-secret")
        webpage = node("DocumentControl", children=[node("ButtonControl", "Use strong password")])
        webpage.GetPattern.return_value.Value = address
        window = node("WindowControl", children=[address_bar, webpage, suggestion])
        window.ProcessId = 1
        api.GetRootControl.return_value.GetChildren.return_value = [window]
        return api, window, address_bar, webpage, suggestion

    def test_chrome_preparation_opens_target_once_and_waits_until_loading_finishes(self):
        from itertools import count
        api, window, address_bar, webpage, _ = self.chrome_form()
        stop, reload = node("ButtonControl", "Stop loading"), node("ButtonControl", "Reload")
        window.GetChildren.side_effect = [[address_bar, webpage, stop],
                                         [address_bar, webpage, reload], [address_bar, webpage, reload]]
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui, "chrome_password_suggestion", side_effect=[(None, None), (window, None), (window, None), (window, None)]), \
             patch.object(ui.subprocess, "Popen") as launch, \
             patch.object(ui.time, "monotonic", side_effect=count()), patch.object(ui.time, "sleep"):
            result = ui.prepare_chrome_site("https://jobs.example.com/register")
        launch.assert_called_once_with([r"C:\Chrome\chrome.exe", "https://jobs.example.com/register"])
        self.assertIn("finished loading", result["message"])
        webpage.GetChildren.assert_not_called()

    def test_chrome_preparation_preserves_ready_suggestion_and_times_out_on_loading(self):
        from itertools import count
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        window.GetChildren.return_value.append(node("ButtonControl", "Reload"))
        container = node("DocumentControl")
        container.GetPattern.return_value = None
        window.GetChildren.return_value.append(container)
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui.subprocess, "Popen") as launch, \
             patch.object(ui.time, "monotonic", side_effect=count()), patch.object(ui.time, "sleep"):
            ui.prepare_chrome_site("https://jobs.example.com/register")
            launch.assert_not_called()
            suggestion.GetPattern.return_value.Invoke.assert_not_called()
            window.GetChildren.return_value.append(node("ButtonControl", "Stop loading"))
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                ui.prepare_chrome_site("https://jobs.example.com/register", open_site=False)
            launch.assert_not_called()
        webpage.GetChildren.assert_not_called()

    def test_chrome_preparation_opens_requested_path_instead_of_accepting_other_page(self):
        from itertools import count
        api, window, _, webpage, _ = self.chrome_form("https://jobs.example.com/other")
        window.GetChildren.return_value.append(node("ButtonControl", "Reload"))
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui.subprocess, "Popen", side_effect=lambda args: setattr(
                 webpage.GetPattern.return_value, "Value", args[1])) as launch, \
             patch.object(ui.time, "monotonic", side_effect=count()), patch.object(ui.time, "sleep"):
            ui.prepare_chrome_site("https://jobs.example.com/register")
        launch.assert_called_once_with([r"C:\Chrome\chrome.exe", "https://jobs.example.com/register"])

    def test_chrome_selects_native_suggestion_once_without_returning_password(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        def invoke():
            window.GetChildren.return_value = [address_bar, webpage]
        suggestion.GetPattern.return_value.Invoke.side_effect = invoke
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            ui.open_chrome_password_suggestion("https://jobs.example.com/register")
            result = ui.accept_chrome_password("https://jobs.example.com/register")
        self.assertIn("activated and closed", result["message"])
        self.assertNotIn("disposable-secret", str(result))
        suggestion.GetPattern.return_value.Invoke.assert_called_once()
        webpage.GetChildren.assert_not_called()

    def test_password_action_opens_native_suggestion_without_external_desktop_input(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        field = node("EditControl", "New password")
        field.IsPassword, field.HasKeyboardFocus = True, True
        confirmation = node("EditControl", "Confirm password")
        confirmation.IsPassword = True
        webpage.GetChildren.return_value = [field, confirmation]
        window.GetChildren.return_value = [address_bar, webpage]
        command = node("MenuItemControl", "Suggest password\u2026")
        field.Element.QueryInterface.return_value.ShowContextMenu.side_effect = lambda: window.GetChildren.return_value.append(command)
        command.GetPattern.return_value.Invoke.side_effect = lambda: setattr(window.GetChildren, "return_value", [address_bar, webpage, suggestion])
        suggestion.GetPattern.return_value.Invoke.side_effect = lambda: setattr(window.GetChildren, "return_value", [address_bar, webpage])
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui, "prepare_chrome_site"):
            ui.open_chrome_password_suggestion("https://jobs.example.com/register")
            ui.accept_chrome_password("https://jobs.example.com/register")
        field.SetFocus.assert_called_once()
        field.Element.QueryInterface.return_value.ShowContextMenu.assert_called_once()
        command.GetPattern.return_value.Invoke.assert_called_once()
        suggestion.GetPattern.return_value.Invoke.assert_called_once()
        field.GetPattern.assert_not_called()
        confirmation.SetFocus.assert_not_called()

    def test_password_preparation_leaves_ambiguous_fields_untouched(self):
        api, window, address_bar, webpage, _ = self.chrome_form()
        first, second = node("EditControl", "Password"), node("EditControl", "New password")
        first.IsPassword = second.IsPassword = True
        webpage.GetChildren.return_value = [first, second]
        window.GetChildren.return_value = [address_bar, webpage]
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            with self.assertRaisesRegex(RuntimeError, "one new-password field"):
                ui.open_chrome_password_suggestion("https://jobs.example.com/register")
        first.SetFocus.assert_not_called()
        second.SetFocus.assert_not_called()

    def test_chrome_wrong_site_or_webpage_lookalike_is_never_activated(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui.time, "monotonic", side_effect=[0, 0, 31]), \
             patch.object(ui.time, "sleep"), patch.object(ui, "press") as press:
            with self.assertRaisesRegex(RuntimeError, "nothing was selected"):
                ui.accept_chrome_password("https://other.example.com")
            press.assert_not_called()
        window.GetChildren.return_value = [address_bar, webpage]
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            self.assertEqual(ui.chrome_password_suggestion("https://jobs.example.com"), (window, None))
            address_bar.GetPattern.return_value.Value = "chrome://newtab/"
            webpage.GetPattern.return_value.Value = "chrome://newtab/"
            self.assertEqual(ui.chrome_password_suggestion("https://jobs.example.com"), (None, None))
        webpage.GetChildren.assert_not_called()

    def test_chrome_ambiguous_or_changed_suggestions_are_not_activated(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        window.GetChildren.return_value.append(node("MenuItemControl", "Use suggested password another-secret"))
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui, "press") as press:
            with self.assertRaisesRegex(RuntimeError, "Several Chrome"):
                ui.accept_chrome_password("jobs.example.com")
            press.assert_not_called()
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "chrome_password_suggestion", side_effect=[(window, suggestion), (window, None)]), \
             patch.object(ui, "press") as press:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                ui.accept_chrome_password("jobs.example.com")
            press.assert_not_called()

    def test_chrome_unconfirmed_activation_is_not_retried(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui.time, "monotonic", side_effect=[0, 0, 0, 4]):
            with self.assertRaisesRegex(RuntimeError, "inspect Chrome"):
                ui.accept_chrome_password("jobs.example.com")
        suggestion.GetPattern.return_value.Invoke.assert_called_once()

    def test_chrome_site_change_after_activation_requires_manual_review(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        suggestion.GetPattern.return_value.Invoke.side_effect = lambda: setattr(
            webpage.GetPattern.return_value, "Value", "https://other.example.com")
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            with self.assertRaisesRegex(RuntimeError, "site changed"):
                ui.accept_chrome_password("jobs.example.com")
        suggestion.GetPattern.return_value.Invoke.assert_called_once()

    def test_chrome_uses_full_document_url_when_omnibox_omits_scheme(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form("http://127.0.0.1:8877/")
        address_bar.GetPattern.return_value.Value = "127.0.0.1:8877"
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            self.assertEqual(ui.chrome_password_suggestion("http://127.0.0.1:8877"), (window, suggestion))
            self.assertEqual(ui.chrome_password_suggestion("https://127.0.0.1:8877"), (None, None))
        webpage.GetChildren.assert_not_called()

    def test_terms_checks_only_unchecked_agreement_and_leaves_marketing_alone(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        window.GetChildren.return_value = [address_bar, webpage]
        terms = node("CheckBoxControl", "I agree to the Terms and Conditions")
        marketing = node("CheckBoxControl", "I agree to the terms and subscribe to marketing updates")
        toggle = terms.GetPattern.return_value
        toggle.ToggleState = marketing.GetPattern.return_value.ToggleState = 0
        toggle.Toggle.side_effect = lambda: setattr(toggle, "ToggleState", 1)
        webpage.GetChildren.return_value = [terms, marketing]
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            request = ui.chrome_signup_request("https://jobs.example.com", terms=True)
            self.assertEqual(request, {"kind": "terms", "label": terms.Name})
            ui.perform_chrome_signup_request("https://jobs.example.com", request)
            self.assertIsNone(ui.chrome_signup_request("https://jobs.example.com", terms=True))
            self.assertIsNone(ui.chrome_signup_request("https://unrelated.example.com", terms=True))
        toggle.Toggle.assert_called_once()
        marketing.GetPattern.return_value.Toggle.assert_not_called()

    def test_ordinary_reply_confirms_echo_after_invoke_event_error_without_retry(self):
        class EventError(Exception):
            hresult = -2147220991
        api = Mock()
        api.comtypes.COMError = EventError
        value = Mock()
        value.Value = ""
        value.IsReadOnly = False
        value.SetValue.side_effect = lambda text: setattr(value, "Value", text)
        entry = node("EditControl", "Work with Codex")
        entry.GetPattern.return_value = value
        send = node("ButtonControl", "Send")
        container = node("GroupControl", children=[entry, send])
        text = node("TextControl", "Continue?")
        doc = node("DocumentControl", "Test chat", [text, container])
        def invoke():
            doc.GetChildren.return_value = [text, node("TextControl", "Continue the test.")]
            raise EventError()
        send.GetPattern.return_value.Invoke.side_effect = invoke
        with patch.object(ui, "automation", return_value=api), patch.object(ui, "document", return_value=doc):
            ui.reply("Test chat", "Continue?", "Continue the test.")
        send.GetPattern.return_value.Invoke.assert_called_once()

    def test_terms_action_selects_only_the_explicit_label_among_two_agreements(self):
        api, window, address_bar, webpage, _ = self.chrome_form()
        window.GetChildren.return_value = [address_bar, webpage]
        first = node("CheckBoxControl", "I agree to the Terms and Conditions")
        second = node("CheckBoxControl", "I accept the partner terms of service")
        for control in (first, second):
            control.GetPattern.return_value.ToggleState = 0
        first.GetPattern.return_value.Toggle.side_effect = lambda: setattr(first.GetPattern.return_value, "ToggleState", 1)
        webpage.GetChildren.return_value = [first, second]
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            request = ui.chrome_signup_request("https://jobs.example.com", terms=True, label=first.Name)
            ui.perform_chrome_signup_request("https://jobs.example.com", request)
        first.GetPattern.return_value.Toggle.assert_called_once()
        second.GetPattern.return_value.Toggle.assert_not_called()

    def test_reply_matches_hyperlinked_request_and_echo_as_paragraphs(self):
        origin = "http://127.0.0.1:8897/"
        request = "Please enter the password at " + origin + " for the test."
        response = "Zenshin completed the browser action on " + origin + " Continue."
        paragraph = node("GroupControl", children=[node("TextControl", "Please enter the password at "),
            node("HyperlinkControl", origin, [node("TextControl", origin)]), node("TextControl", " for the test.")])
        value = Mock(Value="", IsReadOnly=False)
        value.SetValue.side_effect = lambda text: setattr(value, "Value", text)
        entry, send = node("EditControl", "Work with Codex"), node("ButtonControl", "Send")
        entry.GetPattern.return_value = value
        composer = node("GroupControl", children=[entry, send])
        doc = node("DocumentControl", "Test chat", [paragraph, composer])
        echo = node("GroupControl", children=[node("TextControl", "Zenshin completed the browser action on "),
            node("HyperlinkControl", origin, [node("TextControl", origin)]), node("TextControl", " Continue.")])
        send.GetPattern.return_value.Invoke.side_effect = lambda: doc.GetChildren.return_value.append(echo)
        with patch.object(ui, "automation", return_value=Mock()), patch.object(ui, "document", return_value=doc):
            ui.reply("Test chat", request, response)
        send.GetPattern.return_value.Invoke.assert_called_once()

    def test_codex_packaged_identity_and_duplicate_visible_chats(self):
        doc = node("DocumentControl", "Test chat")
        window = node("WindowControl", "ChatGPT", [doc])
        window.ProcessId = 1
        other = node("WindowControl", "Browser", [node("DocumentControl", "Test chat")])
        other.ProcessId = 2
        root = node("PaneControl", children=[window, other])
        api = Mock()
        api.GetRootControl.return_value = root
        def path(identity):
            return r"C:\Program Files\WindowsApps\OpenAI.Codex_1\app\ChatGPT.exe" if identity == 1 else r"C:\chrome.exe"
        with patch.object(ui, "automation", return_value=api), patch.object(ui, "process_path", side_effect=path):
            self.assertIs(ui.document("Test chat"), doc)
            root.GetChildren.return_value = [window, window]
            with self.assertRaisesRegex(RuntimeError, "multiple desktop windows"):
                ui.document("Test chat")

    def test_placeholder_is_empty_but_matching_user_text_remains_a_draft(self):
        label = node("TextControl", "Reply…")
        placeholder = node("GroupControl", children=[label])
        placeholder.GetPropertyValue.return_value = "readonly=true;multiline=false"
        entry = node("EditControl", "Reply…", [placeholder, node("TextControl", "\n")])
        value = Mock()
        value.Value = "Reply…\n"
        entry.GetPattern.return_value = value
        with patch.object(ui, "automation", return_value=Mock()):
            self.assertEqual(ui.entry_text(entry), "")
            placeholder.GetPropertyValue.return_value = "readonly=false"
            self.assertEqual(ui.entry_text(entry), "Reply…")
            with self.assertRaisesRegex(RuntimeError, "contains a draft"):
                ui.write_text("Test chat", entry, "replacement")
            value.SetValue.assert_not_called()

    def test_custom_answer_readback_and_draft_preservation(self):
        entry, send, question = node("EditControl", "Reply…"), node("ButtonControl", "Send"), node("TextControl", "Complete test?")
        form = node("GroupControl", children=[question, entry, send])
        doc = node("DocumentControl", "Test chat", [form])
        draft = ""
        def write(_name, _entry, response):
            nonlocal draft
            draft = response
        def press(_button):
            doc.GetChildren.return_value = [node("TextControl", draft)]
        with patch.object(ui, "document", return_value=doc), \
             patch.object(ui, "entry_text", side_effect=lambda _entry: draft), \
             patch.object(ui, "write_text", side_effect=write) as fill, \
             patch.object(ui, "press", side_effect=press) as activate:
            ui.answer("Test chat", "Complete test?", "Custom café {Enter}")
            activate.assert_called_once_with(send)
            doc.GetChildren.return_value = [form]
            draft = "Unfinished user answer"
            activate.reset_mock()
            fill.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "contains a draft"):
                ui.answer("Test chat", "Complete test?", "replacement")
            activate.assert_not_called()
            fill.assert_not_called()

    def test_open_chat_reveals_latest_messages_without_reopening_or_sending(self):
        bottom = node("ButtonControl", "Scroll to bottom")
        doc = node("DocumentControl", "Test chat", [bottom])
        with patch.object(ui, "document", return_value=doc), \
             patch.object(ui.os, "startfile", create=True) as launch, \
             patch.object(ui, "press") as press:
            ui.open_chat("selected", "Test chat")
            launch.assert_not_called()
            press.assert_called_once_with(bottom)

    def test_navigation_timeout_and_one_time_only_approval(self):
        with patch.object(ui, "document", return_value=None), \
             patch.object(ui.os, "startfile", create=True) as launch, \
             patch.object(ui.time, "monotonic", side_effect=[0, 0, 11]):
            with self.assertRaisesRegex(RuntimeError, "did not appear"):
                ui.open_chat("selected/id", "Test chat")
            launch.assert_called_once_with("codex://threads/selected%2Fid")
        with patch.object(ui, "press") as press, patch.object(ui, "approval_forms", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "one-time"):
                ui.approve("Test chat", "Read probe?", "Always allow")
            with self.assertRaisesRegex(RuntimeError, "changed"):
                ui.approve("Test chat", "Read probe?", "Allow once")
            press.assert_not_called()

    def test_approval_includes_context_beyond_button_row(self):
        allow, deny = node("ButtonControl", "Allow once"), node("ButtonControl", "Deny")
        row = node("GroupControl", children=[deny, allow])
        form = node("GroupControl", children=[node("TextControl", "Permissions"),
                                             node("TextControl", "Read the disposable file?"), row])
        doc = node("DocumentControl", "Test chat", [form])
        with patch.object(ui, "document", return_value=doc), patch.object(ui, "automation", return_value=Mock()):
            self.assertEqual(ui.approval_cards("Test chat"), [
                {"text": "Permissions\nRead the disposable file?", "options": ["Allow once"]}])
            form.GetChildren.return_value.append(node("EditControl", "Work with Codex"))
            self.assertEqual(ui.approval_cards("Test chat"), [])


if __name__ == "__main__":
    unittest.main()
