import unittest
from unittest.mock import patch

from src.utils import schema_compat


class SchemaCompatTests(unittest.TestCase):
    def test_table_detection_uses_schema_catalog(self):
        with patch("src.utils.schema_compat.execute_query", return_value=[{"table_name": "members", "column_name": "member_id"}]):
            catalog = schema_compat.get_schema_catalog()

        self.assertIn("members", catalog)
        self.assertIn("member_id", catalog["members"])


if __name__ == "__main__":
    unittest.main()
