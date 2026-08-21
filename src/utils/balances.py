from src.database.connection import execute_query

WELFARE_RESERVE_LIMIT = 100000.0


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


def _get_member_subscription_net_balance(member_id: str) -> float:
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


def get_member_welfare_reserve_balance(member_id: str) -> float:
    net_balance = _get_member_subscription_net_balance(member_id)
    return min(net_balance, WELFARE_RESERVE_LIMIT)


def get_member_savings_balance(member_id: str) -> float:
    net_balance = _get_member_subscription_net_balance(member_id)
    welfare_balance = get_member_welfare_reserve_balance(member_id)
    return max(net_balance - welfare_balance, 0.0)


def get_member_balance_breakdown(member_id: str) -> dict[str, float]:
    net_balance = _get_member_subscription_net_balance(member_id)
    welfare_balance = get_member_welfare_reserve_balance(member_id)
    savings_balance = max(net_balance - welfare_balance, 0.0)
    return {
        "total_balance": net_balance,
        "welfare_balance": welfare_balance,
        "savings_balance": savings_balance,
    }


def get_effective_member_balance(member_id: str) -> float:
    return _get_member_subscription_net_balance(member_id)


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


def get_effective_pool_welfare_balance() -> float:
    """Return the sum of each member's capped welfare reserve balance."""
    ensure_member_balance_adjustments_table()
    rows = execute_query(
        """
        WITH member_contributions AS (
            SELECT member_id, COALESCE(SUM(amount_paid), 0) AS contributions
            FROM subscriptions
            GROUP BY member_id
        ), member_withdrawals AS (
            SELECT member_id, COALESCE(SUM(amount), 0) AS withdrawals
            FROM member_balance_adjustments
            WHERE adjustment_type = 'withdrawal'
            GROUP BY member_id
        )
        SELECT COALESCE(
            SUM(LEAST(GREATEST(contributions - COALESCE(withdrawals, 0), 0), %s)),
            0
        ) AS total_welfare
        FROM member_contributions
        LEFT JOIN member_withdrawals USING (member_id);
        """,
        params=(WELFARE_RESERVE_LIMIT,),
        fetch=True,
    )
    return float(rows[0]["total_welfare"] or 0) if rows else 0.0
