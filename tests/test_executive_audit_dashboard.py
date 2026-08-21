from datetime import datetime

from src.utils import audit


def test_build_audit_dashboard_summary_counts_key_events(monkeypatch):
    rows = [
        {"entity_type": "member", "entity_id": "M-001", "action": "Member registered", "actor_name": "Alice", "actor_role": "Secretary", "details": "New registration", "previous_value": None, "new_value": "Pending", "created_at": datetime.utcnow()},
        {"entity_type": "loan", "entity_id": "LN-100", "action": "Loan approved", "actor_name": "Bob", "actor_role": "Treasurer", "details": "Approved", "previous_value": "Pending", "new_value": "Approved", "created_at": datetime.utcnow()},
        {"entity_type": "authentication", "entity_id": "M-001", "action": "Login failed", "actor_name": "Alice", "actor_role": "Member", "details": "Failed login", "previous_value": None, "new_value": None, "created_at": datetime.utcnow()},
        {"entity_type": "member", "entity_id": "M-002", "action": "Account suspended", "actor_name": "System", "actor_role": "System", "details": "Suspended", "previous_value": "Active", "new_value": "Suspended", "created_at": datetime.utcnow()},
        {"entity_type": "system", "entity_id": "SYS-1", "action": "Error", "actor_name": "System", "actor_role": "System", "details": "Database connection error", "previous_value": None, "new_value": None, "created_at": datetime.utcnow()},
    ]

    monkeypatch.setattr(audit, "fetch_recent_audit_events", lambda limit=200: rows[:limit])

    summary = audit.build_audit_dashboard_summary(limit=10)

    assert summary["today_activities"] == 5
    assert summary["new_member_registrations"] == 1
    assert summary["loans_approved_today"] == 1
    assert summary["failed_login_attempts"] == 1
    assert summary["suspended_accounts"] == 1
    assert summary["system_errors"] == 1


def test_enrich_audit_event_uses_member_lookup(monkeypatch):
    monkeypatch.setattr(
        audit,
        "fetch_recent_audit_events",
        lambda limit=200: [{
            "entity_type": "member",
            "entity_id": "M-007",
            "action": "Member updated",
            "actor_name": "Chairperson",
            "actor_role": "Chairperson",
            "details": "Profile updated",
            "previous_value": "Pending",
            "new_value": "Active",
            "created_at": datetime.utcnow(),
        }],
    )

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM members" in query:
            return [{"member_id": "M-007", "full_name": "Jane Doe"}]
        return []

    monkeypatch.setattr(audit, "execute_query", fake_execute_query)

    events = audit.fetch_enriched_audit_events(limit=5)

    assert events[0]["member_name"] == "Jane Doe"
    assert events[0]["member_number"] == "M-007"
    assert events[0]["status"] == "Updated"
