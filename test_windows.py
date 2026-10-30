import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, PropertyMock, patch

import app
import windows_ui as ui


def node(role, name="", children=()):
    control = Mock()
    control.ControlTypeName, control.Name = role, name
    control.IsEnabled, control.IsOffscreen = True, False
    control.HelpText, control.AutomationId = "", ""
    control.HasKeyboardFocus, control.IsPassword = False, False
    control.GetParentControl.return_value = None
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
    def test_readiness_distinguishes_missing_documents_from_documents_without_urls(self):
        blank = node("DocumentControl")
        blank.GetPattern.return_value = None
        for documents in ([], [blank]):
            with self.subTest(document_count=len(documents)), patch.object(ui, "automation", return_value=Mock()):
                diagnostics = {}
                self.assertIsNone(ui.chrome_page_document(node("WindowControl"), documents, diagnostics))
                self.assertEqual(diagnostics["reason"],
                                 f"native documents: {len(documents)}; HTTP documents: 0; active page candidates: 0")

    def setUp(self):
        selection = patch.object(ui.ai_decision, "select_browser_control", return_value=0)
        self.select = selection.start()
        self.addCleanup(selection.stop)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only action")

    def chrome_form(self, address="https://jobs.example.com/register"):
        api = Mock()
        api.ControlsAreSame.side_effect = lambda first, second: first is second
        address_bar = node("EditControl", "Address and search bar")
        address_bar.GetPattern.return_value.Value = address
        suggestion = node("MenuItemControl", "Use strong password disposable-secret")
        webpage = node("DocumentControl", children=[node("ButtonControl", "Use strong password")])
        webpage.GetPattern.return_value.Value = address
        password = node("EditControl", "New password")
        password.IsPassword, password.HasKeyboardFocus = True, True
        password.GetPattern.return_value.DocumentRange.textRange.CompareEndpoints.return_value = -1
        password.GetPattern.return_value.DocumentRange.textRange.Clone.return_value.CompareEndpoints.return_value = -1
        webpage.GetChildren.return_value.append(password)
        window = node("WindowControl", children=[address_bar, webpage, suggestion])
        window.ProcessId = 1
        api.GetRootControl.return_value.GetChildren.return_value = [window]
        windows = patch.object(ui, "chrome_windows", return_value=[window])
        windows.start()
        self.addCleanup(windows.stop)
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
            with self.assertRaisesRegex(RuntimeError, "Chrome site is not ready:.*stop present: True"):
                ui.prepare_chrome_site("https://jobs.example.com/register", open_site=False)
            launch.assert_not_called()
        webpage.GetChildren.assert_not_called()

    def test_chrome_preparation_waits_for_initial_accessibility_elements(self):
        from itertools import count
        api, window, _, _, _ = self.chrome_form()
        api.comtypes.COMError = OSError
        window.GetChildren.return_value.append(node("ButtonControl", "Reload"))
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "chrome_password_suggestion", side_effect=[OSError("Chrome page opening"), (window, None), (window, None)]), \
             patch.object(ui.time, "monotonic", side_effect=count()), patch.object(ui.time, "sleep"):
            self.assertIn("finished loading", ui.prepare_chrome_site("https://jobs.example.com/register")["message"])

    def test_chrome_preparation_uses_active_page_among_native_documents(self):
        from itertools import count
        api, window, address_bar, webpage, _ = self.chrome_form()
        webpage.Name = "Registration"
        window.Name = "Registration - Google Chrome"
        other = node("DocumentControl", "Another page")
        other.GetPattern.return_value.Value = "https://other.example.com/"
        window.GetChildren.return_value = [address_bar, webpage, other, node("ButtonControl", "Reload")]
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui.subprocess, "Popen") as launch, \
             patch.object(ui.time, "monotonic", side_effect=count()), patch.object(ui.time, "sleep"):
            self.assertIn("finished loading", ui.prepare_chrome_site(
                "https://jobs.example.com/register", open_site=False)["message"])
            window.Name = "Another page - Google Chrome"
            self.assertEqual(ui.chrome_password_suggestion("https://jobs.example.com"), (None, None))
            launch.assert_not_called()
        webpage.GetChildren.assert_not_called()
        other.GetChildren.assert_not_called()

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
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui, "prepare_chrome_site"):
            selected = ui.open_chrome_password_suggestion("https://jobs.example.com/register")
            result = ui.accept_chrome_password("https://jobs.example.com/register", selected)
        self.assertIn("remained filled", result["message"])
        self.assertNotIn("disposable-secret", str(result))
        self.assertNotIn("disposable-secret", str(self.select.call_args_list))
        suggestion.GetPattern.return_value.Invoke.assert_called_once()
        field = webpage.GetChildren.return_value[-1]
        field.GetPattern.assert_called_with(api.PatternId.TextPattern)
        field.GetPattern.return_value.DocumentRange.GetText.assert_not_called()

    def test_closed_password_popup_requires_fields_to_remain_filled(self):
        from itertools import count
        for filled in ([False], [True, False]):
            with self.subTest(filled=filled):
                api, window, _, _, suggestion = self.chrome_form()
                samples = iter(filled)
                last = False
                def password_filled(*_args):
                    nonlocal last
                    last = next(samples, last)
                    return last
                with patch.object(ui, "automation", return_value=api), \
                     patch.object(ui, "chrome_password_suggestion", side_effect=[(window, suggestion), (window, suggestion)] + [(window, None)] * 10), \
                     patch.object(ui, "chrome_password_filled", side_effect=password_filled, create=True), \
                     patch.object(ui, "press") as activate, \
                     patch.object(ui.time, "monotonic", side_effect=count(0, .6)), \
                     patch.object(ui.time, "sleep"):
                    with self.assertRaisesRegex(RuntimeError, "filled"):
                        ui.accept_chrome_password("https://jobs.example.com/register")
                activate.assert_called_once_with(suggestion)

    def test_empty_password_embedded_object_is_not_filled(self):
        api, window, _, webpage, _ = self.chrome_form()
        field = webpage.GetChildren.return_value[-1]
        extent = field.GetPattern.return_value.DocumentRange.textRange
        extent.Clone.return_value.CompareEndpoints.return_value = 0
        with patch.object(ui, "automation", return_value=api):
            self.assertFalse(ui.chrome_password_filled(window, "https://jobs.example.com"))

    def test_password_action_opens_native_suggestion_without_external_desktop_input(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        field = node("EditControl", "New password")
        field.IsPassword, field.HasKeyboardFocus = True, True
        confirmation = node("EditControl", "Confirm password")
        confirmation.IsPassword = True
        for control in (field, confirmation):
            control.GetPattern.return_value.DocumentRange.textRange.Clone.return_value.CompareEndpoints.return_value = -1
        webpage.GetChildren.return_value = [field, confirmation]
        window.GetChildren.return_value = [address_bar, webpage]
        command = node("MenuItemControl", "Suggest password\u2026")
        field.Element.QueryInterface.return_value.ShowContextMenu.side_effect = lambda: window.GetChildren.return_value.append(command)
        command.GetPattern.return_value.Invoke.side_effect = lambda: setattr(window.GetChildren, "return_value", [address_bar, webpage, suggestion])
        suggestion.GetPattern.return_value.Invoke.side_effect = lambda: setattr(window.GetChildren, "return_value", [address_bar, webpage])
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"), \
             patch.object(ui, "prepare_chrome_site"):
            selected = ui.open_chrome_password_suggestion("https://jobs.example.com/register")
            ui.accept_chrome_password("https://jobs.example.com/register", selected)
        field.SetFocus.assert_called_once()
        field.Element.QueryInterface.return_value.ShowContextMenu.assert_called_once()
        command.GetPattern.return_value.Invoke.assert_called_once()
        suggestion.GetPattern.return_value.Invoke.assert_called_once()
        field.GetPattern.assert_called_with(api.PatternId.TextPattern)
        confirmation.GetPattern.assert_not_called()
        confirmation.SetFocus.assert_not_called()

    def test_password_preparation_leaves_ambiguous_fields_untouched(self):
        api, window, address_bar, webpage, _ = self.chrome_form()
        first, second = node("EditControl", "Password"), node("EditControl", "New password")
        first.IsPassword = second.IsPassword = True
        self.select.return_value = None
        webpage.GetChildren.return_value = [first, second]
        window.GetChildren.return_value = [address_bar, webpage]
        with patch.object(ui, "automation", return_value=api), \
             patch.object(ui, "process_path", return_value=r"C:\Chrome\chrome.exe"):
            with self.assertRaisesRegex(RuntimeError, "one new-password field"):
                ui.open_chrome_password_suggestion("https://jobs.example.com/register")
        first.SetFocus.assert_not_called()
        second.SetFocus.assert_not_called()

    def test_password_waits_for_native_focus_before_opening_suggestion(self):
        from itertools import count
        for focused in (True, False):
            with self.subTest(focused=focused):
                api, window, _, webpage, _ = self.chrome_form()
                field = webpage.GetChildren.return_value[-1]
                field.SetFocus.return_value = False
                focus = PropertyMock(side_effect=[False, focused, focused]) if focused else PropertyMock(return_value=False)
                with patch.object(type(field), "HasKeyboardFocus", focus, create=True), \
                     patch.object(ui, "automation", return_value=api), \
                     patch.object(ui, "prepare_chrome_site"), \
                     patch.object(ui.time, "monotonic", side_effect=count()), patch.object(ui.time, "sleep"):
                    if focused:
                        self.assertIs(ui.open_chrome_password_suggestion("https://jobs.example.com/register")["control"], field)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "did not focus"):
                            ui.open_chrome_password_suggestion("https://jobs.example.com/register")
                        field.Element.QueryInterface.assert_not_called()
                window.SetActive.assert_called_once()
                field.SetFocus.assert_called_once()

    def test_terms_scrolls_selected_agreement_and_preserves_offscreen_label_context(self):
        for revealed in (True, False):
            with self.subTest(revealed=revealed):
                api, window, address_bar, webpage, _ = self.chrome_form()
                window.GetChildren.return_value = [address_bar, webpage]
                agreement = node("CheckBoxControl")
                label = node("TextControl", "I accept the service agreement")
                agreement.IsOffscreen = label.IsOffscreen = True
                marketing = node("CheckBoxControl", "Send offers")
                toggle, scroll = Mock(ToggleState=0), Mock()
                agreement.GetPattern.side_effect = lambda pattern: scroll if pattern == api.PatternId.ScrollItemPattern else toggle
                scroll.ScrollIntoView.side_effect = lambda: setattr(agreement, "IsOffscreen", not revealed)
                toggle.Toggle.side_effect = lambda: setattr(toggle, "ToggleState", 1)
                marketing.GetPattern.return_value.ToggleState = 0
                webpage.GetChildren.return_value = [node("GroupControl", children=[agreement, label]), marketing]
                with patch.object(ui, "automation", return_value=api), patch.object(ui.time, "sleep"):
                    request = ui.chrome_signup_request("https://jobs.example.com", terms=True)
                    self.assertIsNotNone(request)
                    self.assertIn(label.Name, self.select.call_args.args[1][0]["nearby_text"])
                    if revealed:
                        ui.perform_chrome_signup_request("https://jobs.example.com", request)
                        toggle.Toggle.assert_called_once()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "offscreen"):
                            ui.perform_chrome_signup_request("https://jobs.example.com", request)
                        toggle.Toggle.assert_not_called()
                scroll.ScrollIntoView.assert_called_once()
                marketing.GetPattern.return_value.Toggle.assert_not_called()

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
            with self.assertRaisesRegex(RuntimeError, "did not remain filled"):
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
            self.assertEqual(request["label"], terms.Name)
            self.assertIs(request["control"], terms)
            ui.perform_chrome_signup_request("https://jobs.example.com", request)
            self.select.return_value = None
            self.assertIsNone(ui.chrome_signup_request("https://jobs.example.com", terms=True))
            self.assertIsNone(ui.chrome_signup_request("https://unrelated.example.com", terms=True))
        toggle.Toggle.assert_called_once()
        marketing.GetPattern.return_value.Toggle.assert_not_called()

    def test_terms_accepts_paraphrased_hint_and_bundled_marketing_using_nearby_text(self):
        api, window, address_bar, webpage, _ = self.chrome_form()
        window.GetChildren.return_value = [address_bar, webpage]
        agreement = node("CheckBoxControl")
        separate = node("CheckBoxControl", "Send me offers")
        row = node("GroupControl", children=[agreement, node("TextControl",
            "By joining, I acknowledge the User Agreement and consent to product emails.")])
        webpage.GetChildren.return_value = [row, separate]
        for control in (agreement, separate):
            control.GetPattern.return_value.ToggleState = 0
        toggle = agreement.GetPattern.return_value
        toggle.Toggle.side_effect = lambda: setattr(toggle, "ToggleState", 1)
        with patch.object(ui, "automation", return_value=api):
            request = ui.chrome_signup_request("https://jobs.example.com", terms=True, label="Accept signup agreement")
            candidates = self.select.call_args.args[1]
            self.assertIn("User Agreement", candidates[0]["nearby_text"])
            self.assertEqual(self.select.call_args.kwargs["hint"], "Accept signup agreement")
            ui.perform_chrome_signup_request("https://jobs.example.com", request)
        self.select.assert_called_once()
        toggle.Toggle.assert_called_once()
        separate.GetPattern.return_value.Toggle.assert_not_called()

    def test_terms_rechecks_control_identity_and_wording_after_analysis(self):
        api, window, address_bar, webpage, _ = self.chrome_form()
        window.GetChildren.return_value = [address_bar, webpage]
        agreement = node("CheckBoxControl", "Our user agreement applies")
        agreement.GetPattern.return_value.ToggleState = 0
        webpage.GetChildren.return_value = [agreement]
        with patch.object(ui, "automation", return_value=api):
            request = ui.chrome_signup_request("https://jobs.example.com", terms=True)
            agreement.Name = "Receive promotional messages"
            with self.assertRaisesRegex(RuntimeError, "changed"):
                ui.perform_chrome_signup_request("https://jobs.example.com", request)
            replacement = node("CheckBoxControl", request["label"])
            webpage.GetChildren.return_value = [replacement]
            with self.assertRaisesRegex(RuntimeError, "changed"):
                ui.perform_chrome_signup_request("https://jobs.example.com", request)
        agreement.GetPattern.return_value.Toggle.assert_not_called()
        replacement.GetPattern.return_value.Toggle.assert_not_called()

    def test_password_uses_semantic_field_selection_and_ignores_unrelated_empty_fields(self):
        api, window, address_bar, webpage, suggestion = self.chrome_form()
        current = node("EditControl", "Mot de passe actuel")
        new = node("EditControl", "Choisissez votre secret")
        confirmation = node("EditControl", "Saisissez-le de nouveau")
        for control in (current, new, confirmation):
            control.IsPassword = True
        new.HasKeyboardFocus = True
        new.GetPattern.return_value.DocumentRange.textRange.Clone.return_value.CompareEndpoints.return_value = -1
        webpage.GetChildren.return_value = [current, new, confirmation]
        self.select.return_value = 1
        suggestion.GetPattern.return_value.Invoke.side_effect = lambda: setattr(
            window.GetChildren, "return_value", [address_bar, webpage])
        with patch.object(ui, "automation", return_value=api), patch.object(ui.time, "sleep"), \
             patch.object(ui, "prepare_chrome_site"):
            field = ui.open_chrome_password_suggestion("https://jobs.example.com/register")
            self.assertIs(field["control"], new)
            result = ui.accept_chrome_password("https://jobs.example.com/register", field)
        self.assertIn("remained filled", result["message"])
        self.select.assert_called_once()
        new.SetFocus.assert_called_once()
        current.GetPattern.assert_not_called()
        confirmation.GetPattern.assert_not_called()
        new.GetPattern.assert_called_with(api.PatternId.TextPattern)
        new.GetPattern.return_value.DocumentRange.GetText.assert_not_called()

    def test_password_rechecks_selected_field_wording_before_accepting(self):
        api, window, _, webpage, suggestion = self.chrome_form()
        field = webpage.GetChildren.return_value[-1]
        with patch.object(ui, "automation", return_value=api), patch.object(ui, "prepare_chrome_site"):
            selected = ui.open_chrome_password_suggestion("https://jobs.example.com/register")
            field.Name = "Current password"
            with self.assertRaisesRegex(RuntimeError, "password field changed"):
                ui.accept_chrome_password("https://jobs.example.com/register", selected)
        suggestion.GetPattern.return_value.Invoke.assert_not_called()

    def test_password_focus_replaces_popup_for_another_field_before_accepting(self):
        api, window, address_bar, webpage, previous = self.chrome_form()
        field = webpage.GetChildren.return_value[-1]
        current = node("MenuItemControl", "Use strong password replacement-secret")
        field.SetFocus.side_effect = lambda: setattr(window.GetChildren, "return_value", [address_bar, webpage, current]) or True
        current.GetPattern.return_value.Invoke.side_effect = lambda: setattr(
            window.GetChildren, "return_value", [address_bar, webpage])
        with patch.object(ui, "automation", return_value=api), patch.object(ui.time, "sleep"), \
             patch.object(ui, "prepare_chrome_site"):
            selected = ui.open_chrome_password_suggestion("https://jobs.example.com/register")
            ui.accept_chrome_password("https://jobs.example.com/register", selected)
        field.SetFocus.assert_called_once()
        previous.GetPattern.return_value.Invoke.assert_not_called()
        current.GetPattern.return_value.Invoke.assert_called_once()

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
