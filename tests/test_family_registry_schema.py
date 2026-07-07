import unittest
from unittest.mock import patch

from src.views import family


class FamilyRegistrySchemaTests(unittest.TestCase):
    def test_build_family_records_query_uses_quoted_aliases(self):
        query = family._build_family_records_query()
        self.assertIn('AS "Relationship"', query)
        self.assertIn('AS "Full Name"', query)
        self.assertIn('AS "Contact"', query)
        self.assertIn('AS "Vital Status"', query)

    def test_ensure_family_registry_schema_creates_table_and_columns(self):
        executed_queries = []

        def fake_execute_query(query, params=None, fetch=False):
            executed_queries.append((query, params, fetch))
            return None

        with patch("src.views.family.execute_query", side_effect=fake_execute_query):
            family._ensure_family_registry_schema()

        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS family_registry" in query for query, _, _ in executed_queries)
        )
        self.assertTrue(
            any("ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS full_legal_name TEXT" in query for query, _, _ in executed_queries)
        )
        self.assertTrue(
            any("ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS vital_status TEXT" in query for query, _, _ in executed_queries)
        )


if __name__ == "__main__":
    unittest.main()
