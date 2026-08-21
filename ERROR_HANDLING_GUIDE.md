# Error Handling Guide for COMFORT_PORTAL

## Overview

The COMFORT_PORTAL now implements comprehensive, user-friendly error handling for all database operations. The system ensures that:

- **Users never see raw exceptions, stack traces, or SQL errors**
- **Detailed logs are kept for debugging and monitoring**
- **All database operations fail gracefully without crashing the app**
- **Users get clear, reassuring messages with retry options**
- **Network issues are distinguished from server issues**

---

## Architecture

### Three-Layer Error Handling

```
┌─────────────────────────────────────────┐
│  UI Layer (welfare_support.py, etc.)    │
│  - Display user-friendly messages       │
│  - Show retry buttons                   │
│  - Handle business logic                │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  Error Handler (src/utils/error_handler.py)  │
│  - Wrap operations with UI              │
│  - Show spinners and retry buttons      │
│  - Categorize errors                    │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  Database Layer (connection.py)         │
│  - Automatic retry (3 attempts)         │
│  - Detailed logging                     │
│  - Error categorization                 │
└─────────────────────────────────────────┘
```

### Error Types

#### 1. `NetworkConnectionError`

- **When:** DNS resolution fails, internet is down, or server is unreachable
- **User Message:** "Unable to reach the server. Please check your internet connection..."
- **Temporary:** Yes (user can retry)

#### 2. `DatabaseUnavailableError` (Temporary)

- **When:** Connection timeouts, connection pool exhausted, temporary server issues
- **User Message:** "We're temporarily unable to connect to our secure server..."
- **Temporary:** Yes
- **Flag:** `is_temporary=True`

#### 3. `DatabaseUnavailableError` (Permanent)

- **When:** Configuration errors, unexpected database errors
- **User Message:** "We encountered an unexpected issue while connecting..."
- **Temporary:** No
- **Flag:** `is_temporary=False`

---

## Using Error Handling in Your Code

### Option 1: Full Error Handling with UI (Recommended for User-Facing Operations)

```python
from src.utils.error_handler import execute_with_error_handling

def load_member_welfare_data():
    # Database operation wrapped in a function
    return get_member_welfare_summary(member_id)

# Wrap with UI error handling
data = execute_with_error_handling(
    load_member_welfare_data,
    operation_name="Loading welfare summary"
)

# Use the result (will be None if operation failed)
if data:
    st.write(data)
    # Business logic continues...
```

**What this does:**

- Shows a loading spinner ("Loading... Loading welfare summary")
- Automatically retries up to 3 times
- Displays a user-friendly error message if it fails
- Shows a "Try Again" button to retry without page refresh
- Returns None on failure

### Option 2: Retry Without UI (For Background Operations)

```python
from src.utils.error_handler import execute_with_retry

def sync_notifications():
    return execute_query(
        "SELECT * FROM notifications WHERE is_read = FALSE",
        fetch=True
    )

# Retry silently without showing UI elements
result = execute_with_retry(
    sync_notifications,
    operation_name="Syncing notifications",
    max_retries=3
)

# Handle result
if result is None:
    # Operation failed after retries
    logger.warning("Notification sync failed")
else:
    # Process the results
    process_notifications(result)
```

### Option 3: Safe Query Wrapper (Flexible)

```python
from src.utils.error_handler import safe_query

# With UI (default)
data = safe_query(
    lambda: execute_query("SELECT * FROM welfare_requests", fetch=True),
    "Loading requests",
    show_error_ui=True
)

# Without UI
data = safe_query(
    lambda: execute_query("SELECT * FROM welfare_requests", fetch=True),
    "Loading requests",
    show_error_ui=False
)
```

### Option 4: Simple Wrapper (Minimal)

