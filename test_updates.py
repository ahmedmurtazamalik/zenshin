import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import updates


def response(body):
    result = io.BytesIO(body)
    result.headers = {"Content-Length": str(len(body))}
    return result


class UpdateTests(unittest.TestCase):
    def test_latest_release_compares_numeric_versions_and_requires_assets(self):
        tag = "v0.2.10"
        name = "Zenshin-Setup-0.2.10-windows-x64.exe"
        release = {"tag_name": tag, "assets": [
            {"name": asset, "browser_download_url": updates.RELEASES + tag + "/" + asset}
            for asset in (name, "SHA256SUMS.txt")]}
        with patch.object(updates, "urlopen", return_value=response(json.dumps(release).encode())):
            self.assertTrue(updates.latest_release()["available"])
        release["assets"] = []
        with patch.object(updates, "urlopen", return_value=response(json.dumps(release).encode())):
            with self.assertRaisesRegex(RuntimeError, "installer and checksums"):
                updates.latest_release()
        release["tag_name"] = "v" + updates.VERSION
        with patch.object(updates, "urlopen", return_value=response(json.dumps(release).encode())):
            self.assertFalse(updates.latest_release()["available"])

    def test_installer_is_downloaded_with_progress_and_verified_before_launch(self):
        body = b"installer content"
        release = {"name": "setup.exe", "url": "installer", "checksums": "checksums"}
        checksum = (hashlib.sha256(body).hexdigest() + "  setup.exe").encode()
        progress = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(updates.tempfile, "mkdtemp", return_value=directory), \
                 patch.object(updates, "urlopen", side_effect=[response(checksum), response(body)]):
                installer = updates.download_installer(release, progress)
            self.assertEqual(installer.read_bytes(), body)
            progress.assert_called_once()
            with patch.object(updates.subprocess, "Popen") as launch:
                updates.launch_installer(installer, Path("C:/App With Spaces"), 8879, Path("C:/saved.json"))
            arguments = launch.call_args.args[0]
            self.assertIn("/DIR=C:/App With Spaces", [arg.replace("\\", "/") for arg in arguments])
            self.assertIn("/PORT=8879", arguments)
            self.assertIn("/UPDATE=1", arguments)

    def test_bad_checksum_removes_download_and_does_not_launch(self):
        release = {"name": "setup.exe", "url": "installer", "checksums": "checksums"}
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "download"
            directory.mkdir()
            with patch.object(updates.tempfile, "mkdtemp", return_value=str(directory)), \
                 patch.object(updates, "urlopen", side_effect=[response(b"0" * 64 + b"  setup.exe"), response(b"bad")]), \
                 patch.object(updates.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(RuntimeError, "checksum did not match"):
                    updates.download_installer(release, Mock())
            self.assertFalse(directory.exists())
            launch.assert_not_called()

    def test_download_failure_removes_partial_installer(self):
        release = {"name": "setup.exe", "url": "installer", "checksums": "checksums"}
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "download"
            directory.mkdir()
            with patch.object(updates.tempfile, "mkdtemp", return_value=str(directory)), \
                 patch.object(updates, "urlopen", side_effect=[response(b"0" * 64 + b"  setup.exe"), OSError("offline")]):
                with self.assertRaisesRegex(OSError, "offline"):
                    updates.download_installer(release, Mock())
            self.assertFalse(directory.exists())
