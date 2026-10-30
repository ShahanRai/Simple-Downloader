"""
IDM Modern Native Messaging Host.
Enables direct browser-to-desktop native communication for Chrome, Edge, and Firefox.
Reads 32-bit length-prefixed JSON messages from standard input,
dispatches to IDM engine, and sends JSON back to stdout.
"""

import sys
import struct
import json
import urllib.request


LOCAL_API_URL = "http://127.0.0.1:9653/download"


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length or len(raw_length) < 4:
        return None
    message_length = struct.unpack("@I", raw_length)[0]
    message_bytes = sys.stdin.buffer.read(message_length)
    return json.loads(message_bytes.decode("utf-8"))


def send_message(message_dict):
    encoded = json.dumps(message_dict).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("@I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main():
    while True:
        try:
            msg = read_message()
            if msg is None:
                break

            action = msg.get("action")
            if action == "download":
                url = msg.get("url")
                filename = msg.get("filename")
                payload = json.dumps({"url": url, "filename": filename}).encode("utf-8")
                req = urllib.request.Request(
                    LOCAL_API_URL,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        send_message({"status": "success", "result": res})
                except Exception as e:
                    send_message({"status": "error", "message": str(e)})

            elif action == "ping":
                send_message({"status": "pong", "app": "IDM Modern Native Host"})
            else:
                send_message({"status": "unknown_action"})

        except Exception as e:
            send_message({"status": "error", "message": str(e)})
            break


if __name__ == "__main__":
    main()