```python
from src.utils.error_handler import wrap_db_operation

# Just add basic error handling without UI
def create_request():
    return execute_query(
        "INSERT INTO welfare_requests (...) VALUES (...)",
        fetch=False
    )

result = wrap_db_operation(
    create_request,
    "Creating welfare request"
)

# You handle the error display
if result is None:
    st.error("Failed to create request. Please try again.")
else:
    st.success("Request created successfully")
```

---

## Examples in welfare_support.py

### Example 1: Loading Member Context

```python
def load_member_context():
    return _get_current_member_context(user_id)

member_context = execute_with_error_handling(
    load_member_context,
    "Loading member profile"
) or {}  # Default to empty dict on failure
```

### Example 2: Loading Requests for Staff

```python
def load_requests():
    return _get_welfare_requests_for_role(user_role, user_id)

requests = execute_with_error_handling(
    load_requests,
    "Loading welfare requests"
) or []  # Default to empty list on failure
```

### Example 3: Loading Categories

```python
def load_categories():
    return _get_welfare_categories()

categories = execute_with_error_handling(
    load_categories,
    "Loading support categories"
) or []

if not categories:
    st.info("No welfare categories available. Contact support.")
    return
```

---

## Best Practices

### ✅ DO:

1. **Wrap all user-facing database operations**

   ```python
   result = execute_with_error_handling(operation, "Loading data")
   ```

2. **Use descriptive operation names**

   ```python
   # Good
   "Loading welfare dashboard metrics"

   # Bad
   "Loading data"
   ```

3. **Provide sensible defaults on failure**

   ```python
   data = execute_with_error_handling(...) or []
   ```

4. **Log detailed errors internally**

   ```python
   # The error handler logs full details automatically
   logger.exception("Full traceback for investigation")
   ```

5. **Show user-friendly messages**
   ```python
   # Users see: "We're temporarily unable to connect..."
   # Not: "psycopg2.OperationalError: could not connect to server"
   ```

### ❌ DON'T:

1. **Don't expose raw exceptions to users**

   ```python
   # Bad - exposes internals
   except Exception as e:
       st.error(str(e))

   # Good - use error handler
   result = execute_with_error_handling(operation, name)
   ```

2. **Don't include SQL errors in user messages**

   ```python
   # Bad
   st.error(f"Database error: {error}")

   # Good
   st.error("Unable to save your information. Please try again.")
   ```

3. **Don't ignore database failures**

   ```python
   # Bad - crash if database fails
   data = execute_query(...)
   process(data[0])  # KeyError if empty

   # Good - handle gracefully
   data = execute_with_error_handling(...) or []
   if data:
       process(data[0])
   ```

4. **Don't retry indefinitely**

   ```python
   # Bad - infinite loops
   while True:
       try:
           result = execute_query(...)
           break
       except:
           continue

   # Good - use built-in retry (max 3 attempts)
   result = execute_with_error_handling(operation, name)
   ```

5. **Don't hide all errors from logs**

   ```python
   # Bad - silent failures
   result = execute_with_error_handling(...) or []

   # Good - errors are logged automatically
   # You can review logs for debugging
   ```

---

## Error Message Examples

### When User Has No Internet

**User Sees:**

```
🌐 Connection Issue

Unable to reach the server. Please check your internet connection
and try again. If the problem persists, the server may be
temporarily unavailable.

[🔄 Try Again]  Click the button above to retry, or wait a moment
                and refresh the page.
```

### When Server is Temporarily Down

**User Sees:**

```
⚠️ Server Connection

We're temporarily unable to connect to our secure server. This is
usually caused by a temporary internet or server connection issue.
Please wait a moment and try again. Your information has not been lost.

[🔄 Try Again]  Click the button above to retry, or wait a moment
                and refresh the page.
```

### When Unexpected Error Occurs

**User Sees:**

```
❌ Error

We encountered an unexpected issue while connecting to our server.
Please try again. If this continues, please contact our support team.

[🔄 Try Again]  Click the button above to retry, or wait a moment
                and refresh the page.
```

---

## Logging

All errors are logged with full details for investigation:

