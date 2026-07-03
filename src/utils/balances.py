from src.database.connection import execute_query


def ensure_member_balance_adjustments_table() -> None:
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS member_balance_adjustments (
            id SERIAL PRIMARY KEY,
            member_id TEXT NOT NULL,
            adjustment_type TEXT NOT NULL DEFAULT 'withdrawal',
            amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            reference TEXT,
            reference_id INTEGER,
            created_on DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        params=None,
        fetch=False,
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_member_balance_adjustments_member
        ON member_balance_adjustments (member_id, adjustment_type, created_on);
        """,
        params=None,
        fetch=False,
    )


def get_effective_member_balance(member_id: str) -> float:
    ensure_member_balance_adjustments_table()
    contribution_rows = execute_query(
        "SELECT COALESCE(SUM(amount_paid),0) AS total_contributions FROM subscriptions WHERE member_id = %s;",
        params=(member_id,),
        fetch=True,
    )
    contributions = float(contribution_rows[0]["total_contributions"] or 0) if contribution_rows else 0.0

    withdrawal_rows = execute_query(
        "SELECT COALESCE(SUM(amount),0) AS total_withdrawn FROM member_balance_adjustments WHERE member_id = %s AND adjustment_type = 'withdrawal';",
        params=(member_id,),
        fetch=True,
    )
    withdrawals = float(withdrawal_rows[0]["total_withdrawn"] or 0) if withdrawal_rows else 0.0
    return max(contributions - withdrawals, 0.0)


def get_effective_pool_balance() -> float:
    ensure_member_balance_adjustments_table()
    contribution_rows = execute_query(
        "SELECT COALESCE(SUM(amount_paid),0) AS total_contributions FROM subscriptions;",
        params=None,
        fetch=True,
    )
    contributions = float(contribution_rows[0]["total_contributions"] or 0) if contribution_rows else 0.0

    withdrawal_rows = execute_query(
        "SELECT COALESCE(SUM(amount),0) AS total_withdrawn FROM member_balance_adjustments WHERE adjustment_type = 'withdrawal';",
        params=None,
        fetch=True,
    )
    withdrawals = float(withdrawal_rows[0]["total_withdrawn"] or 0) if withdrawal_rows else 0.0
    return max(contributions - withdrawals, 0.0)
