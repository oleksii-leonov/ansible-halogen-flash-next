"""Small synthetic API checks; returns failure on a bad or missing response."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import struct
import sys
import urllib.request
import zlib


def request(base, body):
    payload = {
        "model": "halogen-qwen3.8-flash-next",
        "temperature": 0,
        "enable_thinking": False,
        "max_tokens": 64,
        "prompt_cache_policy": "no_store",
        **body,
    }
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=90)


def chat_check(base):
    text, done = "", False
    with request(base, {"messages": [{"role": "user", "content": "Reply with exactly READY."}], "stream": True}) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            if line[6:] == "[DONE]":
                done = True
                break
            data = json.loads(line[6:])
            assert "error" not in data, data
            for choice in data.get("choices", []):
                text += choice.get("delta", {}).get("content") or ""
    assert done and text.strip().strip(".!") == "READY", repr(text)
    return "PASS: streaming chat"


def tool_check(base):
    tool = {"type": "function", "function": {
        "name": "add_numbers", "description": "Add two integers.", "strict": True,
        "parameters": {"type": "object", "properties": {
            "a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"], "additionalProperties": False},
    }}
    with request(base, {
        "messages": [{"role": "user", "content": "Call add_numbers with a=2 and b=3."}],
        "tools": [tool],
        "tool_choice": {"type": "function", "function": {"name": "add_numbers"}},
    }) as response:
        data = json.load(response)
    calls = data["choices"][0]["message"].get("tool_calls", [])
    assert len(calls) == 1 and calls[0]["function"]["name"] == "add_numbers", data
    assert json.loads(calls[0]["function"]["arguments"]) == {"a": 2, "b": 3}, data
    return "PASS: strict tool arguments (no tool executed)"


def vision_check(base):
    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack("!2I5B", 64, 64, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress((b"\0" + b"\0\0\xff" * 64) * 64))
           + chunk(b"IEND", b""))
    image = "data:image/png;base64," + base64.b64encode(png).decode()
    with request(base, {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "What basic colour fills this image? Answer with one colour word."},
        {"type": "image_url", "image_url": {"url": image}},
    ]}]}) as response:
        data = json.load(response)
    assert "blue" in data["choices"][0]["message"].get("content", "").lower(), data
    return "PASS: vision"


if __name__ == "__main__":
    base = sys.argv[1].rstrip("/")
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(chat_check, base), pool.submit(tool_check, base)]
        for job in jobs:
            print(job.result(), flush=True)
    print("PASS: concurrent requests", flush=True)
    print(vision_check(base), flush=True)
