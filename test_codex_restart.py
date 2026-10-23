from contextlib import ExitStack
from itertools import chain, count, repeat
import unittest
from unittest.mock import Mock, call, patch

import windows_ui as ui


def window(identity=21, children=(), class_name="Chrome_WidgetWin_1"):
    node = Mock(ProcessId=identity, ClassName=class_name, ControlTypeName="WindowControl", Name="Codex")
    node.GetChildren.return_value = list(children)
    return node


class CodexRestartTests(unittest.TestCase):
    def setUp(self):
        self.path = r"C:\Program Files\WindowsApps\OpenAI.Codex_1\app\ChatGPT.exe"
        self.old, self.new = window(), window(22)
        self.api, self.kernel = Mock(), Mock()
        self.api.ControlsAreSame.side_effect = lambda first, second: first is second
        self.api.GetForegroundControl.return_value = self.old
        self.kernel.OpenProcess.return_value = 1234
        self.kernel.WaitForSingleObject.return_value = 0

    def native(self, snapshots):
        stack = ExitStack()
        stack.enter_context(patch.object(ui, "automation", return_value=self.api))
        stack.enter_context(patch.object(ui.ctypes, "WinDLL", return_value=self.kernel, create=True))
        stack.enter_context(patch.object(ui, "codex_windows", side_effect=snapshots))
        stack.enter_context(patch.object(ui.time, "monotonic", side_effect=count()))
        stack.enter_context(patch.object(ui.time, "sleep"))
        self.open_app = stack.enter_context(patch.object(ui.os, "startfile", create=True))
        self.launch = stack.enter_context(patch.object(ui.subprocess, "Popen"))
        return stack

    def test_quit_waits_for_original_process_before_relaunch_and_accepts_new_window(self):
        second_window = window()
        snapshots = [[(self.old, self.path, 21), (second_window, self.path, 21)],
                     [(self.new, self.path, 22)]]
        events = []
        self.kernel.WaitForSingleObject.side_effect = lambda *_args: events.append("old exited") or 0
        with self.native(snapshots):
            self.open_app.side_effect = lambda *_args: events.append("launch")
            self.assertTrue(ui.restart_codex())
        self.assertEqual(events, ["old exited", "launch"])
        self.api.SendKeys.assert_called_once_with("{Ctrl}q", waitTime=.1)
        self.open_app.assert_called_once_with("codex://")
        self.launch.assert_not_called()
        self.kernel.CloseHandle.assert_called_once()

    def test_only_owned_native_quit_confirmation_is_accepted_once(self):
        for owned in (True, False):
            with self.subTest(owned=owned):
                quit_button = Mock(ControlTypeName="ButtonControl", Name="Quit", IsEnabled=True, IsOffscreen=False)
                cancel = Mock(ControlTypeName="ButtonControl", Name="Cancel", IsEnabled=True, IsOffscreen=False)
                quit_button.GetChildren.return_value = cancel.GetChildren.return_value = []
                dialog = window(children=[quit_button, cancel], class_name="#32770")
                self.api.GetForegroundControl.side_effect = [self.old, dialog]
                self.kernel.WaitForSingleObject.side_effect = [258, 0]
                snapshots = [[(self.old, self.path, 21)],
                             [(dialog, self.path, 21 if owned else 99)],
                             [(self.new, self.path, 22)]]
                with self.native(snapshots), patch.object(ui, "press") as press:
                    self.assertTrue(ui.restart_codex())
                if owned:
                    press.assert_called_once_with(quit_button)
                else:
                    press.assert_not_called()

    def test_foreground_failure_sends_no_shortcut_and_does_not_relaunch(self):
        self.api.GetForegroundControl.return_value = window(99)
        with self.native([[(self.old, self.path, 21)]]):
            with self.assertRaisesRegex(RuntimeError, "no quit shortcut"):
                ui.restart_codex()
        self.api.SendKeys.assert_not_called()
        self.open_app.assert_not_called()
        self.launch.assert_not_called()
        self.kernel.CloseHandle.assert_called_once()

    def test_quit_timeout_does_not_force_close_or_relaunch(self):
        self.kernel.WaitForSingleObject.return_value = 258
        with self.native([[(self.old, self.path, 21)]]):
            with self.assertRaisesRegex(RuntimeError, "not forced closed or relaunched"):
                ui.restart_codex()
        self.api.SendKeys.assert_called_once()
        self.open_app.assert_not_called()
        self.launch.assert_not_called()
        self.kernel.TerminateProcess.assert_not_called()
        self.kernel.CloseHandle.assert_called_once()

    def test_app_reopens_when_foreground_disappears_during_quit(self):
        self.kernel.WaitForSingleObject.side_effect = [258, 0]
        self.api.GetForegroundControl.side_effect = [self.old, None]
        with self.native([[(self.old, self.path, 21)], [(self.new, self.path, 22)]]):
            self.assertTrue(ui.restart_codex())
        self.open_app.assert_called_once_with("codex://")
        self.launch.assert_not_called()

    def test_background_app_is_restored_before_native_restart(self):
        with self.native([[], [(self.old, self.path, 21)], [(self.new, self.path, 22)]]):
            self.assertTrue(ui.restart_codex())
        self.assertEqual(self.open_app.call_args_list, [call("codex://"), call("codex://")])
        self.api.SendKeys.assert_called_once_with("{Ctrl}q", waitTime=.1)
        self.launch.assert_not_called()

    def test_missing_protocol_handler_or_window_stops_without_quitting(self):
        for error in (OSError("No protocol handler"), None):
            with self.subTest(error=error), self.native(repeat([])):
                self.open_app.side_effect = error
                with self.assertRaisesRegex(RuntimeError, "Could not open Codex|did not expose a window"):
                    ui.restart_codex()
                self.api.SendKeys.assert_not_called()
                self.launch.assert_not_called()

    def test_distinct_instances_are_ambiguous(self):
        with self.native([[(self.old, self.path, 21), (self.new, r"C:\Other\Codex.exe", 22)]]):
            with self.assertRaisesRegex(RuntimeError, "Several Codex instances"):
                ui.restart_codex()
        self.api.SendKeys.assert_not_called()
        self.launch.assert_not_called()

    def test_relaunch_requires_a_new_process_window_before_reporting_success(self):
        old_window = [(self.old, self.path, 21)]
        with self.native(chain([old_window], repeat(old_window))):
            with self.assertRaisesRegex(RuntimeError, "new window was not confirmed"):
                ui.restart_codex()
        self.open_app.assert_called_once_with("codex://")
        self.launch.assert_not_called()

    def test_failed_windows_activation_reports_that_codex_was_not_reopened(self):
        with self.native([[(self.old, self.path, 21)]]):
            self.open_app.side_effect = OSError("Activation failed")
            with self.assertRaisesRegex(RuntimeError, "closed but Windows could not reopen"):
                ui.restart_codex()
        self.open_app.assert_called_once_with("codex://")
        self.launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
