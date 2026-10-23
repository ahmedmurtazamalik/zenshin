import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import linux_ui
import windows_ui


def control(kind, name="", children=()):
    roles = {"document": ("DocumentControl", "document web"),
             "group": ("GroupControl", "section"), "text": ("TextControl", "static"),
             "entry": ("EditControl", "entry"), "button": ("ButtonControl", "push button")}
    node = Mock()
    node.ControlTypeName, role = roles[kind]
    node.Name, node.IsEnabled, node.IsOffscreen = name, True, False
    node.children = list(children)
    node.GetChildren.side_effect = lambda: node.children
    node.get_role_name.return_value, node.get_name.return_value = role, name
    node.get_child_count.side_effect = lambda: len(node.children)
    node.get_child_at_index.side_effect = lambda index: node.children[index]
    node.get_state_set().contains.return_value = True
    for child in children:
        child.GetParentControl.return_value = node
        child.get_parent.return_value = node
    return node


def chat(latest="", draft="", echo=True):
    api, value, invoke = Mock(), Mock(Value=draft, IsReadOnly=False), Mock()
    api.comtypes.COMError = OSError
    entry, send = control("entry", "Work with Codex"), control("button", "Send")
    doc = control("document", "Selected chat", [control("group", children=[entry, send])])
    if latest:
        doc.children.insert(0, control("text", latest))
    entry.GetPattern.return_value = value
    send.GetPattern.return_value = invoke
    send.get_n_actions.return_value = 1
    send.get_action_name.return_value = "click"
    state = {"writes": [], "sends": 0, "after_write": None}

    def write(text):
        value.Value = text
        state["writes"].append(text)
        if state["after_write"]:
            state["after_write"]()
        return True

    def deliver(*_args):
        state["sends"] += 1
        if echo:
            doc.children.append(control("text", value.Value))
            value.Value = ""
        return True

    value.SetValue.side_effect = write
    invoke.Invoke.side_effect = deliver
    send.do_action.side_effect = deliver
    api.Text.get_text.side_effect = lambda *_args: value.Value
    api.EditableText.set_text_contents.side_effect = lambda _entry, text: write(text)
    return api, value, doc, state


class ChatSetupNativeTests(unittest.TestCase):
    def native(self, ui, api, doc):
        stack = ExitStack()
        stack.enter_context(patch.object(ui, "document", return_value=doc))
        stack.enter_context(patch.object(ui, "automation" if ui is windows_ui else "atspi", return_value=api))
        return stack

    def test_setup_sends_once_in_empty_chat_or_after_user_message(self):
        for ui in (windows_ui, linux_ui):
            for latest in ("", "Please implement this"):
                with self.subTest(platform=ui.__name__, latest=latest):
                    api, value, doc, state = chat(latest)
                    progress = Mock()
                    with self.native(ui, api, doc):
                        self.assertTrue(ui.chat_setup_ready("Selected chat", latest))
                        ui.send_chat_setup("Selected chat", latest, "Use Zenshin for enabled Chrome actions.", progress)
                    self.assertEqual(state["writes"], ["Use Zenshin for enabled Chrome actions."])
                    self.assertEqual(state["sends"], 1)
                    self.assertEqual(value.Value, "")
                    progress.assert_called_once_with("confirming")

    def test_setup_leaves_running_chats_pending_forms_and_drafts_untouched(self):
        for ui in (windows_ui, linux_ui):
            for blocked in ("Stop", "Allow once", "Reply…", "draft", "missing latest"):
                with self.subTest(platform=ui.__name__, blocked=blocked):
                    draft = "My unfinished message" if blocked == "draft" else ""
                    api, value, doc, state = chat("Latest user message", draft)
                    if blocked in {"Stop", "Allow once", "Reply…"}:
                        doc.children.append(control("entry" if blocked == "Reply…" else "button", blocked))
                    latest = "Different message" if blocked == "missing latest" else "Latest user message"
                    with self.native(ui, api, doc):
                        self.assertFalse(ui.chat_setup_ready("Selected chat", latest))
                        with self.assertRaises(RuntimeError):
                            ui.send_chat_setup("Selected chat", latest, "Setup prompt")
                    self.assertEqual(state["writes"], [])
                    self.assertEqual(state["sends"], 0)
                    self.assertEqual(value.Value, draft)

    def test_setup_rechecks_idle_state_before_send(self):
        for ui in (windows_ui, linux_ui):
            with self.subTest(platform=ui.__name__):
                api, value, doc, state = chat()
                state["after_write"] = lambda: doc.children.append(control("button", "Stop"))
                with self.native(ui, api, doc):
                    with self.assertRaisesRegex(RuntimeError, "Composer changed"):
                        ui.send_chat_setup("Selected chat", "", "Setup prompt")
                self.assertEqual(state["sends"], 0)
                self.assertEqual(value.Value, "Setup prompt")

    def test_setup_requires_new_echo_without_retrying_send(self):
        for ui in (windows_ui, linux_ui):
            with self.subTest(platform=ui.__name__):
                api, _value, doc, state = chat("Setup prompt", echo=False)
                with self.native(ui, api, doc), patch.object(ui.time, "monotonic", side_effect=[0, 6]):
                    with self.assertRaisesRegex(RuntimeError, "delivery was not confirmed"):
                        ui.send_chat_setup("Selected chat", "Setup prompt", "Setup prompt")
                self.assertEqual(state["sends"], 1)


if __name__ == "__main__":
    unittest.main()
