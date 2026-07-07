import unittest

from src.views.home import calculate_effective_loan_balance


class LoanBalanceTests(unittest.TestCase):
    def test_includes_interest_when_outstanding_balance_is_still_principal_only(self):
        rows = [
            {"outstanding_balance": 1000.0, "interest_accumulated": 100.0, "amount_requested": 1000.0},
        ]
        self.assertEqual(calculate_effective_loan_balance(rows), 1100.0)

    def test_uses_outstanding_balance_when_it_already_includes_interest(self):
        rows = [
            {"outstanding_balance": 1100.0, "interest_accumulated": 100.0, "amount_requested": 1000.0},
        ]
        self.assertEqual(calculate_effective_loan_balance(rows), 1100.0)


if __name__ == "__main__":
    unittest.main()
