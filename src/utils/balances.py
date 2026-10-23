from __future__ import annotations

import json
import logging
import uuid
from contextlib import nullcontext
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Iterable

import streamlit as st

from src.database.connection import execute_query, get_conn_from_pool

logger = logging.getLogger(__name__)

WELFARE_RESERVE_LIMIT = 100000.0
MAX_MONTHLY_SUBSCRIPTION = 20000.0
INACTIVE_ARREARS_THRESHOLD = 40000.0
_CENT = Decimal("0.01")
_ACCOUNTING_SCHEMA_READY = False


class InsufficientFundsError(ValueError):
    """Raised when an approved debit exceeds a member's available balance."""


class DuplicateFinancialTransactionError(ValueError):
    """Raised when a financial reference has already been posted."""


def _money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Amount must be a valid monetary value.") from exc
    if not result.is_finite():
        raise ValueError("Amount must be finite.")
    return result


def _allocate_proportionally(pool: Decimal, weights: dict[str, Decimal]) -> dict[str, Decimal]:
    positive_weights = {member_id: weight for member_id, weight in weights.items() if weight > 0}
    total_weight = sum(positive_weights.values(), Decimal("0.00"))
    if pool <= 0 or total_weight <= 0:
        return {member_id: Decimal("0.00") for member_id in weights}
    allocations: dict[str, Decimal] = {}
    recipient_ids = list(positive_weights)
    for member_id in recipient_ids[:-1]:
        allocations[member_id] = (pool * positive_weights[member_id] / total_weight).quantize(
            _CENT,
            rounding=ROUND_DOWN,
        )
    allocations[recipient_ids[-1]] = pool - sum(allocations.values(), Decimal("0.00"))
    return {
        member_id: allocations.get(member_id, Decimal("0.00"))
        for member_id in weights
    }


def ensure_accounting_schema() -> None:
    """Create the append-only, double-entry journal schema if it is not present."""
    global _ACCOUNTING_SCHEMA_READY
    if _ACCOUNTING_SCHEMA_READY:
        return

    execute_query(
        """
        CREATE TABLE IF NOT EXISTS accounting_transactions (
            transaction_id TEXT PRIMARY KEY,
            reference TEXT NOT NULL,
            category TEXT NOT NULL,
            member_id TEXT,
            loan_id BIGINT,
            amount NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
            status TEXT NOT NULL CHECK (status = 'APPROVED'),
            approver_id TEXT NOT NULL,
            approved_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            cycle_on DATE,
            reversal_of TEXT UNIQUE REFERENCES accounting_transactions(transaction_id),
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (category, reference)
        );
        """,
        fetch=False,
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS accounting_journal_entries (
            id BIGSERIAL PRIMARY KEY,
            transaction_id TEXT NOT NULL REFERENCES accounting_transactions(transaction_id),
            account_code TEXT NOT NULL,
            member_id TEXT,
            loan_id BIGINT,
            debit NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (debit >= 0),
            credit NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
            CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0))
        );
        """,
        fetch=False,
    )
    execute_query(
        "CREATE INDEX IF NOT EXISTS idx_accounting_entries_account_member ON accounting_journal_entries (account_code, member_id);",
        fetch=False,
    )
    execute_query(
        "CREATE INDEX IF NOT EXISTS idx_accounting_transactions_approved_at ON accounting_transactions (approved_at);",
        fetch=False,
    )
    execute_query(
        """
        CREATE OR REPLACE FUNCTION reject_accounting_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Accounting journal records are immutable; post a reversal instead.';
        END;
        $$ LANGUAGE plpgsql;
        """,
        fetch=False,
    )
    for table in ("accounting_transactions", "accounting_journal_entries"):
        execute_query(
            f"DROP TRIGGER IF EXISTS {table}_immutable ON {table};",
            fetch=False,
        )
        execute_query(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_accounting_mutation();",
            fetch=False,
        )
    execute_query(
        """
        CREATE OR REPLACE FUNCTION enforce_accounting_transaction_balance() RETURNS trigger AS $$
        DECLARE
            entry_count BIGINT;
            debit_total NUMERIC(14, 2);
            credit_total NUMERIC(14, 2);
        BEGIN
            SELECT COUNT(*), COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
            INTO entry_count, debit_total, credit_total
            FROM accounting_journal_entries
            WHERE transaction_id = NEW.transaction_id;
            IF entry_count < 2 OR debit_total <= 0 OR debit_total <> credit_total
               OR debit_total <> NEW.amount THEN
                RAISE EXCEPTION 'Accounting transaction % is not balanced.', NEW.transaction_id;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """,
        fetch=False,
    )
    execute_query(
        "DROP TRIGGER IF EXISTS accounting_transaction_balanced ON accounting_transactions;",
        fetch=False,
    )
    execute_query(
        """
        CREATE CONSTRAINT TRIGGER accounting_transaction_balanced
        AFTER INSERT ON accounting_transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_accounting_transaction_balance();
        """,
        fetch=False,
    )
    _ACCOUNTING_SCHEMA_READY = True


def record_transaction(
    *,
    reference: str,
    category: str,
    approver_id: str,
    entries: Iterable[dict[str, Any]],
    member_id: str | None = None,
    loan_id: int | None = None,
    status: str = "APPROVED",
    cycle_on: date | None = None,
    metadata: dict[str, Any] | None = None,
    reversal_of: str | None = None,
    connection: Any | None = None,
) -> str:
    """Atomically post a balanced, approved transaction as immutable journal lines."""
    if status != "APPROVED":
        raise ValueError("Only explicitly approved financial events may enter the ledger.")
    if not reference or not reference.strip() or not category or not category.strip():
        raise ValueError("A reference and category are required.")
    if not approver_id or not approver_id.strip():
        raise ValueError("An approver identifier is required.")

    normalized: list[dict[str, Any]] = []
    debit_total = Decimal("0.00")
    credit_total = Decimal("0.00")
    for entry in entries:
        account_code = str(entry.get("account_code") or "").strip()
        debit = _money(entry.get("debit", 0))
        credit = _money(entry.get("credit", 0))
        if not account_code or (debit > 0) == (credit > 0):
            raise ValueError("Each journal line must have an account and exactly one positive side.")
        normalized.append(
            {
                "account_code": account_code,
                "member_id": entry.get("member_id", member_id),
                "loan_id": entry.get("loan_id", loan_id),
                "debit": debit,
                "credit": credit,
            }
        )
        debit_total += debit
        credit_total += credit

    if len(normalized) < 2 or debit_total <= 0 or debit_total != credit_total:
        raise ValueError("Journal entries must contain at least two lines with equal debits and credits.")

    transaction_id = str(uuid.uuid4())
    metadata_values = metadata or {}
    category_code = category.strip().upper()
    if category_code == "LOAN_REPAYMENT" and "principal_remaining" not in metadata_values:
        raise ValueError("Loan repayment postings must include the resulting principal balance.")
    metadata_json = json.dumps(metadata_values, sort_keys=True, default=str)
    ensure_accounting_schema()
    try:
        connection_context = get_conn_from_pool() if connection is None else nullcontext(connection)
        with connection_context as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO accounting_transactions
                        (transaction_id, reference, category, member_id, loan_id, amount, status,
                         approver_id, approved_at, cycle_on, reversal_of, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, 'APPROVED', %s, CURRENT_TIMESTAMP, %s, %s, %s);
                    """,
                    (
                        transaction_id,
                        reference.strip(),
                        category.strip().upper(),
                        member_id,
                        loan_id,
                        debit_total,
                        approver_id.strip(),
                        cycle_on,
                        reversal_of,
                        metadata_json,
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO accounting_journal_entries
                        (transaction_id, account_code, member_id, loan_id, debit, credit)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    [
                        (
                            transaction_id,
                            item["account_code"],
                            item["member_id"],
                            item["loan_id"],
                            item["debit"],
                            item["credit"],
                        )
                        for item in normalized
                    ],
                )
                if category_code == "LOAN_DISBURSEMENT":
                    cursor.execute(
                        "UPDATE loans SET status = 'Approved', approved_by = %s, approved_date = CURRENT_TIMESTAMP "
                        "WHERE loan_id = %s;",
                        (approver_id.strip(), loan_id),
                    )
                elif category_code == "LOAN_REPAYMENT":
                    principal_remaining = Decimal(str(metadata_values["principal_remaining"]))
                    cursor.execute(
                        "UPDATE loans SET status = %s, last_payment_applied_at = CURRENT_DATE WHERE loan_id = %s;",
                        ("Closed" if principal_remaining <= 0 else "Active", loan_id),
                    )
                elif category_code == "REVERSAL" and loan_id and metadata_values.get("reversed_category") in {
                    "LOAN_REPAYMENT",
                    "LOAN_DISBURSEMENT",
                }:
                    cursor.execute(
                        """
                        SELECT COALESCE(SUM(e.credit - e.debit), 0)
                        FROM accounting_journal_entries e
                        JOIN accounting_transactions t USING (transaction_id)
                        WHERE t.status = 'APPROVED' AND e.loan_id = %s
                          AND e.account_code = 'LOAN_PRINCIPAL_RECEIVABLE';
                        """,
                        (loan_id,),
                    )
                    principal_balance = Decimal(str(cursor.fetchone()[0] or 0))
                    cursor.execute(
                        "UPDATE loans SET status = %s, last_payment_applied_at = CURRENT_DATE WHERE loan_id = %s;",
                        ("Closed" if principal_balance >= 0 else "Active", loan_id),
                    )
            conn.commit()
        st.cache_data.clear()
    except Exception:
        logger.exception("Unable to post accounting transaction %s", reference)
        raise
    return transaction_id


