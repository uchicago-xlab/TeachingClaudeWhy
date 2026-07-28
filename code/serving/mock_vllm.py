"""Minimal fake vLLM OpenAI server for testing check_endpoint.py / Inspect wiring.

MODE env var picks the failure to simulate:
  ok            - healthy: distinct content per model
  identical     - both models return the same text (unapplied LoRA)
  think_leak    - response contains a <think> block
  reasoning     - text lands in reasoning_content, content empty
  no_adapter    - /v1/models lists only the base model
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

MODE = os.environ.get("MODE", "ok")
BASE = "Qwen/Qwen3-14B"
ADAPTER = "qwen3-14b-da-sonnet5-v1"
RECEIVED = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            ids = [BASE] if MODE == "no_adapter" else [BASE, ADAPTER]
            self._send({"object": "list", "data": [{"id": i, "object": "model"} for i in ids]})
        elif self.path.endswith("/_received"):
            self._send(RECEIVED)
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        RECEIVED.append(req)
        model = req.get("model", "?")

        text = f"Answer from {model}."
        if MODE == "identical":
            text = "Identical answer."
        message = {"role": "assistant", "content": text}
        if MODE == "think_leak":
            message["content"] = "<think>\nhmm\n</think>\n\n" + text
        if MODE == "reasoning":
            message["content"] = ""
            message["reasoning_content"] = "internal deliberation"

        self._send({
            "id": "chatcmpl-1", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49},
        })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8111"))
    print(f"mock vllm [{MODE}] on :{port}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
