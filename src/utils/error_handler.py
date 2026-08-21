"""
Error handling utilities for database operations with Streamlit UI integration.

Provides user-friendly error messages, retry mechanisms, and graceful degradation
without exposing internal details or crashing the application.
"""

import logging
from typing import Any, Callable, Optional, TypeVar

import streamlit as st

from src.database.connection import DatabaseUnavailableError, NetworkConnectionError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def get_error_display_message(error: Exception) -> str:
    """
    Extract the user-friendly error message from a DatabaseUnavailableError.
    Falls back to a generic message for other exceptions.
    """
    if isinstance(error, DatabaseUnavailableError):
        return error.user_friendly_message
    
    # Generic fallback for unexpected exceptions
    return (
        "We encountered an unexpected issue. Please try again. "
        "If this continues, please contact our support team."
    )


def display_database_error(
    error: Exception,
    context: str = "database operation",
    show_retry_button: bool = True,
    retry_callback: Optional[Callable[[], None]] = None,
) -> None:
    """
    Display a user-friendly error message with optional retry button.
    
    Args:
        error: The exception that occurred
        context: Human-readable description of what was being attempted
        show_retry_button: Whether to show a "Try Again" button
        retry_callback: Optional callback to execute when retry button is clicked
    """
    message = get_error_display_message(error)
    
    # Determine if we should show specific guidance
    if isinstance(error, NetworkConnectionError):
        icon = "🌐"
        title = "Connection Issue"
    elif isinstance(error, DatabaseUnavailableError):
        icon = "⚠️"
        title = "Server Connection"
    else:
        icon = "❌"
        title = "Error"
    
    # Display the error in Streamlit
    with st.container(border=True):
        st.markdown(f"### {icon} {title}")
        st.write(message)
        
        if show_retry_button:
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("🔄 Try Again", key=f"retry_{id(error)}"):
                    if retry_callback:
                        retry_callback()
                    st.rerun()
            with col2:
                st.caption(
                    "Click the button above to retry, or wait a moment and refresh the page."
                )


def execute_with_error_handling(
    operation: Callable[[], T],
    operation_name: str = "Operation",
    show_spinner: bool = True,
) -> Optional[T]:
    """
    Execute a database operation with automatic retry, error display, and retry button.
    
    This function:
    - Shows a loading spinner during the operation
    - Catches database errors and displays user-friendly messages
    - Provides a "Try Again" button to retry without page refresh
    - Logs detailed errors for debugging
    - Never exposes internal details to the user
    - Returns None on failure
    
    Args:
        operation: Callable that performs the database operation
        operation_name: Human-readable name of the operation for UI display
        show_spinner: Whether to show a loading spinner (default: True)
    
    Returns:
        Result of the operation, or None if operation failed
    
    Example:
        def load_welfare_data():
            return execute_query("SELECT * FROM welfare_requests", fetch=True)
        
        data = execute_with_error_handling(
            load_welfare_data,
            "Loading welfare requests"
        )
        if data:
            st.write(data)
    """
    try:
        if show_spinner:
            with st.spinner(f"Loading... {operation_name}"):
                result = operation()
            return result
        else:
            return operation()
    
    except DatabaseUnavailableError as exc:
        logger.exception("Database unavailable during %s", operation_name)
        
        # Create retry callback
        def retry_operation():
            st.session_state[f"retry_{operation_name}"] = True
        
        display_database_error(
            exc,
            context=operation_name,
            show_retry_button=True,
            retry_callback=retry_operation,
        )
        return None
    
    except NetworkConnectionError as exc:
        logger.exception("Network error during %s", operation_name)
        
        def retry_operation():
            st.session_state[f"retry_{operation_name}"] = True
        
        display_database_error(
            exc,
            context=operation_name,
            show_retry_button=True,
            retry_callback=retry_operation,
        )
        return None
    
    except Exception as exc:
        logger.exception("Unexpected error during %s", operation_name)
        
        def retry_operation():
            st.session_state[f"retry_{operation_name}"] = True
        
        display_database_error(
            exc,
            context=operation_name,
            show_retry_button=True,
            retry_callback=retry_operation,
        )
        return None


def execute_with_retry(
    operation: Callable[[], T],
    operation_name: str = "Operation",
    max_retries: int = 3,
) -> Optional[T]:
    """
    Execute a database operation with automatic retries and error logging.
    
    This is a lighter-weight alternative to execute_with_error_handling()
    when you want to handle the retry display yourself or don't need
    Streamlit UI elements.
    
    Args:
        operation: Callable that performs the database operation
        operation_name: Human-readable name of the operation for logging
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        Result of the operation, or None if operation failed after all retries
    """
    last_error = None
    
    for attempt in range(1, max_retries + 1):
        try:
            return operation()
        except (DatabaseUnavailableError, NetworkConnectionError) as exc:
            last_error = exc
            is_last_attempt = attempt == max_retries
            
            if is_last_attempt:
                logger.error(
                    "Operation failed after %d attempts: %s",
                    max_retries,
                    operation_name,
                )
                return None
            
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt,
                max_retries,
                operation_name,
                exc,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected error during %s (attempt %d/%d)",
                operation_name,
                attempt,
                max_retries,
            )
            return None
    
    if last_error:
        return None
    
    return None


def safe_query(
    query_func: Callable[[], Optional[Any]],
    operation_name: str = "Database Query",
    show_error_ui: bool = True,
) -> Optional[Any]:
    """
    Safely execute a database query function with error handling.
    
    This is a convenience wrapper that combines error handling and optional UI display.
    
    Args:
        query_func: Function that executes the database query
        operation_name: Description of the operation for error messages
        show_error_ui: Whether to display error UI (default: True)
    
    Returns:
        Query result or None on failure
    """
    if show_error_ui:
        return execute_with_error_handling(query_func, operation_name)
    else:
        return execute_with_retry(query_func, operation_name)


def wrap_db_operation(
    operation: Callable[[], T],
    operation_name: str,
) -> Optional[T]:
    """
    Simple wrapper for database operations that just adds error logging
    and returns None on failure without any UI elements.
    
    Use this for operations where the caller will handle error display.
    
    Args:
        operation: The database operation to wrap
        operation_name: Description for logging
    
    Returns:
        Operation result or None
    """
    try:
        return operation()
    except DatabaseUnavailableError as exc:
        logger.error("Database unavailable: %s", operation_name)
        return None
    except Exception as exc:
        logger.exception("Error during %s", operation_name)
        return None