def reverse_transaction(
    transaction_id: str,
    *,
    approver_id: str,
    reason: str,
    reference: str,
) -> str:
    """Post a new, linked transaction with the exact opposite of an original."""
    if not reason.strip():
        raise ValueError("A reversal reason is required.")
    ensure_accounting_schema()
    with get_conn_from_pool() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.category, t.member_id, t.loan_id, e.account_code, e.member_id,
                       e.loan_id, e.debit, e.credit
                FROM accounting_transactions t
                JOIN accounting_journal_entries e USING (transaction_id)
                WHERE t.transaction_id = %s AND t.status = 'APPROVED'
                ORDER BY e.id;
                """,
                (transaction_id,),
            )
            original = cursor.fetchall()
    if not original:
        raise ValueError("Approved transaction was not found.")
    return record_transaction(
        reference=reference,
        category="REVERSAL",
        approver_id=approver_id,
        member_id=original[0][1],
        loan_id=original[0][2],
        entries=[
            {
                "account_code": row[3],
                "member_id": row[4],
                "loan_id": row[5],
                "debit": row[7],
                "credit": row[6],
            }
            for row in original
        ],
        metadata={"reason": reason, "reversed_category": original[0][0]},
        reversal_of=transaction_id,
    )


def _account_balance(account_code: str, member_id: str | None = None, loan_id: int | None = None) -> Decimal:
    ensure_accounting_schema()
    filters = ["t.status = 'APPROVED'", "e.account_code = %s"]
    params: list[Any] = [account_code]
    if member_id is not None:
        filters.append("UPPER(BTRIM(e.member_id::text)) = UPPER(BTRIM(%s))")
        params.append(member_id)
    if loan_id is not None:
        filters.append("e.loan_id = %s")
        params.append(loan_id)
    rows = execute_query(
        "SELECT COALESCE(SUM(e.credit - e.debit), 0) AS balance "
        "FROM accounting_journal_entries e JOIN accounting_transactions t USING (transaction_id) "
        f"WHERE {' AND '.join(filters)};",
        params=tuple(params),
        fetch=True,
    ) or []
    return Decimal(str(rows[0].get("balance") or 0))


def _get_unposted_legacy_subscription_rows(
    *,
    member_ids: list[str] | None = None,
    member_id: str | None = None,
    cycle_start: date | None = None,
    cycle_end: date | None = None,
) -> list[dict[str, Any]]:
    """Return successful legacy subscription rows not already represented in the ledger."""
    ensure_accounting_schema()
    predicates = [
        "UPPER(BTRIM(COALESCE(s.status::text, ''))) IN ('APPROVED', 'POSTED', 'SUCCESS', 'PAID')",
        "s.amount_paid > 0",
        """
        NOT EXISTS (
            SELECT 1
            FROM accounting_transactions t
            WHERE t.category = 'SUBSCRIPTION_RECEIPT'
              AND t.status = 'APPROVED'
              AND UPPER(BTRIM(COALESCE(t.member_id::text, ''))) = UPPER(BTRIM(s.member_id::text))
              AND t.cycle_on::date = s.billing_month::date
              AND ROUND(t.amount::numeric, 2) = ROUND(s.amount_paid::numeric, 2)
        )
        """,
    ]
    params: list[Any] = []
    if member_ids is not None:
        unique_keys = list(dict.fromkeys(str(value).strip().upper() for value in member_ids if value))
        if not unique_keys:
            return []
        predicates.append("UPPER(BTRIM(s.member_id::text)) = ANY(%s)")
        params.append(unique_keys)
    elif member_id is not None:
        predicates.append("UPPER(BTRIM(s.member_id::text)) = UPPER(BTRIM(%s))")
        params.append(member_id)
    if cycle_start is not None:
        predicates.append("s.billing_month::date >= %s")
        params.append(cycle_start)
    if cycle_end is not None:
        predicates.append("s.billing_month::date < %s")
        params.append(cycle_end)
    return execute_query(
        f"""
        SELECT s.member_id::text AS member_id, m.full_name, s.billing_month,
               s.amount_paid, s.status, s.billing_month AS approved_at,
               NULL::text AS reference, 'LEGACY_SUBSCRIPTION' AS category
        FROM subscriptions s
        LEFT JOIN members m
          ON UPPER(BTRIM(m.member_id::text)) = UPPER(BTRIM(s.member_id::text))
        WHERE {' AND '.join(predicates)}
        ORDER BY s.billing_month DESC;
        """,
        params=tuple(params),
        fetch=True,
    ) or []


def _apply_legacy_subscription_savings(
    balances: dict[str, float],
    legacy_amount: Decimal,
) -> None:
    """Apply unreconciled paid subscriptions using the standard reserve-first allocation."""
    remaining_reserve = max(
        _money(WELFARE_RESERVE_LIMIT) - _money(balances["welfare_balance"]),
        Decimal("0.00"),
    )
    to_welfare = min(legacy_amount, remaining_reserve)
    balances["welfare_balance"] += float(to_welfare)
    balances["savings_balance"] += float(legacy_amount - to_welfare)
    balances["total_balance"] = balances["welfare_balance"] + balances["savings_balance"]


def _get_legacy_subscription_fund_allocations() -> dict[str, Decimal]:
    legacy_rows = _get_unposted_legacy_subscription_rows()
    legacy_by_member: dict[str, Decimal] = {}
    for row in legacy_rows:
        member_key = str(row.get("member_id") or "").strip().upper()
        if member_key:
            legacy_by_member[member_key] = legacy_by_member.get(member_key, Decimal("0.00")) + _money(
                row.get("amount_paid") or 0
            )
    if not legacy_by_member:
        return {"savings": Decimal("0.00"), "welfare": Decimal("0.00")}

    ensure_accounting_schema()
    welfare_rows = execute_query(
        """
        SELECT UPPER(BTRIM(e.member_id::text)) AS member_key,
               COALESCE(SUM(e.credit - e.debit), 0) AS welfare_balance
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        WHERE t.status = 'APPROVED'
          AND e.account_code = 'MEMBER_WELFARE_LIABILITY'
          AND UPPER(BTRIM(e.member_id::text)) = ANY(%s)
        GROUP BY UPPER(BTRIM(e.member_id::text));
        """,
        params=(list(legacy_by_member),),
        fetch=True,
    ) or []
    current_welfare = {
        str(row["member_key"]): max(_money(row.get("welfare_balance") or 0), Decimal("0.00"))
        for row in welfare_rows
    }
    allocated_welfare = Decimal("0.00")
    allocated_savings = Decimal("0.00")
    for member_key, legacy_amount in legacy_by_member.items():
        reserve_room = max(
            _money(WELFARE_RESERVE_LIMIT) - current_welfare.get(member_key, Decimal("0.00")),
            Decimal("0.00"),
        )
        to_welfare = min(legacy_amount, reserve_room)
        allocated_welfare += to_welfare
        allocated_savings += legacy_amount - to_welfare
    return {"savings": allocated_savings, "welfare": allocated_welfare}


def get_loan_balances(loan_id: int) -> dict[str, float]:
    """Return ledger-backed principal and interest receivables for one loan."""
    principal = -_account_balance("LOAN_PRINCIPAL_RECEIVABLE", loan_id=loan_id)
    interest = -_account_balance("LOAN_INTEREST_RECEIVABLE", loan_id=loan_id)
    return {
        "principal": float(max(principal, Decimal("0"))),
        "interest": float(max(interest, Decimal("0"))),
        "outstanding": float(max(principal, Decimal("0")) + max(interest, Decimal("0"))),
    }


def _get_loan_balances_batch(loan_ids: list[int]) -> dict[int, dict[str, Any]]:
    unique_ids = list(dict.fromkeys(loan_ids))
    if not unique_ids:
        return {}
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT e.loan_id, e.account_code,
               COUNT(*) AS ledger_entry_count,
               COALESCE(SUM(e.credit - e.debit), 0) AS signed_balance
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        WHERE t.status = 'APPROVED' AND e.loan_id = ANY(%s)
          AND e.account_code IN ('LOAN_PRINCIPAL_RECEIVABLE', 'LOAN_INTEREST_RECEIVABLE')
        GROUP BY e.loan_id, e.account_code;
        """,
        params=(unique_ids,),
        fetch=True,
    ) or []
    balances: dict[int, dict[str, Any]] = {}
    for row in rows:
        loan_balances = balances.setdefault(
            int(row["loan_id"]),
            {"ledger_entry_count": 0},
        )
        loan_balances[row["account_code"]] = Decimal(str(row["signed_balance"] or 0))
        loan_balances["ledger_entry_count"] += int(row.get("ledger_entry_count") or 0)
    result: dict[int, dict[str, Any]] = {}
    for loan_id in unique_ids:
        accounts = balances.get(loan_id, {})
        principal = max(-accounts.get("LOAN_PRINCIPAL_RECEIVABLE", Decimal("0")), Decimal("0"))
        interest = max(-accounts.get("LOAN_INTEREST_RECEIVABLE", Decimal("0")), Decimal("0"))
        ledger_backed = accounts.get("ledger_entry_count", 0) > 0
        result[loan_id] = {
            "principal": float(principal) if ledger_backed else None,
            "interest": float(interest) if ledger_backed else None,
            "outstanding": float(principal + interest) if ledger_backed else None,
            "ledger_backed": ledger_backed,
        }
    return result


def get_member_balances(member_id: str) -> dict[str, float]:
    """Return a member's approved ledger balances, split by fund/account."""
    savings = _account_balance("MEMBER_SAVINGS_LIABILITY", member_id=member_id)
    welfare = _account_balance("MEMBER_WELFARE_LIABILITY", member_id=member_id)
    credit = _account_balance("MEMBER_CREDIT_LIABILITY", member_id=member_id)
    debt = -_account_balance("WELFARE_DEBT_RECEIVABLE", member_id=member_id)
    balances = {
        "savings_balance": float(max(savings, Decimal("0"))),
        "welfare_balance": float(max(welfare, Decimal("0"))),
        "member_credit": float(max(credit, Decimal("0"))),
        "welfare_debt": float(max(debt, Decimal("0"))),
        "total_balance": float(max(savings, Decimal("0")) + max(welfare, Decimal("0"))),
    }
    legacy_rows = _get_unposted_legacy_subscription_rows(member_id=member_id)
    legacy_amount = sum((_money(row.get("amount_paid") or 0) for row in legacy_rows), Decimal("0.00"))
    _apply_legacy_subscription_savings(balances, legacy_amount)
    return balances


def get_member_balances_batch(
    member_ids: list[str],
    *,
    as_of: date | None = None,
) -> dict[str, dict[str, float]]:
    """Fetch member ledger balances, optionally as of an inclusive calendar date."""
    unique_ids = list(dict.fromkeys(member_ids))
    if not unique_ids:
        return {}
    ensure_accounting_schema()
    cutoff_clause = ""
    params: list[Any] = [[member_id.strip().upper() for member_id in unique_ids]]
    if as_of is not None:
        cutoff_clause = "AND t.approved_at < %s"
        params.append(datetime.combine(as_of + timedelta(days=1), time.min))
    rows = execute_query(
        f"""
        SELECT e.member_id, e.account_code, COALESCE(SUM(e.credit - e.debit), 0) AS balance
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        WHERE t.status = 'APPROVED' AND UPPER(BTRIM(e.member_id::text)) = ANY(%s)
          {cutoff_clause}
          AND e.account_code IN (
              'MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY',
              'MEMBER_CREDIT_LIABILITY', 'WELFARE_DEBT_RECEIVABLE'
          )
        GROUP BY e.member_id, e.account_code;
        """,
        params=tuple(params),
        fetch=True,
    ) or []
    account_balances: dict[str, dict[str, Decimal]] = {}
    for row in rows:
        account_balances.setdefault(str(row["member_id"]).strip().upper(), {})[row["account_code"]] = Decimal(str(row["balance"] or 0))
    result: dict[str, dict[str, float]] = {}
    for member_id in unique_ids:
        values = account_balances.get(member_id.strip().upper(), {})
        savings = max(values.get("MEMBER_SAVINGS_LIABILITY", Decimal("0.00")), Decimal("0.00"))
        welfare = max(values.get("MEMBER_WELFARE_LIABILITY", Decimal("0.00")), Decimal("0.00"))
        credit = max(values.get("MEMBER_CREDIT_LIABILITY", Decimal("0.00")), Decimal("0.00"))
        debt = max(-values.get("WELFARE_DEBT_RECEIVABLE", Decimal("0.00")), Decimal("0.00"))
        result[member_id] = {
            "savings_balance": float(savings),
            "welfare_balance": float(welfare),
            "member_credit": float(credit),
            "welfare_debt": float(debt),
            "total_balance": float(savings + welfare),
        }
    legacy_rows = _get_unposted_legacy_subscription_rows(
        member_ids=unique_ids,
        cycle_end=as_of + timedelta(days=1) if as_of is not None else None,
    )
    legacy_totals: dict[str, Decimal] = {}
    for row in legacy_rows:
        key = str(row.get("member_id") or "").strip().upper()
        legacy_totals[key] = legacy_totals.get(key, Decimal("0.00")) + _money(row.get("amount_paid") or 0)
    for member_id in unique_ids:
        _apply_legacy_subscription_savings(
            result[member_id],
            legacy_totals.get(member_id.strip().upper(), Decimal("0.00")),
        )
    return result


