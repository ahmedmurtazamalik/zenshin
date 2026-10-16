"""Two local MCP tools that delegate individual Chrome actions to running Zenshin."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


INSTRUCTIONS = """Use normal browser tools for navigation and other work. Delegate
authorized Chrome password generation/selection and terms checkbox actions to
Zenshin. Zenshin performs the entire native interaction, including opening the
password suggestion; do not use Computer Use to prepare or perform these actions.
Keep the normal permission flow. Never delegate a safety refusal, URL-policy stop, CAPTCHA,
account submission, or marketing consent. Do not read or return passwords.
Use a unique request_id for each intended action and reuse it for any transport
retry; never retry an unconfirmed action with a new ID. After confirmed success,
continue in this turn with your normal tools. Do not ask for a continuation reply.
The Zenshin app must be running, the action enabled, and Preview mode off.
Chrome must already show the requested page. These Chrome tools require Windows;
Zenshin's existing Codex approvals and question forms also support Linux."""

COMMON = {
    "site": {"type": "string", "description": "The intended current Chrome page's full HTTP(S) URL."},
    "request_id": {"type": "string", "description": "Unique ID for this one action; reuse on transport retries."},
}
TOOLS = [
    {"name": "select_chrome_password",
     "description": "Let Zenshin focus the new-password field, open Chrome's native password suggestion, and select it once. "
                    "Chrome generates and fills the password; no Computer Use preparation is needed. "
                    "Requires user authorization; never bypass a safety refusal or URL stop. "
                    "Does not return passwords, navigate, or submit an account. Returns a confirmed receipt or error.",
     "inputSchema": {"type": "object", "properties": COMMON,
                     "required": ["site", "request_id"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}},
    {"name": "check_chrome_terms",
     "description": "Check one exactly named, unchecked terms agreement box on the current Chrome page. "
                    "Requires user authorization to agree; never bypass a safety refusal or URL stop. "
                    "Excludes marketing opt-ins and account submission. Returns a confirmed receipt or error.",
     "inputSchema": {"type": "object", "properties": {**COMMON,
         "label": {"type": "string", "description": "Exact visible accessible label of the authorized terms checkbox."}},
                     "required": ["site", "request_id", "label"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}},
]


def call_tool(port, name, arguments):
    tool = next((tool for tool in TOOLS if tool["name"] == name), None)
    if tool is None:
        raise ValueError("Unknown Zenshin tool")
    schema = tool["inputSchema"]
    if (not isinstance(arguments, dict) or set(arguments) - schema["properties"].keys()
            or any(not isinstance(arguments.get(key), str) or not arguments[key].strip()
                   for key in schema["required"])):
        raise ValueError("Supply the tool's required text arguments only")
    action = "password" if name == "select_chrome_password" else "terms"
    request = Request(f"http://127.0.0.1:{port}/api/browser-action",
                      data=json.dumps({**arguments, "action": action}).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=55) as response:
            return json.load(response)
    except HTTPError as error:
        with error:
            raise RuntimeError(json.load(error)["error"]) from None
    except (URLError, TimeoutError) as error:
        raise RuntimeError("Zenshin is unavailable or its result is unknown. Keep the same request_id; "
                           "check the running app and its action journal before continuing.") from error


def serve(port):
    for line in sys.stdin.buffer:
        request_id = None
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            request_id = message["id"]
            method, params = message["method"], message.get("params", {})
            if method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "zenshin", "version": "0.2.0"}, "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    receipt = call_tool(port, params["name"], params.get("arguments", {}))
                    result = {"content": [{"type": "text", "text": json.dumps(receipt)}],
                              "structuredContent": receipt, "isError": False}
                except (ValueError, RuntimeError) as error:
                    result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": request_id,
                                  "error": {"code": -32601, "message": "Method not found"}}), flush=True)
                continue
            reply = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (ValueError, KeyError, TypeError) as error:
            reply = {"jsonrpc": "2.0", "id": request_id,
                     "error": {"code": -32600, "message": "Invalid MCP request: " + str(error)}}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Running Zenshin app's local port")
    serve(parser.parse_args().port)
