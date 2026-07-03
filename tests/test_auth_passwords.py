import unittest

import bcrypt

from src.components.auth import check_password


class CheckPasswordTests(unittest.TestCase):
    def test_accepts_plaintext_legacy_passwords(self):
        self.assertTrue(check_password("secret123", "secret123"))

    def test_rejects_wrong_plaintext_passwords(self):
        self.assertFalse(check_password("wrong", "secret123"))

    def test_accepts_bcrypt_hashes_stored_as_bytes_literal_strings(self):
        hashed = bcrypt.hashpw(b"secret123", bcrypt.gensalt())
        self.assertTrue(check_password("secret123", str(hashed)))

    def test_accepts_hex_encoded_bcrypt_hashes(self):
        hashed = bcrypt.hashpw(b"secret123", bcrypt.gensalt())
        self.assertTrue(check_password("secret123", hashed.hex()))


if __name__ == "__main__":
    unittest.main()