def get_member_balance_breakdown(member_id: str) -> dict[str, float]:
    balances = get_member_balances(member_id)
    return {
        "total_balance": balances["total_balance"],
        "welfare_balance": balances["welfare_balance"],
        "savings_balance": balances["savings_balance"],
    }


def get_member_available_balance(member_id: str) -> float:
    balances = get_member_balances(member_id)
    return balances["savings_balance"] + balances["welfare_balance"]


def post_subscription_payment(
    *,
    member_id: str,
    amount: float,
    reference: str,
    approved_by: str,
    billing_date: date | None = None,
) -> str:
    value = _money(amount)
    if value <= 0:
        raise ValueError("Subscription payment must be positive.")
    ensure_accounting_schema()
    existing = execute_query(
        "SELECT transaction_id, member_id, amount FROM accounting_transactions "
        "WHERE category = 'SUBSCRIPTION_RECEIPT' AND reference = %s;",
        params=(reference,),
        fetch=True,
    ) or []
    if existing:
        if existing[0]["member_id"] == member_id and _money(existing[0]["amount"]) == value:
            return str(existing[0]["transaction_id"])
        raise DuplicateFinancialTransactionError("This subscription reference was already used for a different payment.")
    current_welfare = _money(get_member_balances(member_id)["welfare_balance"])
    to_welfare = min(value, max(_money(WELFARE_RESERVE_LIMIT) - current_welfare, Decimal("0.00")))
    to_savings = value - to_welfare
    entries = [
        {"account_code": "CASH", "debit": value, "credit": 0},
    ]
    if to_welfare:
        entries.append(
            {"account_code": "MEMBER_WELFARE_LIABILITY", "member_id": member_id, "debit": 0, "credit": to_welfare}
        )
    if to_savings:
        entries.append(
            {"account_code": "MEMBER_SAVINGS_LIABILITY", "member_id": member_id, "debit": 0, "credit": to_savings}
        )
    return record_transaction(
        reference=reference,
        category="SUBSCRIPTION_RECEIPT",
        approver_id=approved_by,
        member_id=member_id,
        cycle_on=billing_date,
        entries=entries,
        metadata={"billing_date": billing_date},
    )


def record_opening_loan(
    loan_id: int,
    *,
    approver_id: str,
    reference: str | None = None,
) -> str:
    """Post a newly approved loan as principal receivable against cash."""
    ensure_accounting_schema()
    rows = execute_query(
        "SELECT member_id, amount_requested FROM loans WHERE loan_id = %s;",
        params=(loan_id,),
        fetch=True,
    ) or []
    if not rows:
        raise ValueError("Loan was not found.")
    member_id = str(rows[0]["member_id"])
    amount = _money(rows[0]["amount_requested"])
    if amount <= 0:
        raise ValueError("Approved loan principal must be positive.")
    reference_value = reference or f"loan-disbursement:{loan_id}"
    existing = execute_query(
        "SELECT transaction_id, member_id, amount FROM accounting_transactions "
        "WHERE category = 'LOAN_DISBURSEMENT' AND reference = %s;",
        params=(reference_value,),
        fetch=True,
    ) or []
    if existing:
        if existing[0]["member_id"] == member_id and _money(existing[0]["amount"]) == amount:
            execute_query(
                "UPDATE loans SET status = 'Approved', approved_by = %s, "
                "approved_date = COALESCE(approved_date, CURRENT_TIMESTAMP) WHERE loan_id = %s;",
                params=(approver_id, loan_id),
                fetch=False,
            )
            return str(existing[0]["transaction_id"])
        raise DuplicateFinancialTransactionError("This loan disbursement reference was already used.")
    return record_transaction(
        reference=reference_value,
        category="LOAN_DISBURSEMENT",
        approver_id=approver_id,
        member_id=member_id,
        loan_id=loan_id,
        entries=[
            {"account_code": "LOAN_PRINCIPAL_RECEIVABLE", "member_id": member_id, "loan_id": loan_id, "debit": amount, "credit": 0},
            {"account_code": "CASH", "member_id": member_id, "loan_id": loan_id, "debit": 0, "credit": amount},
        ],
    )


def get_member_loan_accounts(member_id: str) -> list[dict[str, Any]]:
    """Return all member loan records, identifying balances without ledger backing."""
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT l.loan_id, l.member_id, l.status, l.approved_date, l.applied_date
        FROM loans l
        WHERE UPPER(BTRIM(l.member_id::text)) = UPPER(BTRIM(%s))
        ORDER BY l.loan_id DESC;
        """,
        params=(member_id,),
        fetch=True,
    ) or []
    balances = _get_loan_balances_batch([int(row["loan_id"]) for row in rows])
    return [{**row, **balances[int(row["loan_id"])]} for row in rows]


def get_member_loan_outstanding_total(member_id: str) -> float:
    return float(sum(
        (
            Decimal(str(row["outstanding"]))
            for row in get_member_loan_accounts(member_id)
            if row.get("outstanding") is not None
        ),
        Decimal("0.00"),
    ))


def get_loan_records(
    member_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return loan workflow fields with monetary balances derived only from the journal."""
    predicates: list[str] = []
    params: list[Any] = []
    if member_id:
        predicates.append("UPPER(BTRIM(l.member_id::text)) = UPPER(BTRIM(%s))")
        params.append(member_id)
    if status:
        predicates.append("UPPER(BTRIM(l.status::text)) = UPPER(BTRIM(%s))")
        params.append(status)
    where = f"WHERE {' AND '.join(predicates)}" if predicates else ""
    purpose_select = "l.purpose" if loans_table_has_purpose_column() else "NULL AS purpose"
    rows = execute_query(
        f"""
        SELECT l.loan_id, l.member_id, l.amount_requested, l.status, l.approved_by,
               l.approved_date, l.applied_date, l.last_interest_applied_at,
               l.last_payment_applied_at, {purpose_select},
               COALESCE(m.full_name, '') AS applicant_name
        FROM loans l
        LEFT JOIN members m ON m.member_id::text = l.member_id::text
        {where}
        ORDER BY l.applied_date DESC NULLS LAST, l.loan_id DESC;
        """,
        params=tuple(params),
        fetch=True,
    ) or []
    balances_by_loan = _get_loan_balances_batch([int(row["loan_id"]) for row in rows])
    for row in rows:
        balances = balances_by_loan[int(row["loan_id"])]
        row.update(
            outstanding_balance=balances["outstanding"],
            principal_outstanding=balances["principal"],
            interest_accumulated=balances["interest"],
            ledger_backed=balances["ledger_backed"],
        )
    return rows


def loans_table_has_purpose_column() -> bool:
    rows = execute_query(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'loans' AND column_name = 'purpose' LIMIT 1;",
        fetch=True,
    ) or []
    return bool(rows)


def record_loan_interest_accrual(
    *,
    loan_id: int,
    member_id: str,
    accrual_date: date,
    approved_by: str,
    rate: float = 0.10,
) -> float:
    """Accrue interest on remaining principal only; an accrual is not cash income."""
    ensure_accounting_schema()
    loan_rows = execute_query(
        "SELECT member_id, status FROM loans WHERE loan_id = %s;",
        params=(loan_id,),
        fetch=True,
    ) or []
    if not loan_rows:
        raise ValueError("Loan was not found.")
    if str(loan_rows[0].get("member_id") or "").strip().casefold() != member_id.strip().casefold():
        raise ValueError("Loan member does not match the requested interest account.")
    if str(loan_rows[0].get("status") or "").strip().casefold() not in {"approved", "active"}:
        return 0.0
    reference = f"loan-interest:{loan_id}:{accrual_date.isoformat()}"
    existing = execute_query(
        """
        SELECT t.amount,
               EXISTS (
                   SELECT 1 FROM accounting_transactions reversal
                   WHERE reversal.reversal_of = t.transaction_id AND reversal.status = 'APPROVED'
               ) AS is_reversed
        FROM accounting_transactions t
        WHERE t.category = 'LOAN_INTEREST_ACCRUAL' AND t.reference = %s;
        """,
        params=(reference,),
        fetch=True,
    ) or []
    if existing:
        if existing[0].get("is_reversed"):
            raise DuplicateFinancialTransactionError(
                "This interest accrual was reversed; it cannot be silently reused."
            )
        return float(_money(existing[0]["amount"]))
    principal = _money(-_account_balance("LOAN_PRINCIPAL_RECEIVABLE", loan_id=loan_id))
    if principal <= 0:
        return 0.0
    interest = _money(principal * Decimal(str(rate)))
    if interest <= 0:
        return 0.0
    record_transaction(
        reference=reference,
        category="LOAN_INTEREST_ACCRUAL",
        approver_id=approved_by,
        member_id=member_id,
        loan_id=loan_id,
        cycle_on=accrual_date,
        entries=[
            {"account_code": "LOAN_INTEREST_RECEIVABLE", "member_id": member_id, "loan_id": loan_id, "debit": interest, "credit": 0},
            {"account_code": "INTEREST_INCOME", "member_id": member_id, "loan_id": loan_id, "debit": 0, "credit": interest},
        ],
        metadata={"basis": "declining principal", "rate": str(rate)},
    )
    return float(interest)


