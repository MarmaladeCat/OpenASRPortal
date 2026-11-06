"""Setup decisions use live public status rather than installation version flags."""

import io
import json
import unittest
from unittest.mock import patch

from openasrportal.entrypoints.onboarding import setup_url


class OnboardingTests(unittest.TestCase):
    def test_first_run_and_unfinished_reinstall_open_setup(self):
        with patch(
            "openasrportal.entrypoints.onboarding.urlopen",
            return_value=io.BytesIO(b'{"initialized":false}'),
        ) as request:
            self.assertEqual(
                setup_url("http://127.0.0.1:12087/admin"), "http://127.0.0.1:12087/admin/setup"
            )
            request.assert_called_once_with(
                "http://127.0.0.1:12087/v1/admin/auth/status", timeout=2
            )

    def test_initialized_upgrade_and_reinstall_do_not_open_setup(self):
        with patch(
            "openasrportal.entrypoints.onboarding.urlopen",
            return_value=io.BytesIO(json.dumps({"initialized": True}).encode()),
        ):
            self.assertIsNone(setup_url("http://127.0.0.1:12087/admin"))

    def test_invalid_address_is_rejected_before_network(self):
        with patch("openasrportal.entrypoints.onboarding.urlopen") as request:
            for address in ("file:///data", "http://user:secret@localhost"):
                with self.assertRaises(ValueError):
                    setup_url(address)
            request.assert_not_called()
