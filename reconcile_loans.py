"""
Loan Ledger Reconciliation Script (Type-Safe Version)
Automatically generates missing opening journal entries 
for loans present in the 'loans' table using 'loan_id' and 'outstanding_balance'.
"""

import sys
import os

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.connection import execute_query

def run_reconciliation():
    print("Starting loan ledger reconciliation...")

    # 1. Find loans missing ledger disbursement records
    unreconciled_query = """
        SELECT l.loan_id, l.member_id, l.outstanding_balance, l.applied_date
        FROM loans l
        WHERE NOT EXISTS (
            SELECT 1 FROM ledger_transactions t 
            WHERE t.member_id = l.member_id 
              AND (t.transaction_type ILIKE '%LOAN%' OR t.transaction_type ILIKE '%DISBURSEMENT%')
        );
    """
    
    try:
        loans = execute_query(unreconciled_query, fetch=True) or []
    except Exception as e:
        print(f"Error fetching unreconciled loans: {e}")
        return

    if not loans:
        print("All loans are already reconciled with the ledger! No action needed.")
        return

    print(f"Found {len(loans)} unreconciled loan(s). Creating ledger entries...")

    success_count = 0
    for loan in loans:
        # Type-safe extraction to satisfy Pylance
        raw_loan_id = loan.get("loan_id")
        if raw_loan_id is None:
            continue
        loan_id = int(raw_loan_id)

        member_id = loan.get("member_id")
        if not member_id:
            continue

        raw_balance = loan.get("outstanding_balance")
        balance = float(raw_balance) if raw_balance is not None else 0.0
        
        applied_date = loan.get("applied_date")
        
        if balance <= 0:
            print(f"Skipping Loan #{loan_id} (Member: {member_id}): Balance is 0 or invalid.")
            continue

        insert_query = """
            INSERT INTO ledger_transactions (
                member_id, 
                transaction_type, 
                amount, 
                description, 
                created_at
            ) VALUES (%s, %s, %s, %s, %s);
        """
        
        params = (
            str(member_id),
            "LOAN_DISBURSEMENT",
            balance,
            f"Automated reconciliation: Opening balance for Loan #{loan_id}",
            applied_date
        )

        try:
            execute_query(insert_query, params=params, fetch=False)
            print(f" Successfully reconciled Loan #{loan_id} for Member {member_id} (Balance: {balance:,.2f})")
            success_count += 1
        except Exception as ex:
            print(f" Failed to reconcile Loan #{loan_id}: {ex}")

    print(f"\nReconciliation complete! Successfully synchronized {success_count} of {len(loans)} loans.")

if __name__ == "__main__":
    run_reconciliation() 