def record_loan_repayment(
    *,
    loan_id: int,
    member_id: str,
    amount: float,
    reference: str,
    approved_by: str,
) -> dict[str, float]:
    """Apply an approved repayment interest-first, then principal, then member credit."""
    payment = _money(amount)
    if payment <= 0:
        raise ValueError("Loan repayment must be positive.")
    ensure_accounting_schema()
    with get_conn_from_pool() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT loan_id, member_id
                FROM loans
                WHERE loan_id = %s
                  AND UPPER(BTRIM(member_id::text)) = UPPER(BTRIM(%s))
                FOR UPDATE;
                """,
                (loan_id, member_id),
            )
            loan = cursor.fetchone()
            if not loan:
                raise ValueError("Loan was not found for this member.")

            cursor.execute(
                """
                SELECT t.transaction_id, t.member_id, t.loan_id, t.amount, t.metadata,
                       EXISTS (
                           SELECT 1 FROM accounting_transactions reversal
                           WHERE reversal.reversal_of = t.transaction_id
                             AND reversal.status = 'APPROVED'
                       ) AS is_reversed
                FROM accounting_transactions t
                WHERE t.category = 'LOAN_REPAYMENT' AND t.reference = %s;
                """,
                (reference,),
            )
            prior = cursor.fetchone()
            cursor.execute(
                """
                SELECT e.account_code, COALESCE(SUM(e.credit - e.debit), 0) AS signed_balance
                FROM accounting_journal_entries e
                JOIN accounting_transactions t USING (transaction_id)
                WHERE t.status = 'APPROVED' AND e.loan_id = %s
                  AND e.account_code IN ('LOAN_PRINCIPAL_RECEIVABLE', 'LOAN_INTEREST_RECEIVABLE')
                GROUP BY e.account_code;
                """,
                (loan_id,),
            )
            ledger_rows = cursor.fetchall()

            if prior:
                prior_metadata = prior[4]
                if isinstance(prior_metadata, str):
                    prior_metadata = json.loads(prior_metadata)
                if (
                    str(prior[1]).strip().casefold() != member_id.strip().casefold()
                    or int(prior[2]) != loan_id
                    or _money(prior[3]) != payment
                ):
                    raise DuplicateFinancialTransactionError(
                        "This repayment reference was already used for a different transaction."
                    )
                if prior[5]:
                    raise DuplicateFinancialTransactionError(
                        "This repayment reference has already been reversed; use a new reference for another payment."
                    )
                balances_by_account = {
                    row[0]: Decimal(str(row[1] or 0))
                    for row in ledger_rows
                }
                return {
                    "interest_paid": float(prior_metadata["interest_paid"]),
                    "principal_paid": float(prior_metadata["principal_paid"]),
                    "overpayment_credit": float(prior_metadata["overpayment_credit"]),
                    "principal_remaining": float(
                        max(-balances_by_account.get("LOAN_PRINCIPAL_RECEIVABLE", Decimal("0")), Decimal("0"))
                    ),
                    "interest_remaining": float(
                        max(-balances_by_account.get("LOAN_INTEREST_RECEIVABLE", Decimal("0")), Decimal("0"))
                    ),
                }

            balances_by_account = {
                row[0]: Decimal(str(row[1] or 0))
                for row in ledger_rows
            }
            principal_due = max(
                -balances_by_account.get("LOAN_PRINCIPAL_RECEIVABLE", Decimal("0.00")),
                Decimal("0.00"),
            )
            interest_due = max(
                -balances_by_account.get("LOAN_INTEREST_RECEIVABLE", Decimal("0.00")),
                Decimal("0.00"),
            )
            if interest_due + principal_due <= 0:
                raise ValueError("Loan has no outstanding balance.")

            interest_paid = min(payment, interest_due)
            after_interest = payment - interest_paid
            principal_paid = min(after_interest, principal_due)
            overpayment = after_interest - principal_paid
            lines: list[dict[str, Any]] = [
                {"account_code": "CASH", "member_id": member_id, "loan_id": loan_id, "debit": payment, "credit": 0},
            ]
            if interest_paid:
                lines.append(
                    {"account_code": "LOAN_INTEREST_RECEIVABLE", "member_id": member_id, "loan_id": loan_id, "debit": 0, "credit": interest_paid}
                )
            if principal_paid:
                lines.append(
                    {"account_code": "LOAN_PRINCIPAL_RECEIVABLE", "member_id": member_id, "loan_id": loan_id, "debit": 0, "credit": principal_paid}
                )
            if overpayment:
                lines.append(
                    {"account_code": "MEMBER_CREDIT_LIABILITY", "member_id": member_id, "loan_id": loan_id, "debit": 0, "credit": overpayment}
                )
            record_transaction(
                reference=reference,
                category="LOAN_REPAYMENT",
                approver_id=approved_by,
                member_id=member_id,
                loan_id=loan_id,
                entries=lines,
                metadata={
                    "interest_paid": str(interest_paid),
                    "principal_paid": str(principal_paid),
                    "overpayment_credit": str(overpayment),
                    "principal_remaining": str(principal_due - principal_paid),
                },
                connection=conn,
            )
            return {
                "interest_paid": float(interest_paid),
                "principal_paid": float(principal_paid),
                "overpayment_credit": float(overpayment),
                "principal_remaining": float(principal_due - principal_paid),
                "interest_remaining": float(interest_due - interest_paid),
            }


def record_welfare_debt(
    *,
    member_id: str,
    amount: float,
    reference: str,
    approved_by: str,
    notes: str,
) -> str:
    value = _money(amount)
    if value <= 0:
        raise ValueError("Welfare debt must be positive.")
    return record_transaction(
        reference=reference,
        category="WELFARE_DEBT",
        approver_id=approved_by,
        member_id=member_id,
        entries=[
            {"account_code": "WELFARE_DEBT_RECEIVABLE", "member_id": member_id, "debit": value, "credit": 0},
            {"account_code": "WELFARE_FUND", "member_id": member_id, "debit": 0, "credit": value},
        ],
        metadata={"notes": notes},
    )


def settle_welfare_debt(
    *,
    member_id: str,
    amount: float,
    reference: str,
    approved_by: str,
) -> str:
    """Settle an existing welfare debt from an approved cash/mobile-money deposit."""
    value = _money(amount)
    if value <= 0:
        raise ValueError("Welfare debt settlement must be positive.")
    ensure_accounting_schema()
    existing = execute_query(
        "SELECT transaction_id, member_id, amount FROM accounting_transactions "
        "WHERE category = 'WELFARE_DEBT_SETTLEMENT' AND reference = %s;",
        params=(reference,),
        fetch=True,
    ) or []
    if existing:
        prior = existing[0]
        if str(prior["member_id"]) != member_id or _money(prior["amount"]) != value:
            raise DuplicateFinancialTransactionError("This debt-settlement reference was used for another payment.")
        return str(prior["transaction_id"])
    debt = _money(get_member_balances(member_id)["welfare_debt"])
    if value > debt:
        raise InsufficientFundsError("The settlement cannot exceed the member's outstanding welfare debt.")
    return record_transaction(
        reference=reference,
        category="WELFARE_DEBT_SETTLEMENT",
        approver_id=approved_by,
        member_id=member_id,
        entries=[
            {"account_code": "CASH", "member_id": member_id, "debit": value, "credit": 0},
            {"account_code": "WELFARE_DEBT_RECEIVABLE", "member_id": member_id, "debit": 0, "credit": value},
        ],
        metadata={"settlement_method": "approved cash/mobile money deposit"},
    )


def post_welfare_contribution(
    *,
    contributions: dict[str, float],
    reference: str,
    approved_by: str,
) -> str:
    ensure_accounting_schema()
    existing = execute_query(
        "SELECT transaction_id, metadata FROM accounting_transactions "
        "WHERE category = 'WELFARE_CONTRIBUTION' AND reference = %s AND status = 'APPROVED';",
        params=(reference,),
        fetch=True,
    ) or []
    if existing:
        prior_metadata = existing[0]["metadata"]
        if isinstance(prior_metadata, str):
            prior_metadata = json.loads(prior_metadata)
        prior_contributions = prior_metadata.get("contributions", {})
        requested = {key: _money(value) for key, value in contributions.items()}
        posted = {key: _money(value) for key, value in prior_contributions.items()}
        if requested != posted:
            raise DuplicateFinancialTransactionError("This welfare contribution reference was already used for different amounts.")
        return str(existing[0]["transaction_id"])
    entries: list[dict[str, Any]] = []
    total = Decimal("0.00")
    for member_id, amount in contributions.items():
        value = _money(amount)
        if value <= 0:
            raise ValueError("Welfare contributions must be positive.")
        balances = get_member_balances(member_id)
        available_welfare = _money(balances["welfare_balance"])
        available_savings = _money(balances["savings_balance"])
        if available_welfare + available_savings < value:
            raise InsufficientFundsError(f"Member {member_id} does not have enough available funds.")
        from_welfare = min(available_welfare, value)
        from_savings = value - from_welfare
        if from_welfare:
            entries.append(
                {"account_code": "MEMBER_WELFARE_LIABILITY", "member_id": member_id, "debit": from_welfare, "credit": 0}
            )
        if from_savings:
            entries.append(
                {"account_code": "MEMBER_SAVINGS_LIABILITY", "member_id": member_id, "debit": from_savings, "credit": 0}
            )
        entries.append(
            {"account_code": "WELFARE_FUND", "member_id": member_id, "debit": 0, "credit": value}
        )
        total += value
    if not entries:
        raise ValueError("No eligible welfare contributions were provided.")
    return record_transaction(
        reference=reference,
        category="WELFARE_CONTRIBUTION",
        approver_id=approved_by,
        entries=entries,
        metadata={"contributions": contributions, "total": str(total)},
    )


def post_welfare_payment(
    *,
    beneficiary_id: str,
    amount: float,
    reference: str,
    approved_by: str,
) -> str:
    value = _money(amount)
    if value <= 0:
        raise ValueError("Welfare payment must be positive.")
    ensure_accounting_schema()
    existing = execute_query(
        "SELECT transaction_id, member_id, amount FROM accounting_transactions "
        "WHERE category = 'WELFARE_PAYMENT' AND reference = %s AND status = 'APPROVED';",
        params=(reference,),
        fetch=True,
    ) or []
    if existing:
        prior = existing[0]
        if str(prior["member_id"]) != beneficiary_id or _money(prior["amount"]) != value:
            raise DuplicateFinancialTransactionError("This welfare payment reference was already used for a different payment.")
        return str(existing[0]["transaction_id"])
    fund_balance = _account_balance("WELFARE_FUND")
    available = max(fund_balance, Decimal("0.00"))
    if available < value:
        raise InsufficientFundsError("The welfare fund does not have enough approved contributions to pay this request.")
    cash_available = max(-_account_balance("CASH"), Decimal("0.00"))
    if cash_available < value:
        raise InsufficientFundsError("Verified cash is insufficient to settle this welfare payment.")
    return record_transaction(
        reference=reference,
        category="WELFARE_PAYMENT",
        approver_id=approved_by,
        member_id=beneficiary_id,
        entries=[
            {"account_code": "WELFARE_FUND", "member_id": beneficiary_id, "debit": value, "credit": 0},
            {"account_code": "CASH", "member_id": beneficiary_id, "debit": 0, "credit": value},
        ],
    )


def get_welfare_contribution_breakdown(request_id: int) -> list[dict[str, Any]]:
    ensure_accounting_schema()
    return execute_query(
        """
        SELECT e.member_id, COALESCE(m.full_name, '') AS member_name,
               COALESCE(SUM(e.credit - e.debit), 0) AS contribution_amount
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        LEFT JOIN members m ON m.member_id::text = e.member_id
        WHERE t.status = 'APPROVED'
          AND ((t.category = 'WELFARE_CONTRIBUTION' AND t.reference = %s)
               OR (t.category = 'REVERSAL' AND original.category = 'WELFARE_CONTRIBUTION'
                   AND original.reference = %s))
          AND e.account_code = 'WELFARE_FUND'
        GROUP BY e.member_id, m.full_name
        HAVING SUM(e.credit - e.debit) > 0
        ORDER BY m.full_name;
        """,
        params=(f"welfare-contribution:{request_id}", f"welfare-contribution:{request_id}"),
        fetch=True,
    ) or []


def get_welfare_payment_amount(request_id: int) -> float:
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT COALESCE(SUM(e.debit - e.credit), 0) AS amount
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND ((t.category = 'WELFARE_PAYMENT' AND t.reference = %s)
               OR (t.category = 'REVERSAL' AND original.category = 'WELFARE_PAYMENT'
                   AND original.reference = %s))
          AND e.account_code = 'WELFARE_FUND';
        """,
        params=(f"welfare-payment:{request_id}", f"welfare-payment:{request_id}"),
        fetch=True,
    ) or []
    return float(rows[0]["amount"] or 0.0) if rows else 0.0


