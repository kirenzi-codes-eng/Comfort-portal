# Error Handling Quick Reference

## TL;DR - One-Minute Guide

### For User-Facing Database Operations

```python
from src.utils.error_handler import execute_with_error_handling

# Your database operation
def load_data():
    return execute_query("SELECT * FROM table", fetch=True)

# Wrap with error handling (shows spinner + retry button)
data = execute_with_error_handling(load_data, "Loading data") or []

# Use the data
if data:
    st.write(data)
```

**User sees on failure:**

- Loading spinner during 3 automatic retries
- If still fails: Professional error message (🌐, ⚠️, or ❌)
- "Try Again" button to retry without page refresh
- **Never sees:** Technical errors, SQL, stack traces, configs

---

## Available Functions

| Function                        | Best For                   | Includes                          |
| ------------------------------- | -------------------------- | --------------------------------- |
| `execute_with_error_handling()` | User-facing operations     | Spinner + UI error + retry button |
| `execute_with_retry()`          | Background operations      | Silent retry (no UI)              |
| `safe_query()`                  | When you want to toggle UI | Flexible control                  |
| `wrap_db_operation()`           | Simple logging             | Basic error handling              |

---

## Error Types Users See

```
🌐 Connection Issue
   "Unable to reach the server. Check your internet connection..."

⚠️  Server Connection
    "We're temporarily unable to connect. Please wait and try again..."

❌ Error
    "We encountered an unexpected issue. Please try again..."
```

---

## Implementation in welfare_support.py

```python
# Member context
member_context = execute_with_error_handling(
    lambda: _get_current_member_context(user_id),
    "Loading member profile"
) or {}

# Dashboard metrics
metrics = execute_with_error_handling(
    get_welfare_leader_metrics,
    "Loading dashboard metrics"
) or {default_metrics}

# Requests list
requests = execute_with_error_handling(
    lambda: _get_welfare_requests_for_role(user_role, user_id),
    "Loading welfare requests"
) or []

# Support categories
categories = execute_with_error_handling(
    _get_welfare_categories,
    "Loading support categories"
) or []
```

---

## What Never Reaches Users

❌ `psycopg2.OperationalError`  
❌ `socket.gaierror`  
❌ `DNS resolution failed`  
❌ Stack traces  
❌ Connection strings  
❌ Database credentials  
❌ SQL errors  
❌ Server configuration

## What Gets Logged (For Debugging)

✅ Full exception details  
✅ Stack traces  
✅ Database errors  
✅ Retry attempts  
✅ Timestamps  
✅ Error categorization

## Testing

```bash
# Run error handling tests
python -m pytest tests/test_error_handling.py -v

# Run existing welfare tests (backward compat)
python -m pytest tests/test_welfare_workflow.py -v

# Check syntax
python -m py_compile src/utils/error_handler.py
```

## Results from Tests

✅ 12/12 error handling tests passing  
✅ 2/2 welfare workflow tests passing  
✅ All syntax valid  
✅ No internal details exposed (verified)  
✅ User messages are reassuring (verified)  
✅ 100% backward compatible

---

## More Information

- **Full Guide:** [ERROR_HANDLING_GUIDE.md](ERROR_HANDLING_GUIDE.md)
- **Implementation Details:** [ERROR_HANDLING_IMPLEMENTATION.md](ERROR_HANDLING_IMPLEMENTATION.md)
- **Source Code:** `src/utils/error_handler.py`
- **Tests:** `tests/test_error_handling.py`

---

## Key Benefits

✅ Users never see technical errors  
✅ Automatic recovery for temporary issues  
✅ Professional, reassuring messages  
✅ Manual retry option ("Try Again" button)  
✅ Full logging for debugging  
✅ No crashes or blank pages  
✅ Works with existing code

---

**Status: READY FOR PRODUCTION** ✅
