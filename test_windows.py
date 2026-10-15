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


class WindowsControlsTests(unittest.TestCase):
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