def get_member_welfare_ledger_totals(member_id: str) -> dict[str, float]:
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT
            COALESCE(SUM(CASE WHEN (t.category = 'WELFARE_CONTRIBUTION'
                              OR (t.category = 'REVERSAL' AND original.category = 'WELFARE_CONTRIBUTION'))
                              AND e.account_code = 'WELFARE_FUND' THEN e.credit - e.debit ELSE 0 END), 0) AS contributions,
            COALESCE(SUM(CASE WHEN (t.category = 'WELFARE_PAYMENT'
                              OR (t.category = 'REVERSAL' AND original.category = 'WELFARE_PAYMENT'))
                              AND e.account_code = 'WELFARE_FUND' THEN e.debit - e.credit ELSE 0 END), 0) AS payments_received,
            MAX(CASE WHEN t.category = 'WELFARE_CONTRIBUTION' THEN t.approved_at END) AS last_contribution_date
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED' AND e.member_id = %s;
        """,
        params=(member_id,),
        fetch=True,
    ) or []
    row = rows[0] if rows else {}
    return {
        "contributions": float(row.get("contributions") or 0.0),
        "payments_received": float(row.get("payments_received") or 0.0),
        "welfare_balance": get_member_welfare_reserve_balance(member_id),
        "last_contribution_date": row.get("last_contribution_date"),
    }


def get_welfare_fund_totals() -> dict[str, float]:
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT
            COALESCE(SUM(CASE WHEN (t.category = 'WELFARE_CONTRIBUTION'
                              OR (t.category = 'REVERSAL' AND original.category = 'WELFARE_CONTRIBUTION'))
                              AND e.account_code = 'WELFARE_FUND' THEN e.credit - e.debit ELSE 0 END), 0) AS total_contributions,
            COALESCE(SUM(CASE WHEN (t.category = 'WELFARE_PAYMENT'
                              OR (t.category = 'REVERSAL' AND original.category = 'WELFARE_PAYMENT'))
                              AND e.account_code = 'WELFARE_FUND' THEN e.debit - e.credit ELSE 0 END), 0) AS total_paid
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED';
        """,
        fetch=True,
    ) or []
    row = rows[0] if rows else {}
    return {
        "total_contributions": float(row.get("total_contributions") or 0.0),
        "total_paid": float(row.get("total_paid") or 0.0),
        "balance": float(max(_account_balance("WELFARE_FUND"), Decimal("0.00"))),
    }


@st.cache_data(ttl=60)
def get_admin_dashboard_balances() -> dict[str, float]:
    """Return dashboard cash/receivable/liability amounts from approved journal entries."""
    ensure_accounting_schema()
    disbursed_rows = execute_query(
        """
        SELECT COALESCE(SUM(e.debit - e.credit), 0) AS total_disbursed
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'LOAN_DISBURSEMENT'
               OR (t.category = 'REVERSAL' AND original.category = 'LOAN_DISBURSEMENT'))
          AND e.account_code = 'LOAN_PRINCIPAL_RECEIVABLE';
        """,
        fetch=True,
    ) or []
    return {
        "cash": float(max(-_account_balance("CASH"), Decimal("0.00"))),
        "savings_pool": get_effective_pool_savings_balance(),
        "welfare_pool": get_effective_pool_welfare_balance(),
        "admin_reserve": float(max(_account_balance("ADMIN_FUND"), Decimal("0"))),
        "interest_collected": float(
            get_verified_cash_interest()
        ),
        "outstanding_principal": float(max(-_account_balance("LOAN_PRINCIPAL_RECEIVABLE"), Decimal("0"))),
        "outstanding_interest": float(max(-_account_balance("LOAN_INTEREST_RECEIVABLE"), Decimal("0"))),
        "total_disbursed": float(disbursed_rows[0].get("total_disbursed") or 0.0),
    }


@st.cache_data(ttl=60)
def get_subscription_arrears(
    as_of: date,
    *,
    expected_per_month: float = 20000.0,
) -> dict[str, float]:
    """Calculate arrears from approved ledger receipts using the configured monthly target."""
    members = _all_members()
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT e.member_id, COALESCE(t.cycle_on, original.cycle_on) AS cycle_on,
               COALESCE(SUM(e.credit - e.debit), 0) AS paid
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
          AND COALESCE(t.cycle_on, original.cycle_on) >= %s
          AND COALESCE(t.cycle_on, original.cycle_on) < %s
        GROUP BY e.member_id, COALESCE(t.cycle_on, original.cycle_on);
        """,
        params=(date(as_of.year, 1, 1), date(as_of.year + 1, 1, 1)),
        fetch=True,
    ) or []
    paid_by_member: dict[str, Decimal] = {}
    for row in rows:
        member_id = str(row["member_id"]).strip().upper()
        paid_by_member[member_id] = paid_by_member.get(member_id, Decimal("0.00")) + Decimal(str(row["paid"] or 0))
    legacy_rows = _get_unposted_legacy_subscription_rows(
        cycle_start=date(as_of.year, 1, 1),
        cycle_end=date(as_of.year + 1, 1, 1),
    )
    for row in legacy_rows:
        member_id = str(row.get("member_id") or "").strip().upper()
        paid_by_member[member_id] = paid_by_member.get(member_id, Decimal("0.00")) + _money(
            row.get("amount_paid") or 0
        )
    due_per_member = _money(expected_per_month) * as_of.month
    total_arrears = sum(
        (
            max(
                due_per_member
                - paid_by_member.get(str(member["member_id"]).strip().upper(), Decimal("0.00")),
                Decimal("0.00"),
            )
            for member in members
        ),
        Decimal("0.00"),
    )
    return {
        "total_arrears": float(total_arrears),
        "expected_per_month": float(_money(expected_per_month)),
        "months_elapsed": as_of.month,
    }


@st.cache_data(ttl=60)
def get_member_activity_summary(
    as_of: date,
    *,
    expected_per_month: float = 20000.0,
) -> dict[str, Any]:
    """Summarize membership activity using approved subscription receipts only."""
    members = execute_query(
        "SELECT full_name, status, member_id FROM members ORDER BY full_name;",
        fetch=True,
    ) or []
    ensure_accounting_schema()
    paid_rows = execute_query(
        """
        SELECT e.member_id, COALESCE(SUM(e.credit - e.debit), 0) AS paid
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
          AND COALESCE(t.cycle_on, original.cycle_on) >= %s
          AND COALESCE(t.cycle_on, original.cycle_on) < %s
        GROUP BY e.member_id;
        """,
        params=(date(as_of.year, 1, 1), date(as_of.year + 1, 1, 1)),
        fetch=True,
    ) or []
    paid_by_member: dict[str, Decimal] = {}
    for row in paid_rows:
        member_id = str(row.get("member_id") or "").strip().upper()
        if member_id:
            paid_by_member[member_id] = paid_by_member.get(member_id, Decimal("0.00")) + Decimal(
                str(row.get("paid") or 0)
            )
    legacy_rows = _get_unposted_legacy_subscription_rows(
        cycle_start=date(as_of.year, 1, 1),
        cycle_end=date(as_of.year + 1, 1, 1),
    )
    for row in legacy_rows:
        member_id = str(row.get("member_id") or "").strip().upper()
        if member_id:
            paid_by_member[member_id] = paid_by_member.get(member_id, Decimal("0.00")) + _money(
                row.get("amount_paid") or 0
            )
    due = _money(expected_per_month) * as_of.month
    active_statuses = {
        "active", "probationary", "probational", "partial", "partial member",
        "full", "full member",
    }
    inactive_statuses = {"inactive", "suspended", "terminated"}
    pending_statuses = {"pending", "due", "open", "incomplete", "rejected"}
    active_names: list[str] = []
    inactive_names: list[str] = []
    pending_count = 0
    for member in members:
        status = str(member.get("status") or "pending").strip().lower().replace("_", " ").replace("-", " ")
        member_id = str(member.get("member_id") or "").strip().upper()
        arrears = max(due - paid_by_member.get(member_id, Decimal("0.00")), Decimal("0.00"))
        name = str(member.get("full_name") or "")
        if status in inactive_statuses or (
            status in active_statuses and arrears >= Decimal(str(INACTIVE_ARREARS_THRESHOLD))
        ):
            inactive_names.append(name)
        elif status in active_statuses:
            active_names.append(name)
        if status in pending_statuses:
            pending_count += 1
    return {
        "total_members": len(members),
        "active_members": len(active_names),
        "inactive_members": len(inactive_names),
        "pending_members": pending_count,
        "active_member_names": active_names,
        "inactive_member_names": inactive_names,
    }


def get_member_subscription_arrears(
    member_id: str,
    as_of: date,
    *,
    expected_per_month: float = 20000.0,
) -> float:
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT COALESCE(SUM(e.credit - e.debit), 0) AS paid
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
          AND UPPER(BTRIM(e.member_id::text)) = UPPER(BTRIM(%s))
          AND COALESCE(t.cycle_on, original.cycle_on) >= %s
          AND COALESCE(t.cycle_on, original.cycle_on) < %s;
        """,
        params=(member_id, date(as_of.year, 1, 1), date(as_of.year + 1, 1, 1)),
        fetch=True,
    ) or []
    paid = Decimal(str(rows[0].get("paid") or 0)) if rows else Decimal("0.00")
    paid += sum(
        (
            _money(row.get("amount_paid") or 0)
            for row in _get_unposted_legacy_subscription_rows(
                member_id=member_id,
                cycle_start=date(as_of.year, 1, 1),
                cycle_end=date(as_of.year + 1, 1, 1),
            )
        ),
        Decimal("0.00"),
    )
    due = _money(expected_per_month) * as_of.month
    return float(max(due - paid, Decimal("0.00")))


def get_effective_member_balance(member_id: str) -> float:
    return get_member_balances(member_id)["total_balance"]


def get_member_welfare_reserve_balance(member_id: str) -> float:
    return get_member_balances(member_id)["welfare_balance"]


def get_member_savings_balance(member_id: str) -> float:
    return get_member_balances(member_id)["savings_balance"]


def get_effective_pool_balance() -> float:
    legacy_allocations = _get_legacy_subscription_fund_allocations()
    return float(
        max(
            _account_balance("MEMBER_SAVINGS_LIABILITY")
            + _account_balance("MEMBER_WELFARE_LIABILITY")
            + _account_balance("WELFARE_FUND"),
            Decimal("0"),
        )
        + legacy_allocations["savings"]
        + legacy_allocations["welfare"]
    )


def get_effective_pool_savings_balance() -> float:
    legacy_allocations = _get_legacy_subscription_fund_allocations()
    return float(
        max(_account_balance("MEMBER_SAVINGS_LIABILITY"), Decimal("0"))
        + legacy_allocations["savings"]
    )


def get_effective_pool_welfare_balance() -> float:
    legacy_allocations = _get_legacy_subscription_fund_allocations()
    return float(
        max(
            _account_balance("MEMBER_WELFARE_LIABILITY")
            + _account_balance("WELFARE_FUND"),
            Decimal("0"),
        )
        + legacy_allocations["welfare"]
    )


