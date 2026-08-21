"""
Test suite for error handling in COMFORT_PORTAL.

Tests verify that:
- Database errors are properly categorized
- User-friendly messages are generated correctly
- No crashes occur on database failures
- Retry mechanisms work properly
"""

import logging
from src.database.connection import (
    DatabaseUnavailableError,
    NetworkConnectionError,
)
from src.utils.error_handler import (
    get_error_display_message,
)

logger = logging.getLogger(__name__)


def test_network_error_user_message():
    """Test that network errors show appropriate user message."""
    error = NetworkConnectionError("DNS resolution failed")
    message = error.user_friendly_message
    
    assert "internet connection" in message.lower()
    assert "DNS resolution failed" not in message  # Internal details hidden
    assert error.is_network_error is True
    assert error.is_temporary is True
    print("✅ NetworkConnectionError message correct")


def test_temporary_database_error_message():
    """Test that temporary database errors show appropriate message."""
    error = DatabaseUnavailableError(
        "Connection timeout",
        is_network_error=False,
        is_temporary=True
    )
    message = error.user_friendly_message
    
    assert "temporarily unable to connect" in message.lower()
    assert "Connection timeout" not in message  # Internal details hidden
    assert error.is_temporary is True
    print("✅ Temporary database error message correct")


def test_permanent_database_error_message():
    """Test that permanent database errors show appropriate message."""
    error = DatabaseUnavailableError(
        "Invalid configuration",
        is_network_error=False,
        is_temporary=False
    )
    message = error.user_friendly_message
    
    assert "unexpected issue" in message.lower()
    assert "support team" in message.lower()
    assert error.is_temporary is False
    print("✅ Permanent database error message correct")


def test_get_error_display_message_with_db_error():
    """Test that error messages are retrieved correctly."""
    error = DatabaseUnavailableError(
        "Connection refused",
        is_network_error=False,
        is_temporary=True
    )
    
    message = get_error_display_message(error)
    assert isinstance(message, str)
    assert len(message) > 0
    assert "Connection refused" not in message  # Internal details hidden
    print("✅ Error display message extraction works")


def test_get_error_display_message_with_network_error():
    """Test network error message display."""
    error = NetworkConnectionError("Network unavailable")
    message = get_error_display_message(error)
    
    assert "internet" in message.lower() or "connection" in message.lower()
    assert "Network unavailable" not in message  # Internal details hidden
    print("✅ Network error display message works")


def test_get_error_display_message_with_generic_exception():
    """Test fallback for non-DatabaseUnavailableError exceptions."""
    generic_error = Exception("Some random error")
    message = get_error_display_message(generic_error)
    
    assert isinstance(message, str)
    assert len(message) > 0
    assert "Some random error" not in message  # Internal details hidden
    assert "unexpected" in message.lower()
    print("✅ Generic exception fallback works")


def test_no_internal_details_exposed():
    """Verify that internal implementation details are never exposed."""
    errors = [
        NetworkConnectionError("DNS: getaddrinfo failed"),
        DatabaseUnavailableError(
            "psycopg2.OperationalError: connection refused",
            is_network_error=False,
            is_temporary=True
        ),
        DatabaseUnavailableError(
            "Invalid connection string: malformed URL",
            is_network_error=False,
            is_temporary=False
        ),
    ]
    
    dangerous_keywords = [
        "psycopg2",
        "getaddrinfo",
        "connection string",
        "malformed URL",
        "OperationalError",
        "traceback",
        "stack trace",
    ]
    
    for error in errors:
        message = error.user_friendly_message
        for keyword in dangerous_keywords:
            assert keyword.lower() not in message.lower(), \
                f"Internal detail '{keyword}' exposed in: {message}"
    
    print("✅ No internal implementation details exposed")


def test_error_categorization():
    """Test that errors are categorized correctly for logging."""
    # Network error
    network_err = NetworkConnectionError("DNS failed")
    assert network_err.is_network_error is True
    assert network_err.is_temporary is True
    
    # Temporary database error
    temp_db_err = DatabaseUnavailableError("timeout", False, True)
    assert temp_db_err.is_network_error is False
    assert temp_db_err.is_temporary is True
    
    # Permanent database error
    perm_db_err = DatabaseUnavailableError("config error", False, False)
    assert perm_db_err.is_network_error is False
    assert perm_db_err.is_temporary is False
    
    print("✅ Error categorization works correctly")


def test_error_inheritance():
    """Test that error classes inherit from appropriate base classes."""
    network_error = NetworkConnectionError("test")
    db_error = DatabaseUnavailableError("test")
    
    assert isinstance(network_error, DatabaseUnavailableError)
    assert isinstance(network_error, Exception)
    assert isinstance(db_error, Exception)
    
    print("✅ Error inheritance hierarchy correct")


def test_error_string_representation():
    """Test that errors can be converted to strings without crashing."""
    errors = [
        NetworkConnectionError("Network issue"),
        DatabaseUnavailableError("DB unavailable", True, True),
        DatabaseUnavailableError("Unexpected error", False, False),
    ]
    
    for error in errors:
        error_str = str(error)
        message = error.user_friendly_message
        
        assert isinstance(error_str, str)
        assert isinstance(message, str)
        assert len(error_str) > 0
        assert len(message) > 0
    
    print("✅ Error string representations work")


def test_user_friendly_messages_are_reassuring():
    """Verify that error messages are reassuring and helpful."""
    errors = [
        NetworkConnectionError("Network down"),
        DatabaseUnavailableError("timeout", False, True),
    ]
    
    reassuring_keywords = [
        "temporary",
        "try again",
        "moment",
        "usually",
        "not lost",
    ]
    
    for error in errors:
        message = error.user_friendly_message
        has_reassuring_language = any(
            keyword.lower() in message.lower()
            for keyword in reassuring_keywords
        )
        assert has_reassuring_language, \
            f"Message not reassuring: {message}"
    
    print("✅ Error messages are reassuring and helpful")


def test_error_logging_context():
    """Test that errors preserve context information for logging."""
    error = DatabaseUnavailableError(
        "Connection failed",
        is_network_error=False,
        is_temporary=True
    )
    
    # Error should have all contextual info for logging
    assert hasattr(error, "is_network_error")
    assert hasattr(error, "is_temporary")
    assert hasattr(error, "user_friendly_message")
    
    # These can be used for intelligent error routing in logs
    assert error.is_network_error is False
    assert error.is_temporary is True
    
    print("✅ Error logging context preserved")


def run_all_tests():
    """Run all error handling tests."""
    print("\n" + "="*60)
    print("COMFORT_PORTAL Error Handling Test Suite")
    print("="*60 + "\n")
    
    test_functions = [
        test_network_error_user_message,
        test_temporary_database_error_message,
        test_permanent_database_error_message,
        test_get_error_display_message_with_db_error,
        test_get_error_display_message_with_network_error,
        test_get_error_display_message_with_generic_exception,
        test_no_internal_details_exposed,
        test_error_categorization,
        test_error_inheritance,
        test_error_string_representation,
        test_user_friendly_messages_are_reassuring,
        test_error_logging_context,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in test_functions:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test_func.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test_func.__name__}: Unexpected error: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("="*60)
    
    if failed == 0:
        print("\n✅ All tests passed! Error handling is working correctly.")
        return True
    else:
        print(f"\n❌ {failed} test(s) failed. Please review.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
