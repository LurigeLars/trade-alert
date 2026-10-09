"""Offline Chrome pairing credentials and expiry tests."""
import json
import pathlib
import tempfile
import unittest

from trade_alert.chrome_pairing import PairingStore

ORIGIN_A = "chrome-extension://" + "a"*32
ORIGIN_B = "chrome-extension://" + "b"*32


class ChromePairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.pairing = PairingStore(self.root)

    def test_pair_once_pin_exact_extension_and_persist_only_hash(self):
        code = self.pairing.issue_code(now=100)
        self.assertEqual(len(code), 20)
        self.assertNotIn(code, self.pairing.pending_path.read_text())
        self.assertIsNone(self.pairing.pair(ORIGIN_B, "X"*20, now=101))
        token = self.pairing.pair(ORIGIN_A, code, now=101)
        self.assertIsNotNone(token)
        self.assertEqual(len(token), 64)
        self.assertTrue(self.pairing.authenticated(ORIGIN_A, token))
        self.assertFalse(self.pairing.authenticated(ORIGIN_B, token))
        self.assertFalse(self.pairing.authenticated(ORIGIN_A, "0"*64))
        self.assertIsNone(self.pairing.pair(ORIGIN_A, code, now=102))
        self.assertNotIn(token, self.pairing.auth_path.read_text())
        self.assertEqual(self.pairing.paired_origin(), ORIGIN_A)
        fresh_process = PairingStore(self.root)
        self.assertTrue(fresh_process.authenticated(ORIGIN_A, token))

    def test_code_expires_in_ten_minutes(self):
        code = self.pairing.issue_code(now=100)
        self.assertIsNone(self.pairing.pair(ORIGIN_A, code, now=701))
        self.assertFalse(self.pairing.auth_path.exists())

    def test_new_pair_rotates_bearer_credential_and_pins_new_extension(self):
        token1 = self.pairing.pair(ORIGIN_A,self.pairing.issue_code(now=100),now=101)
        token2 = self.pairing.pair(ORIGIN_B,self.pairing.issue_code(now=102),now=103)
        self.assertNotEqual(token1,token2)
        self.assertFalse(self.pairing.authenticated(ORIGIN_A,token1))
        self.assertTrue(self.pairing.authenticated(ORIGIN_B,token2))

    def test_bad_origin_and_malformed_code_are_denied(self):
        code = self.pairing.issue_code(now=100)
        self.assertIsNone(self.pairing.pair("https://truthsocial.com",code,now=101))
        self.assertIsNone(self.pairing.pair("chrome-extension://bad",code,now=101))
        self.assertIsNone(self.pairing.pair(ORIGIN_A,code.lower(),now=101))
        self.assertFalse(self.pairing.authenticated(ORIGIN_A,None))
        self.assertFalse(self.pairing.authenticated(ORIGIN_A,"Bearer "+"a"*64))
        self.assertIsNone(self.pairing.paired_origin())


if __name__ == "__main__":
    unittest.main()