def get_verified_cash_interest(
    cycle_start: date | datetime | None = None,
    cycle_end: date | datetime | None = None,
    *,
    by_member: bool = False,
) -> float | dict[str, float]:
    """Return approved interest receipts from repayments, excluding accrued interest."""
    ensure_accounting_schema()
    predicates = [
        "t.status = 'APPROVED'",
        "(t.category = 'LOAN_REPAYMENT' OR "
        "(t.category = 'REVERSAL' AND original.category = 'LOAN_REPAYMENT'))",
        "e.account_code = 'LOAN_INTEREST_RECEIVABLE'",
    ]
    params: list[Any] = []
    if cycle_start is not None:
        predicates.append("t.approved_at >= %s")
        params.append(datetime.combine(cycle_start.date() if isinstance(cycle_start, datetime) else cycle_start, time.min))
    if cycle_end is not None:
        end_day = cycle_end.date() if isinstance(cycle_end, datetime) else cycle_end
        predicates.append("t.approved_at < %s")
        params.append(datetime.combine(end_day + timedelta(days=1), time.min))
    select = "e.member_id, " if by_member else ""
    group = "GROUP BY e.member_id" if by_member else ""
    rows = execute_query(
        f"""
        SELECT {select}COALESCE(SUM(e.credit - e.debit), 0) AS interest_collected
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE {" AND ".join(predicates)}
        {group};
        """,
        params=tuple(params),
        fetch=True,
    ) or []
    if by_member:
        return {
            str(row["member_id"]): float(row["interest_collected"] or 0)
            for row in rows
            if row.get("member_id") is not None
        }
    return float(rows[0]["interest_collected"] or 0) if rows else 0.0


def _eligible_members() -> list[dict[str, Any]]:
    excluded_statuses = {"probationary", "probational", "probation", "probation member"}
    return [
        member for member in _all_members()
        if str(member.get("status") or "").strip().lower() not in excluded_statuses
    ]


def _all_members() -> list[dict[str, Any]]:
    return execute_query(
        "SELECT member_id, full_name, status FROM members ORDER BY member_id;",
        fetch=True,
    ) or []


def _daily_average_savings_batch(
    member_ids: list[str],
    cycle_start: date,
    cycle_end_exclusive: date,
) -> dict[str, Decimal]:
    if not member_ids:
        return {}
    rows = execute_query(
        """
        SELECT e.member_id, t.approved_at::date AS effective_date,
               COALESCE(SUM(e.credit - e.debit), 0) AS delta
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        WHERE t.status = 'APPROVED'
          AND e.account_code = 'MEMBER_SAVINGS_LIABILITY'
          AND e.member_id = ANY(%s) AND t.approved_at < %s
        GROUP BY e.member_id, t.approved_at::date
        ORDER BY e.member_id, effective_date;
        """,
        params=(member_ids, datetime.combine(cycle_end_exclusive, time.min)),
        fetch=True,
    ) or []
    changes: dict[str, dict[date, Decimal]] = {}
    for row in rows:
        changes.setdefault(str(row["member_id"]), {})[row["effective_date"]] = Decimal(str(row["delta"] or 0))
    days = (cycle_end_exclusive - cycle_start).days
    if days <= 0:
        return {member_id: Decimal("0.00") for member_id in member_ids}
    averages: dict[str, Decimal] = {}
    for member_id in member_ids:
        balance = Decimal("0.00")
        cycle_changes: list[tuple[date, Decimal]] = []
        for event_date, delta in changes.get(member_id, {}).items():
            if event_date < cycle_start:
                balance += delta
            else:
                cycle_changes.append((event_date, delta))
        weighted_total = Decimal("0.00")
        cursor = cycle_start
        for event_date, delta in sorted(cycle_changes):
            weighted_total += max(balance, Decimal("0.00")) * (event_date - cursor).days
            balance += delta
            cursor = event_date
        weighted_total += max(balance, Decimal("0.00")) * (cycle_end_exclusive - cursor).days
        averages[member_id] = weighted_total / days
    return averages


