import src.views.welfare_support as ws
queries = []

def fake(query, params=None, fetch=False):
    queries.append((query, params, fetch))
    if 'SELECT' in query.upper() and 'member_welfare_accounts' in query.lower():
        return []
    return None

ws.execute_query = fake
ws.record_audit_event = lambda **kwargs: None
ws._create_notification = lambda *args, **kwargs: None

result = ws.set_member_welfare_account_status('M-002', 'Suspended', 'Chairperson', 'Chairperson', 'Rule violation')
print('RESULT', result)
updates = [q for q, _, _ in queries if 'UPDATE member_welfare_accounts' in q.upper()]
print('UPDATE_COUNT', len(updates))
for q in updates:
    print(q)
