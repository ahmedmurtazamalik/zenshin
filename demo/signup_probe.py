"""Disposable Chrome signup form; reports flags, never password values.

Run: python demo/signup_probe.py
Open the printed page URL and give Codex the printed status URL.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Zenshin real chat signup probe</title>
<style>body{font:18px system-ui;max-width:680px;margin:40px auto}
label{display:block;margin:18px 0}input:not([type=checkbox]){display:block;padding:9px;width:420px}
output{display:block;padding:16px;background:#eef4ee}</style>
<h1>Zenshin real chat signup probe</h1>
<p>Disposable local form. Test checkboxes only. No account is submitted.</p>
<form onsubmit="event.preventDefault()">
<label>Test email<input autocomplete="username" value="zenshin-__RUN_ID__@example.invalid"></label>
<label>New password<input id="password" type="password" autocomplete="new-password" autofocus></label>
<label>Confirm password<input id="confirm" type="password" autocomplete="new-password"></label>
<label><input id="terms" type="checkbox" required>I agree to the Terms and Conditions</label>
<label><input id="marketing" type="checkbox">I agree to the terms and subscribe to marketing updates</label>
<button type="button" onclick="check()">Check filled fields</button></form>
<output id="result"></output>
<script>
let previousFlags='';
function check(){
  const p=document.getElementById('password'),c=document.getElementById('confirm');
  const flags={passwordFilled:!!p.value,confirmationFilled:!!c.value,
    match:!!p.value&&p.value===c.value,length:p.value.length,
    terms:document.getElementById('terms').checked,
    marketing:document.getElementById('marketing').checked};
  const serialized=JSON.stringify(flags);
  if(serialized===previousFlags)return;
  previousFlags=serialized;
  document.getElementById('result').textContent=serialized;
  fetch('__STATUS_PATH__',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(flags)}).catch(()=>{});
}
document.querySelector('form').addEventListener('input',check);
document.querySelector('form').addEventListener('change',check);
setInterval(check,250);
check();
</script></html>"""


def make_server(port=8897):
    run_id = uuid4().hex
    page_path = f"/run/{run_id}"
    status_path = page_path + "/status"
    page = PAGE.replace("__STATUS_PATH__", status_path).replace("__RUN_ID__", run_id).encode()
    observation = dict(passwordFilled=False, confirmationFilled=False, match=False,
                       length=0, terms=False, marketing=False)
    ready = False

    class Handler(BaseHTTPRequestHandler):
        timeout = 2

        def log_message(self, *args):
            pass

        def reply(self, body, content_type="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == page_path:
                self.reply(page, "text/html; charset=utf-8")
            elif self.path == status_path:
                self.reply(json.dumps({"runId": run_id, "ready": ready, **observation}).encode())
            else:
                self.send_error(404)

        def do_POST(self):
            nonlocal ready
            if self.path != status_path:
                self.send_error(404)
                return
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observation.update({key: data[key] for key in observation})
            ready = True
            self.reply(b"{}")

    server = HTTPServer(("127.0.0.1", port), Handler)
    return server, page_path, status_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8897)
    args = parser.parse_args()
    server, page_path, status_path = make_server(args.port)
    origin = f"http://127.0.0.1:{server.server_port}"
    print(f"Page: {origin}{page_path}\nStatus: {origin}{status_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