def calculate_cycle_payouts(cycle_start: date, cycle_end: date) -> dict[str, Any]:
    """Calculate cash-safe, full-roster sharing payouts for an inclusive cycle."""
    if cycle_end < cycle_start:
        raise ValueError("Cycle end must not precede cycle start.")
    ensure_accounting_schema()
    cycle_reference = f"sharing-cycle:{cycle_start.isoformat()}:{cycle_end.isoformat()}"
    posted_rows = execute_query(
        "SELECT metadata FROM accounting_transactions "
        "WHERE category = 'SHARING_ALLOCATION' AND reference = %s AND status = 'APPROVED';",
        params=(cycle_reference,),
        fetch=True,
    ) or []
    if posted_rows:
        snapshot = posted_rows[0]["metadata"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        if "payouts" not in snapshot:
            raise ValueError("The posted sharing cycle has no payout snapshot; accountant reconciliation is required.")
        return {
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "eligible_count": int(snapshot["eligible_count"]),
            "interest_collected": float(snapshot["interest_collected"]),
            "borrower_rebate_pool": float(snapshot["borrower_rebate_pool"]),
            "admin_reserve": float(snapshot["admin_reserve"]),
            "member_sharing_pool": float(snapshot["member_sharing_pool"]),
            "equal_pool": float(snapshot["equal_pool"]),
            "weighted_pool": float(snapshot["weighted_pool"]),
            "total_savings_weight": float(snapshot["total_savings_weight"]),
            "payouts": snapshot["payouts"],
            "distributed_borrower_rebate": float(snapshot["distributed_borrower_rebate"]),
            "distributed_equal_pool": float(snapshot["distributed_equal_pool"]),
            "distributed_weighted_pool": float(snapshot["distributed_weighted_pool"]),
            "unallocated_rounding": float(snapshot["unallocated_rounding"]),
        }
    eligible = _eligible_members()
    eligible_ids = [str(row["member_id"]) for row in eligible]
    cycle_interest_by_member = get_verified_cash_interest(cycle_start, cycle_end, by_member=True)
    if not isinstance(cycle_interest_by_member, dict):
        raise TypeError("Member-level verified interest must be returned as a mapping.")
    collected_interest = float(get_verified_cash_interest(cycle_start, cycle_end))

    total_interest = _money(collected_interest)
    borrower_pool = _money(total_interest * Decimal("0.30"))
    admin_reserve = _money(total_interest * Decimal("0.10"))
    member_pool = total_interest - borrower_pool - admin_reserve
    equal_pool = _money(member_pool * Decimal("0.50"))
    weighted_pool = member_pool - equal_pool
    savings_weights = _daily_average_savings_batch(
        eligible_ids,
        cycle_start,
        cycle_end + timedelta(days=1),
    )
    total_savings_weight = sum(savings_weights.values(), Decimal("0.00"))
    payouts: list[dict[str, Any]] = []
    count = len(eligible_ids)
    interest_recipient_ids = sorted(
        member_id for member_id, value in cycle_interest_by_member.items()
        if Decimal(str(value)) > 0
    )
    borrower_ids = [member_id for member_id in interest_recipient_ids if member_id not in eligible_ids]
    members_by_id = {str(member["member_id"]): member for member in eligible}
    all_recipient_ids = eligible_ids + borrower_ids
    member_balances = get_member_balances_batch(all_recipient_ids, as_of=cycle_end)
    borrower_weights = {
        member_id: Decimal(str(cycle_interest_by_member[member_id]))
        for member_id in interest_recipient_ids
    }
    borrower_shares = _allocate_proportionally(borrower_pool, borrower_weights)
    equal_shares = _allocate_proportionally(
        equal_pool,
        {member_id: Decimal("1") for member_id in eligible_ids},
    )
    weighted_shares = _allocate_proportionally(
        weighted_pool,
        {
            member_id: savings_weights[member_id] if total_savings_weight > 0 else Decimal("1")
            for member_id in eligible_ids
        },
    )

    for member_id in all_recipient_ids:
        member = members_by_id.get(member_id, {})
        borrower_interest = Decimal(str(cycle_interest_by_member.get(member_id, 0.0)))
        borrower_share = borrower_shares.get(member_id, Decimal("0.00"))
        equal_share = equal_shares.get(member_id, Decimal("0.00"))
        weighted_share = weighted_shares.get(member_id, Decimal("0.00"))
        savings_weight = savings_weights.get(member_id, Decimal("0.00"))
        dividend = borrower_share + equal_share + weighted_share
        savings_balance = member_balances.get(member_id, {}).get("total_balance", 0.0)
        withdrawable_savings = min(
            member_balances.get(member_id, {}).get("savings_balance", 0.0),
            max(savings_balance - WELFARE_RESERVE_LIMIT, 0.0),
        )
        payouts.append(
            {
                "member_id": member_id,
                "full_name": member.get("full_name") or "",
                "borrower_interest_paid": float(borrower_interest),
                "borrower_rebate": float(borrower_share),
                "equal_share": float(equal_share),
                "savings_weight": float(savings_weight),
                "weighted_share": float(weighted_share),
                "dividend_share": float(dividend),
                "savings_balance": float(savings_balance),
                "withdrawable_savings": round(withdrawable_savings, 2),
                "net_payout": round(withdrawable_savings + float(dividend), 2),
            }
        )
    distributed_borrower = sum(borrower_shares.values(), Decimal("0.00"))
    distributed_equal = sum(equal_shares.values(), Decimal("0.00"))
    distributed_weighted = sum(weighted_shares.values(), Decimal("0.00"))

    return {
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "eligible_count": count,
        "interest_collected": collected_interest,
        "borrower_rebate_pool": borrower_pool,
        "admin_reserve": admin_reserve,
        "member_sharing_pool": member_pool,
        "equal_pool": equal_pool,
        "weighted_pool": weighted_pool,
        "total_savings_weight": float(total_savings_weight),
        "payouts": payouts,
        "distributed_borrower_rebate": float(distributed_borrower),
        "distributed_equal_pool": float(distributed_equal),
        "distributed_weighted_pool": float(distributed_weighted),
        "unallocated_rounding": round(
            float(Decimal(str(borrower_pool)) + Decimal(str(equal_pool)) + Decimal(str(weighted_pool))
            - distributed_borrower - distributed_equal - distributed_weighted),
            2,
        ),
    }


def post_cycle_allocations(
    cycle_start: date,
    cycle_end: date,
    *,
    approved_by: str,
) -> str:
    """Post the approved cycle's complete interest allocation once, including admin reserve."""
    reference = f"sharing-cycle:{cycle_start.isoformat()}:{cycle_end.isoformat()}"
    ensure_accounting_schema()
    existing = execute_query(
        "SELECT transaction_id FROM accounting_transactions "
        "WHERE category = 'SHARING_ALLOCATION' AND reference = %s AND status = 'APPROVED';",
        params=(reference,),
        fetch=True,
    ) or []
    if existing:
        return str(existing[0]["transaction_id"])
    result = calculate_cycle_payouts(cycle_start, cycle_end)
    collected = _money(result["interest_collected"])
    if collected <= 0:
        return ""
    if result["eligible_count"] <= 0:
        raise ValueError("No eligible members are registered for this cycle.")
    entries: list[dict[str, Any]] = []
    allocations = _money(result["admin_reserve"])
    if allocations:
        entries.append({"account_code": "INTEREST_DISTRIBUTION_EXPENSE", "debit": allocations, "credit": 0})
        entries.append({"account_code": "ADMIN_FUND", "debit": 0, "credit": allocations})
    for item in result["payouts"]:
        amount = _money(item["dividend_share"])
        if amount <= 0:
            continue
        entries.append({"account_code": "INTEREST_DISTRIBUTION_EXPENSE", "debit": amount, "credit": 0})
        entries.append(
            {"account_code": "MEMBER_DIVIDEND_PAYABLE", "member_id": item["member_id"], "debit": 0, "credit": amount}
        )
    return record_transaction(
        reference=reference,
        category="SHARING_ALLOCATION",
        approver_id=approved_by,
        entries=entries,
        cycle_on=cycle_start,
        metadata={
            "cycle_end": cycle_end,
            "interest_collected": collected,
            "eligible_count": result["eligible_count"],
            "rounding_residual": result["unallocated_rounding"],
            "borrower_rebate_pool": result["borrower_rebate_pool"],
            "admin_reserve": result["admin_reserve"],
            "member_sharing_pool": result["member_sharing_pool"],
            "equal_pool": result["equal_pool"],
            "weighted_pool": result["weighted_pool"],
            "total_savings_weight": result["total_savings_weight"],
            "payouts": result["payouts"],
            "distributed_borrower_rebate": result["distributed_borrower_rebate"],
            "distributed_equal_pool": result["distributed_equal_pool"],
            "distributed_weighted_pool": result["distributed_weighted_pool"],
            "unallocated_rounding": result["unallocated_rounding"],
        },
    )


def post_member_sharing_payout(
    *,
    member_id: str,
    cycle_start: date,
    cycle_end: date,
    approved_by: str,
    requested_amount: float,
) -> str:
    """Pay a closed-cycle payout from member savings and dividend liabilities."""
    ensure_accounting_schema()
    payout_reference = f"sharing-payout:{cycle_start.isoformat()}:{cycle_end.isoformat()}:{member_id}"
    existing_payout = execute_query(
        "SELECT transaction_id FROM accounting_transactions "
        "WHERE category = 'SHARING_PAYOUT' AND reference = %s AND status = 'APPROVED';",
        params=(payout_reference,),
        fetch=True,
    ) or []
    if existing_payout:
        return str(existing_payout[0]["transaction_id"])

    allocation_reference = f"sharing-cycle:{cycle_start.isoformat()}:{cycle_end.isoformat()}"
    allocation_rows = execute_query(
        "SELECT transaction_id FROM accounting_transactions "
        "WHERE category = 'SHARING_ALLOCATION' AND reference = %s AND status = 'APPROVED';",
        params=(allocation_reference,),
        fetch=True,
    ) or []
    if not allocation_rows:
        post_cycle_allocations(cycle_start, cycle_end, approved_by=approved_by)

    cycle = calculate_cycle_payouts(cycle_start, cycle_end)
    payout = next((row for row in cycle["payouts"] if row["member_id"] == member_id), None)
    if payout is None or payout["net_payout"] <= 0:
        raise ValueError("No payout is available for this member in the selected cycle.")
    if _money(requested_amount) != _money(payout["net_payout"]):
        raise ValueError("The requested amount does not match the approved cycle payout.")
    balances = get_member_balances(member_id)
    total_balance = _money(balances["total_balance"])
    reserve_from_savings = max(
        Decimal("0.00"),
        _money(WELFARE_RESERVE_LIMIT) - _money(balances["welfare_balance"]),
    )
    savings_amount = _money(payout["withdrawable_savings"])
    if savings_amount > _money(balances["savings_balance"]) - reserve_from_savings:
        raise InsufficientFundsError("The member's savings reserve cannot be withdrawn.")
    dividend_amount = _money(payout["dividend_share"])
    total = savings_amount + dividend_amount
    cash_available = max(-_account_balance("CASH"), Decimal("0.00"))
    if cash_available < total:
        raise InsufficientFundsError("The verified cash balance is insufficient to settle this sharing payout.")
    payable = _account_balance("MEMBER_DIVIDEND_PAYABLE", member_id=member_id)
    if payable < dividend_amount:
        raise InsufficientFundsError("The member's approved dividend allocation has not been posted.")

    entries: list[dict[str, Any]] = []
    if savings_amount:
        entries.append(
            {"account_code": "MEMBER_SAVINGS_LIABILITY", "member_id": member_id, "debit": savings_amount, "credit": 0}
        )
    if dividend_amount:
        entries.append(
            {"account_code": "MEMBER_DIVIDEND_PAYABLE", "member_id": member_id, "debit": dividend_amount, "credit": 0}
        )
    entries.append({"account_code": "CASH", "member_id": member_id, "debit": 0, "credit": total})
    return record_transaction(
        reference=payout_reference,
        category="SHARING_PAYOUT",
        approver_id=approved_by,
        member_id=member_id,
        entries=entries,
        cycle_on=cycle_start,
        metadata={"cycle_end": cycle_end, "savings_withdrawn": str(savings_amount), "dividend_paid": str(dividend_amount)},
    )


def get_subscription_history(
    member_id: str | None = None,
    *,
    cycle_start: date | None = None,
    cycle_end: date | None = None,
) -> list[dict[str, Any]]:
    """Return posted subscription transactions from the approved ledger."""
    ensure_accounting_schema()
    params: list[Any] = []
    predicates = [
        "(t.category = 'SUBSCRIPTION_RECEIPT' OR "
        "(t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))",
        "t.status = 'APPROVED'",
        "e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')",
    ]
    if member_id:
        predicates.append("UPPER(BTRIM(e.member_id::text)) = UPPER(BTRIM(%s))")
        params.append(member_id)
    if cycle_start:
        predicates.append("COALESCE(t.cycle_on, original.cycle_on) >= %s")
        params.append(cycle_start)
    if cycle_end:
        predicates.append("COALESCE(t.cycle_on, original.cycle_on) < %s")
        params.append(cycle_end)
    ledger_rows = execute_query(
        f"""
        SELECT e.member_id, m.full_name, COALESCE(t.cycle_on, original.cycle_on) AS billing_month,
               SUM(e.credit - e.debit) AS amount_paid, t.status, t.reference, t.approved_at,
               t.category
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        LEFT JOIN members m ON m.member_id::text = e.member_id
        WHERE {" AND ".join(predicates)}
        GROUP BY e.member_id, m.full_name, COALESCE(t.cycle_on, original.cycle_on),
                 t.status, t.reference, t.approved_at, t.category
        ORDER BY t.approved_at DESC;
        """,
        params=tuple(params),
        fetch=True,
    ) or []
    legacy_rows = _get_unposted_legacy_subscription_rows(
        member_id=member_id,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
    )
    combined = ledger_rows + legacy_rows
    combined.sort(key=lambda row: str(row.get("approved_at") or ""), reverse=True)
    return combined


def get_subscription_summary(year: int) -> dict[str, float]:
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT e.member_id, COALESCE(SUM(e.credit - e.debit), 0) AS member_total
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
          AND COALESCE(t.cycle_on, original.cycle_on) >= %s
          AND COALESCE(t.cycle_on, original.cycle_on) < %s
        GROUP BY e.member_id;
        """,
        params=(date(year, 1, 1), date(year + 1, 1, 1)),
        fetch=True,
    ) or []
    member_totals = {
        str(row["member_id"]).strip().upper(): Decimal(str(row["member_total"] or 0))
        for row in rows
    }
    for row in _get_unposted_legacy_subscription_rows(
        cycle_start=date(year, 1, 1),
        cycle_end=date(year + 1, 1, 1),
    ):
        key = str(row.get("member_id") or "").strip().upper()
        member_totals[key] = member_totals.get(key, Decimal("0.00")) + _money(row.get("amount_paid") or 0)
    return {
        "members_with_payments": float(sum(total > 0 for total in member_totals.values())),
        "total_paid": float(sum(member_totals.values(), Decimal("0.00"))),
    }


def get_subscription_member_count() -> int:
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT e.member_id, COALESCE(SUM(e.credit - e.debit), 0) AS member_total
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
        GROUP BY e.member_id;
        """,
        fetch=True,
    ) or []
    member_totals = {
        str(row["member_id"]).strip().upper(): Decimal(str(row["member_total"] or 0))
        for row in rows
    }
    for row in _get_unposted_legacy_subscription_rows():
        key = str(row.get("member_id") or "").strip().upper()
        member_totals[key] = member_totals.get(key, Decimal("0.00")) + _money(row.get("amount_paid") or 0)
    return sum(total > 0 for total in member_totals.values())


def get_subscription_totals(member_id: str, year: int | None = None) -> dict[str, float]:
    ensure_accounting_schema()
    predicates = [
        "t.status = 'APPROVED'",
        "(t.category = 'SUBSCRIPTION_RECEIPT' OR "
        "(t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))",
        "e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')",
        "UPPER(BTRIM(e.member_id::text)) = UPPER(BTRIM(%s))",
    ]
    params: list[Any] = [member_id]
    if year is not None:
        predicates.extend(["COALESCE(t.cycle_on, original.cycle_on) >= %s", "COALESCE(t.cycle_on, original.cycle_on) < %s"])
        params.extend([date(year, 1, 1), date(year + 1, 1, 1)])
    rows = execute_query(
        "SELECT COALESCE(SUM(month_total), 0) AS total_paid, "
        "COUNT(*) FILTER (WHERE month_total > 0 AND cycle_on IS NOT NULL) AS paid_months FROM ("
        "SELECT COALESCE(t.cycle_on, original.cycle_on) AS cycle_on, "
        "SUM(e.credit - e.debit) AS month_total "
        "FROM accounting_journal_entries e "
        "JOIN accounting_transactions t USING (transaction_id) "
        "LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of "
        f"WHERE {' AND '.join(predicates)} "
        "GROUP BY COALESCE(t.cycle_on, original.cycle_on)) monthly_totals;",
        params=tuple(params),
        fetch=True,
    ) or []
    total_paid = Decimal(str(rows[0].get("total_paid") or 0)) if rows else Decimal("0.00")
    paid_months = int(rows[0].get("paid_months") or 0) if rows else 0
    legacy_rows = _get_unposted_legacy_subscription_rows(
        member_id=member_id,
        cycle_start=date(year, 1, 1) if year is not None else None,
        cycle_end=date(year + 1, 1, 1) if year is not None else None,
    )
    legacy_amounts_by_month: dict[tuple[int, int], Decimal] = {}
    for row in legacy_rows:
        billing_month = row.get("billing_month")
        if isinstance(billing_month, datetime):
            billing_month = billing_month.date()
        if isinstance(billing_month, date):
            key = (billing_month.year, billing_month.month)
            legacy_amounts_by_month[key] = legacy_amounts_by_month.get(key, Decimal("0.00")) + _money(
                row.get("amount_paid") or 0
            )
    total_paid += sum(legacy_amounts_by_month.values(), Decimal("0.00"))
    paid_months += sum(1 for amount in legacy_amounts_by_month.values() if amount > 0)
    return {"total_paid": float(total_paid), "paid_months": float(paid_months)}


