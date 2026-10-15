import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from demo.signup_probe import make_server


class SignupProbeTests(unittest.TestCase):
    def test_stale_tab_cannot_overwrite_current_run(self):
        server, page_path, status_path = make_server(port=0)
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"

        def status():
            with urlopen(origin + status_path, timeout=2) as response:
                return json.load(response)

        self.assertFalse(status()["ready"])
        with urlopen(origin + page_path, timeout=2) as response:
            self.assertIn(status_path, response.read().decode())
        filled = dict(passwordFilled=True, confirmationFilled=True, match=True,
                      length=15, terms=True, marketing=False)
        with urlopen(Request(origin + status_path, data=json.dumps(filled).encode(),
                             headers={"Content-Type": "application/json"}), timeout=2):
            pass
        for stale_path in ("/status", "/run/previous/status"):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(origin + stale_path, data=b"{}"), timeout=2)
            self.assertEqual(error.exception.code, 404)
        self.assertEqual(status(), {"runId": page_path.rsplit("/", 1)[1], "ready": True, **filled})


if __name__ == "__main__":
    unittest.main()
