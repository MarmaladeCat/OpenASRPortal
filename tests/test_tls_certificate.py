"""Native certificate generation and real verified HTTPS/WSS, without OpenSSL CLI."""

import ipaddress
import os
import ssl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from cryptography import x509

ROOT = Path(__file__).resolve().parents[1]


class CertificateTests(unittest.IsolatedAsyncioTestCase):
    def generate(self, *arguments):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/create_tls_certificate.py"), *arguments],
            env={**os.environ, "PATH": ""},
            capture_output=True,
        )

    async def test_native_certificate_verified_https_and_wss(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as temporary:
            output = Path(temporary) / "中文 TLS"
            args = [
                "--host",
                "localhost",
                "--host",
                "127.0.0.1",
                "--host",
                "::1",
                "--output",
                str(output),
            ]
            result = self.generate(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            cert, key = output / "server.crt", output / "server.key"
            original = cert.read_bytes(), key.read_bytes()
            certificate = x509.load_pem_x509_certificate(original[0])
            san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            self.assertEqual(san.get_values_for_type(x509.DNSName), ["localhost"])
            self.assertEqual(
                san.get_values_for_type(x509.IPAddress),
                [ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")],
            )
            self.assertNotEqual(self.generate(*args).returncode, 0)
            self.assertEqual((cert.read_bytes(), key.read_bytes()), original)
            if os.name != "nt":
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_tls.load_cert_chain(cert, key)
            client_tls = ssl.create_default_context(cafile=str(cert))

            async def health(request):
                return web.json_response({"status": "ok"})

            async def websocket(request):
                socket = web.WebSocketResponse()
                await socket.prepare(request)
                await socket.send_json({"type": "final", "text": "中文🙂"})
                await socket.close()
                return socket

            app = web.Application()
            app.router.add_get("/health", health)
            app.router.add_get("/ws", websocket)
            server = TestServer(app, scheme="https")
            await server.start_server(ssl=server_tls)
            try:
                async with ClientSession() as client:
                    async with client.get(server.make_url("/health"), ssl=client_tls) as response:
                        self.assertEqual(await response.json(), {"status": "ok"})
                    async with client.ws_connect(server.make_url("/ws"), ssl=client_tls) as socket:
                        self.assertEqual((await socket.receive_json())["text"], "中文🙂")
                    with self.assertRaises(ssl.SSLError):
                        async with client.get(server.make_url("/health")):
                            pass
            finally:
                await server.close()

    def test_invalid_host_and_validity_do_not_create_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as temporary:
            output = Path(temporary) / "invalid"
            for arguments in (
                ["--host", "https://localhost"],
                ["--host", "localhost", "--days", "0"],
            ):
                result = self.generate(*arguments, "--output", str(output))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())
