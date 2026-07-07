import unittest

from src.views.admin_docs import build_member_profile_pdf


class AdminDocsPdfTests(unittest.TestCase):
    def test_build_member_profile_pdf_returns_pdf_bytes(self):
        pdf_bytes = build_member_profile_pdf(
            {
                "member_id": "M-001",
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "0772123456",
                "role": "Member",
                "status": "Active",
            }
        )

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