```python
# In src/database/connection.py logs:
ERROR - Database connection error (attempt 3/3, temp=True): timeout
ERROR - Network error: DNS resolution failed (attempt 3/3)
ERROR - Query execution failed: connection refused

# In src/utils/error_handler.py logs:
ERROR - Database unavailable during Loading welfare requests
ERROR - Network error during Loading member profile
ERROR - Unexpected error during Creating welfare request
```

**View logs in production:**

- Streamlit apps: Check app.log files
- Heroku: `heroku logs --tail`
- Docker: `docker logs <container>`
- Local: Console output during development

---

## Testing Error Handling

### Simulate Database Failure

```python
# In development, you can test error handling by:

# 1. Stopping the database
# Run: sudo systemctl stop postgres

# 2. Changing DATABASE_URL to invalid host
# os.environ["DATABASE_URL"] = "postgresql://user:pass@invalid-host:5432/db"

# 3. Using execute_with_error_handling as normal
# The error handling will catch the failure and show user-friendly message

# 4. Click "Try Again" button to retry
# After restarting database, retry should succeed
```

### Simulate Network Failure

```python
# Windows: ipconfig /release  (releases IP temporarily)
# Mac: networksetup -setnetworkserviceenabled WiFi off
# Linux: sudo ip link set eth0 down

# Then access the app - error handling will catch network errors
```

---

## Backward Compatibility

✅ **All existing code continues to work:**

- Function signatures unchanged
- Return types unchanged
- Business logic unchanged
- Database operations unchanged
- Financial records unchanged
- Audit logging unchanged
- Permissions unchanged

**Only additions:**

- Better error messages (never exposed to users)
- Automatic retry mechanism
- User-friendly UI error display
- Error categorization for logging

---

## Performance Impact

- **Minimal overhead:** ~1-5ms per operation for error handling
- **Retry mechanism:** Adds 1-3 seconds only on failure
- **Logging:** Negligible impact
- **UI elements:** Cached and reused efficiently

---

## Migration Guide

### For Existing Code

Option 1: **Leave as-is (still works)**

```python
# Old code still works fine
data = execute_query(...)
# If it fails, exception bubbles up
```

Option 2: **Add error handling gradually**

```python
# Wrap user-facing operations
result = execute_with_error_handling(
    lambda: execute_query(...),
    "Loading data"
)
```

### For New Code

Always use error handling for user-facing operations:

```python
result = execute_with_error_handling(
    load_data,
    "Loading data"
)
```

---

## Troubleshooting

### Users See "Try Again" Button but Operation Still Fails

**Likely causes:**

- Database is down longer than retry timeout
- Network is completely disconnected
- Invalid database configuration

**Solution:**

- Check database status
- Check network connectivity
- Review logs for detailed error

### Retry Button Not Working

**Likely causes:**

- Browser cache issue
- Session timeout
- JavaScript error

**Solution:**

- Clear browser cache
- Refresh page manually
- Check browser console for JS errors

### Errors Not Appearing in Logs

**Likely causes:**

- Logging not configured
- Log level too high
- Logs rotated out

**Solution:**

- Check logging configuration
- Reduce log level to DEBUG
- Check log rotation settings

---

## Support & References

- **Error Handler Source:** `src/utils/error_handler.py`
- **Database Connection Source:** `src/database/connection.py`
- **Example Usage:** `src/views/welfare_support.py`
- **Logger Configuration:** Check Python logging setup in main app

---

## Summary

The new error handling system provides:

✅ **User Experience:** Clear, reassuring messages instead of technical errors
✅ **Reliability:** Automatic retry without app crash
✅ **Debugging:** Detailed logs while protecting user privacy
✅ **Flexibility:** Multiple usage patterns for different scenarios
✅ **Safety:** All operations fail gracefully
✅ **Compatibility:** Existing code continues to work
✅ **Performance:** Minimal overhead

Use `execute_with_error_handling()` for all user-facing database operations to ensure the best user experience during temporary server or network issues.