def get_member_subscription_months(
    member_id: str,
    year: int,
    through_month: int,
    *,
    expected_per_month: float = 20000.0,
) -> dict[int, dict[str, float]]:
    if not 1 <= through_month <= 12:
        raise ValueError("Month must be between 1 and 12.")
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT EXTRACT(MONTH FROM COALESCE(t.cycle_on, original.cycle_on))::integer AS month,
               COALESCE(SUM(e.credit - e.debit), 0) AS amount
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
          AND UPPER(BTRIM(e.member_id::text)) = UPPER(BTRIM(%s))
          AND COALESCE(t.cycle_on, original.cycle_on) >= %s
          AND COALESCE(t.cycle_on, original.cycle_on) < %s
        GROUP BY EXTRACT(MONTH FROM COALESCE(t.cycle_on, original.cycle_on));
        """,
        params=(member_id, date(year, 1, 1), date(year + 1, 1, 1)),
        fetch=True,
    ) or []
    paid_by_month = {int(row["month"]): float(row["amount"] or 0.0) for row in rows}
    legacy_rows = _get_unposted_legacy_subscription_rows(
        member_id=member_id,
        cycle_start=date(year, 1, 1),
        cycle_end=date(year + 1, 1, 1),
    )
    for row in legacy_rows:
        billing_month = row.get("billing_month")
        if isinstance(billing_month, datetime):
            billing_month = billing_month.date()
        if isinstance(billing_month, date):
            month = billing_month.month
            paid_by_month[month] = paid_by_month.get(month, 0.0) + float(row.get("amount_paid") or 0.0)
    monthly_target = float(_money(expected_per_month))
    return {
        month: {
            "paid": paid_by_month.get(month, 0.0),
            "expected": monthly_target,
            "arrears": max(monthly_target - paid_by_month.get(month, 0.0), 0.0),
        }
        for month in range(1, through_month + 1)
    }


def get_month_subscription_total(member_id: str, month: int, year: int) -> float:
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    ensure_accounting_schema()
    paid_rows = execute_query(
        """
        SELECT COALESCE(SUM(e.credit - e.debit), 0) AS total
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
          AND UPPER(BTRIM(e.member_id::text)) = UPPER(BTRIM(%s))
          AND COALESCE(t.cycle_on, original.cycle_on) >= %s
          AND COALESCE(t.cycle_on, original.cycle_on) < %s;
        """,
        params=(member_id, start, end),
        fetch=True,
    ) or []
    legacy_rows = _get_unposted_legacy_subscription_rows(
        member_id=member_id,
        cycle_start=start,
        cycle_end=end,
    )
    proof_rows = execute_query(
        """
        SELECT COALESCE(SUM(amount_paid), 0) AS total_pending
        FROM subscription_payment_proofs proof
        WHERE proof.member_id = %s AND proof.subscription_month = %s AND proof.subscription_year = %s
          AND COALESCE(proof.verification_status, '') NOT IN ('Rejected', 'Verified')
          AND NOT EXISTS (
              SELECT 1 FROM accounting_transactions t
              WHERE t.category = 'SUBSCRIPTION_RECEIPT'
                AND t.reference = 'subscription-proof:' || proof.proof_id::text
          );
        """,
        params=(member_id, month, year),
        fetch=True,
    ) or []
    paid = Decimal(str(paid_rows[0].get("total") or 0)) if paid_rows else Decimal("0.00")
    paid += sum((_money(row.get("amount_paid") or 0) for row in legacy_rows), Decimal("0.00"))
    pending = Decimal(str(proof_rows[0].get("total_pending") or 0)) if proof_rows else Decimal("0.00")
    return float(paid + pending)


def get_month_subscription_remaining(member_id: str, month: int, year: int) -> float:
    """Return the remaining monthly subscription allowance, including pending proofs."""
    return float(
        max(
            _money(MAX_MONTHLY_SUBSCRIPTION) - _money(get_month_subscription_total(member_id, month, year)),
            Decimal("0.00"),
        )
    )


def get_all_member_balances() -> list[dict[str, Any]]:
    """Return the complete roster with ledger-backed savings balances."""
    members = _all_members()
    balances = get_member_balances_batch([str(member["member_id"]) for member in members])
    return [
        {**member, **balances[str(member["member_id"])]}
        for member in members
    ]


def get_subscription_ledger(
    as_of: date,
    *,
    expected_per_month: float = 20000.0,
) -> list[dict[str, Any]]:
    """Build the all-member subscription ledger from approved journal transactions."""
    members = _all_members()
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT e.member_id, COALESCE(t.cycle_on, original.cycle_on) AS cycle_on,
               COALESCE(SUM(e.credit - e.debit), 0) AS amount
        FROM accounting_journal_entries e
        JOIN accounting_transactions t USING (transaction_id)
        LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of
        WHERE t.status = 'APPROVED'
          AND (t.category = 'SUBSCRIPTION_RECEIPT'
               OR (t.category = 'REVERSAL' AND original.category = 'SUBSCRIPTION_RECEIPT'))
          AND e.account_code IN ('MEMBER_SAVINGS_LIABILITY', 'MEMBER_WELFARE_LIABILITY')
        GROUP BY e.member_id, COALESCE(t.cycle_on, original.cycle_on);
        """,
        fetch=True,
    ) or []
    aggregate: dict[str, dict[str, Any]] = {}
    for row in rows:
        member_id = str(row["member_id"]).strip().upper()
        record = aggregate.setdefault(member_id, {"total_paid": Decimal("0.00"), "paid_months": set(), "year_paid": Decimal("0.00")})
        amount = Decimal(str(row["amount"] or 0))
        record["total_paid"] += amount
        billing_month = row.get("cycle_on")
        if billing_month and amount > 0:
            record["paid_months"].add((billing_month.year, billing_month.month))
            if billing_month.year == as_of.year:
                record["year_paid"] += amount

    legacy_rows = _get_unposted_legacy_subscription_rows(
        cycle_end=as_of + timedelta(days=1),
    )
    for row in legacy_rows:
        member_id = str(row.get("member_id") or "").strip().upper()
        record = aggregate.setdefault(
            member_id,
            {"total_paid": Decimal("0.00"), "paid_months": set(), "year_paid": Decimal("0.00")},
        )
        amount = _money(row.get("amount_paid") or 0)
        record["total_paid"] += amount
        billing_month = row.get("billing_month")
        if isinstance(billing_month, datetime):
            billing_month = billing_month.date()
        if isinstance(billing_month, date) and amount > 0:
            record["paid_months"].add((billing_month.year, billing_month.month))
            if billing_month.year == as_of.year:
                record["year_paid"] += amount

    expected = _money(expected_per_month) * as_of.month
    member_balances = get_member_balances_batch([str(member["member_id"]) for member in members])
    ledger: list[dict[str, Any]] = []
    for member in members:
        member_id = str(member["member_id"])
        paid = aggregate.get(member_id.strip().upper(), {})
        balances = member_balances[member_id]
        year_paid = paid.get("year_paid", Decimal("0.00"))
        ledger.append(
            {
                "member_id": member_id,
                "full_name": member.get("full_name") or "",
                "total_paid": float(paid.get("total_paid", Decimal("0.00"))),
                "net_balance": balances["total_balance"],
                "paid_months": len(paid.get("paid_months", set())),
                "arrears": float(max(expected - year_paid, Decimal("0.00"))),
            }
        )
    return ledger


@st.cache_data(ttl=60)
def get_loan_portfolio() -> dict[str, Any]:
    """Return active loan accounts and only show balances supported by the journal."""
    ensure_accounting_schema()
    rows = execute_query(
        """
        SELECT l.loan_id, l.member_id, COALESCE(m.full_name, '') AS full_name, l.status,
               COUNT(e.id) FILTER (WHERE t.transaction_id IS NOT NULL) AS ledger_entry_count,
               GREATEST(COALESCE(SUM(CASE WHEN t.transaction_id IS NOT NULL
                                              AND e.account_code = 'LOAN_PRINCIPAL_RECEIVABLE'
                                          THEN e.debit - e.credit ELSE 0 END), 0), 0) AS principal,
               GREATEST(COALESCE(SUM(CASE WHEN t.transaction_id IS NOT NULL
                                              AND e.account_code = 'LOAN_INTEREST_RECEIVABLE'
                                          THEN e.debit - e.credit ELSE 0 END), 0), 0) AS interest
        FROM loans l
        LEFT JOIN accounting_journal_entries e
          ON e.loan_id = l.loan_id
         AND e.account_code IN ('LOAN_PRINCIPAL_RECEIVABLE', 'LOAN_INTEREST_RECEIVABLE')
        LEFT JOIN accounting_transactions t
          ON t.transaction_id = e.transaction_id
         AND t.status = 'APPROVED'
        LEFT JOIN members m ON UPPER(BTRIM(m.member_id::text)) = UPPER(BTRIM(l.member_id::text))
        WHERE UPPER(BTRIM(l.status::text)) IN ('APPROVED', 'ACTIVE')
        GROUP BY l.loan_id, l.member_id, m.full_name, l.status
        ORDER BY l.loan_id DESC;
        """,
        fetch=True,
    ) or []
    loans: list[dict[str, Any]] = []
    for row in rows:
        ledger_backed = int(row.get("ledger_entry_count") or 0) > 0
        principal = float(row.get("principal") or 0) if ledger_backed else None
        interest = float(row.get("interest") or 0) if ledger_backed else None
        outstanding = principal + interest if ledger_backed else None
        loans.append(
            {
                "loan_id": row["loan_id"],
                "member_id": row["member_id"],
                "member_name": row.get("full_name") or "",
                "status": row.get("status") or "Unknown",
                "ledger_backed": ledger_backed,
                "principal": principal,
                "interest": interest,
                "outstanding": outstanding,
            }
        )
    backed_loans = [loan for loan in loans if loan["ledger_backed"]]
    return {
        "loans": loans,
        "outstanding_principal": sum(item["principal"] or 0 for item in backed_loans),
        "outstanding_interest": sum(item["interest"] or 0 for item in backed_loans),
        "outstanding_total": sum(item["outstanding"] or 0 for item in backed_loans),
        "loans_requiring_reconciliation": sum(not item["ledger_backed"] for item in loans),
    }


def record_opening_balance(
    *,
    member_id: str,
    amount: float,
    account_code: str,
    reference: str,
    approved_by: str,
    category: str = "OPENING_BALANCE",
    loan_id: int | None = None,
    notes: str,
) -> str:
    """Record an externally reconciled opening balance without guessing legacy cash."""
    if account_code not in {
        "MEMBER_SAVINGS_LIABILITY",
        "MEMBER_WELFARE_LIABILITY",
        "LOAN_PRINCIPAL_RECEIVABLE",
        "LOAN_INTEREST_RECEIVABLE",
        "WELFARE_DEBT_RECEIVABLE",
    }:
        raise ValueError("Unsupported opening balance account.")
    value = _money(amount)
    if value <= 0:
        raise ValueError("Opening balance must be positive.")
    is_receivable = account_code in {"LOAN_PRINCIPAL_RECEIVABLE", "LOAN_INTEREST_RECEIVABLE", "WELFARE_DEBT_RECEIVABLE"}
    return record_transaction(
        reference=reference,
        category=category,
        approver_id=approved_by,
        member_id=member_id,
        loan_id=loan_id,
        entries=[
            {
                "account_code": account_code,
                "member_id": member_id,
                "loan_id": loan_id,
                "debit": value if is_receivable else 0,
                "credit": value if not is_receivable else 0,
            },
            {
                "account_code": "OPENING_BALANCE_CLEARING",
                "debit": 0 if is_receivable else value,
                "credit": value if is_receivable else 0,
            },
        ],
        metadata={"notes": notes, "reconciled_opening_balance": True},
    )


def ensure_member_balance_adjustments_table() -> None:
    """Compatibility no-op: balances now come only from the accounting journal."""
    ensure_accounting_schema()
