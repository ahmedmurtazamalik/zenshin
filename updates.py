"""On-demand Windows installer updates from the project's GitHub releases."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import Request, urlopen

VERSION = "0.2.15"
REPOSITORY = "ahmedmurtazamalik/zenshin"
RELEASES = f"https://github.com/{REPOSITORY}/releases/download/"


def latest_release():
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "Zenshin/" + VERSION})
    with urlopen(request, timeout=15) as response:
        release = json.load(response)
    tag = release["tag_name"]
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise RuntimeError("The latest release has an unsupported version number.")
    newer = tuple(map(int, tag[1:].split("."))) > tuple(map(int, VERSION.split(".")))
    name = f"Zenshin-Setup-{tag[1:]}-windows-x64.exe"
    assets = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
    if newer and any(assets.get(asset) != RELEASES + tag + "/" + asset
                     for asset in (name, "SHA256SUMS.txt")):
        raise RuntimeError("The latest release does not have a Windows installer and checksums yet.")
    return {"version": tag[1:], "available": newer, "name": name,
            "url": RELEASES + tag + "/" + name,
            "checksums": RELEASES + tag + "/SHA256SUMS.txt"}


def download_installer(release, on_progress):
    with urlopen(release["checksums"], timeout=15) as response:
        checksums = response.read().decode("ascii")
    expected = next((line.split()[0] for line in checksums.splitlines()
                     if len(line.split()) == 2 and line.split()[1] == release["name"]), "")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
        raise RuntimeError("The release is missing the installer checksum.")
    directory = Path(tempfile.mkdtemp(prefix="zenshin-update-"))
    installer = directory / release["name"]
    try:
        digest, received = hashlib.sha256(), 0
        with urlopen(release["url"], timeout=30) as response, installer.open("wb") as output:
            total = response.headers.get("Content-Length")
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                on_progress(f"Downloading update: {received // 1024:,} KB"
                            + (f" of {int(total) // 1024:,} KB" if total else ""))
        if digest.hexdigest() != expected.lower():
            raise RuntimeError("Installer checksum did not match. Nothing was installed; try again.")
        return installer
    except Exception:
        installer.unlink(missing_ok=True)
        directory.rmdir()
        raise


def launch_installer(installer, install_root, port, state_path):
    # Inno Setup owns replacement and reopening; never uninstall or delete user data.
    subprocess.Popen([str(installer), "/SILENT", "/SP-", "/NORESTART", "/CLOSEAPPLICATIONS",
                      "/FORCECLOSEAPPLICATIONS", "/UPDATE=1", f"/DIR={install_root}",
                      f"/PORT={port}", f"/STATE={state_path}"], close_fds=True,
                     env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
