from __future__ import annotations

import base64
import io
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from helpers import scratch_tempdir

import gridcrop_core as core
from PIL import Image


class FakeOllama:
    """/api/tags, /api/show, /api/chat 만 흉내 내는 내 PC 시험 서버."""

    def __init__(self, models: dict[str, list[str] | None], chat_reply: str = "안녕하세요\nHello 123", chat_status: int = 200, chat_error: str = "") -> None:
        self.models = models
        self.chat_reply = chat_reply
        self.chat_status = chat_status
        self.chat_error = chat_error
        self.requests: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # 시험 출력 조용히
                pass

            def _send(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": n} for n in outer.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append((self.path, data))
                if self.path == "/api/show":
                    name = data.get("model")
                    if name not in outer.models:
                        self._send(404, {"error": f"model '{name}' not found"})
                    elif outer.models[name] is None:
                        self._send(200, {"details": {}})
                    else:
                        self._send(200, {"capabilities": outer.models[name]})
                elif self.path == "/api/chat":
                    if outer.chat_status != 200:
                        self._send(outer.chat_status, {"error": outer.chat_error})
                    else:
                        self._send(200, {"message": {"role": "assistant", "content": outer.chat_reply}, "done": True})
                else:
                    self._send(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "FakeOllama":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HostTest(unittest.TestCase):
    def test_allowed(self) -> None:
        self.assertEqual(core.normalize_local_host(""), core.DEFAULT_OLLAMA_HOST)
        self.assertEqual(core.normalize_local_host("localhost:11434/"), "http://localhost:11434")
        self.assertEqual(core.normalize_local_host("http://127.0.0.1:11434/api"), "http://127.0.0.1:11434")
        self.assertEqual(core.normalize_local_host("192.168.0.10:11434"), "http://192.168.0.10:11434")
        self.assertEqual(core.normalize_local_host("http://[::1]:11434"), "http://[::1]:11434")

    def test_rejected(self) -> None:
        for host in ["8.8.8.8:11434", "https://api.example.com", "ftp://127.0.0.1", "http://127.0.0.1:99999"]:
            with self.subTest(host=host):
                with self.assertRaises(core.OcrError):
                    core.normalize_local_host(host)


class PayloadTest(unittest.TestCase):
    def test_payload_shape_and_png(self) -> None:
        image = Image.new("RGBA", (200, 50), (0, 0, 0, 0))
        b64 = core.image_to_png_base64(image)
        payload = core.build_ollama_chat_payload("m:1", b64)
        self.assertEqual(payload["model"], "m:1")
        self.assertFalse(payload["stream"])
        message = payload["messages"][0]
        self.assertEqual(message["role"], "user")
        self.assertIn("글자", message["content"])
        decoded = Image.open(io.BytesIO(base64.b64decode(message["images"][0])))
        self.assertEqual(decoded.format, "PNG")
        self.assertEqual(decoded.mode, "RGB")
        self.assertEqual(max(decoded.size), core.OCR_IMAGE_MIN_SIDE)  # 작은 조각은 키운다

    def test_prepare_shrinks_large(self) -> None:
        big = core.prepare_ocr_image(Image.new("RGB", (5000, 1000)))
        self.assertEqual(big.size, (2048, 410))
        same = Image.new("L", (800, 600))
        self.assertIs(core.prepare_ocr_image(same), same)

    def test_parse_response(self) -> None:
        self.assertEqual(core.parse_ollama_chat_response({"message": {"content": "  가나다 \n"}}), "가나다")
        with self.assertRaises(core.OcrError):
            core.parse_ollama_chat_response({"error": "boom"})
        with self.assertRaises(core.OcrError):
            core.parse_ollama_chat_response({"message": {}})
        with self.assertRaises(core.OcrError):
            core.parse_ollama_chat_response([])

    def test_error_translation(self) -> None:
        self.assertIn("ollama pull x", core.translate_ollama_error(404, "model 'x' not found", "x"))
        self.assertIn("불러오지 못했", core.translate_ollama_error(500, "unable to load model: E:\\blob"))
        self.assertIn("그림을 읽지 못", core.translate_ollama_error(400, "model does not support image input"))
        self.assertIn("상태 418", core.translate_ollama_error(418, "teapot"))


class ClientTest(unittest.TestCase):
    def test_reads_text_with_auto_picked_vision_model(self) -> None:
        with FakeOllama({"llama3.1:latest": ["completion"], "qwen2.5vl:7b": ["completion", "vision"]}) as fake:
            client = core.OllamaClient(fake.url, timeout=5)
            model = client.pick_vision_model("")
            self.assertEqual(model, "qwen2.5vl:7b")
            text = client.read_text(model, Image.new("RGB", (64, 64), "white"))
            self.assertEqual(text, "안녕하세요\nHello 123")
            chat = [data for path, data in fake.requests if path == "/api/chat"][0]
            self.assertEqual(chat["model"], "qwen2.5vl:7b")
            self.assertEqual(len(chat["messages"][0]["images"]), 1)

    def test_preferred_model_checks(self) -> None:
        with FakeOllama({"exaone3.5:7.8b": ["completion"], "llava:latest": ["vision"], "old:1": None}) as fake:
            client = core.OllamaClient(fake.url, timeout=5)
            self.assertEqual(client.pick_vision_model("llava"), "llava:latest")
            self.assertEqual(client.pick_vision_model("old:1"), "old:1")  # 능력을 알려 주지 않는 옛 판은 믿고 쓴다
            with self.assertRaisesRegex(core.OcrError, "그림을 읽지 못하는"):
                client.pick_vision_model("exaone3.5:7.8b")
            with self.assertRaisesRegex(core.OcrError, "없습니다"):
                client.pick_vision_model("nothing:1")
            self.assertEqual(client.vision_models(), ["llava:latest"])

    def test_no_vision_model_guidance(self) -> None:
        with FakeOllama({"exaone3.5:7.8b": ["completion"]}) as fake:
            client = core.OllamaClient(fake.url, timeout=5)
            with self.assertRaises(core.OcrError) as ctx:
                client.pick_vision_model("")
            self.assertIn(f"ollama pull {core.SUGGESTED_VISION_MODEL}", str(ctx.exception))
            self.assertIn("exaone3.5:7.8b", str(ctx.exception))

    def test_chat_error_is_translated(self) -> None:
        with FakeOllama({"v:1": ["vision"]}, chat_status=500, chat_error="unable to load model: X") as fake:
            client = core.OllamaClient(fake.url, timeout=5)
            with self.assertRaisesRegex(core.OcrError, "불러오지 못했"):
                client.read_text("v:1", Image.new("RGB", (10, 10)))

    def test_ollama_off(self) -> None:
        client = core.OllamaClient(f"http://127.0.0.1:{free_port()}", timeout=3)
        with self.assertRaisesRegex(core.OcrError, "연결하지 못했습니다"):
            client.list_models()


class SettingsTest(unittest.TestCase):
    def test_roundtrip_and_corrupt(self) -> None:
        with scratch_tempdir() as tmp:
            path = Path(tmp) / core.OCR_SETTINGS_FILENAME
            self.assertEqual(core.load_ocr_settings(path), core.OcrSettings())
            core.save_ocr_settings(path, core.OcrSettings(engine="cpp", ollama_host="http://127.0.0.1:1", ollama_model="m", timeout_sec=60))
            loaded = core.load_ocr_settings(path)
            self.assertEqual((loaded.engine, loaded.ollama_model, loaded.timeout_sec), ("cpp", "m", 60))
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(core.load_ocr_settings(path).engine, "ollama")
            path.write_text(json.dumps({"engine": "evil", "timeout_sec": 1}), encoding="utf-8")
            loaded = core.load_ocr_settings(path)
            self.assertEqual((loaded.engine, loaded.timeout_sec), ("ollama", 10))

    def test_format_results(self) -> None:
        text = core.format_ocr_results([("영역 1", "가\n나"), ("영역 2", "  ")])
        self.assertEqual(text, "[영역 1]\n가\n나\n\n[영역 2]\n(글자 없음)\n")
        self.assertEqual(core.format_ocr_results([]), "")


if __name__ == "__main__":
    unittest.main()
