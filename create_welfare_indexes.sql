-- ============================================================================
-- Welfare Module Performance Optimization - Database Indexes
-- ============================================================================
-- Purpose: Create indexes on frequently searched/filtered columns to support
--          optimized queries in the welfare module
-- 
-- Apply these indexes to production database to complete the optimization
-- 
-- Deployment: Run this script against COMFORT_PORTAL production database
-- ============================================================================

-- ============================================================================
-- WELFARE_REQUESTS TABLE INDEXES
-- ============================================================================
-- These indexes support the optimized _get_welfare_requests_for_role() function
-- and member welfare summary queries

-- Index for role-based filtering (Chairperson, Treasurer, etc.)
CREATE INDEX IF NOT EXISTS idx_welfare_requests_member_status 
ON welfare_requests(member_id, status);

-- Index for case number lookups
CREATE INDEX IF NOT EXISTS idx_welfare_requests_case_number 
ON welfare_requests(case_number);

-- Index for date-range queries and sorting
CREATE INDEX IF NOT EXISTS idx_welfare_requests_created_at 
ON welfare_requests(created_at DESC);

-- Index for status-only filters (staff dashboard)
CREATE INDEX IF NOT EXISTS idx_welfare_requests_status 
ON welfare_requests(status);

-- ============================================================================
-- LEDGER_TRANSACTIONS TABLE INDEXES
-- ============================================================================
-- These indexes support the optimized get_member_welfare_summary() query
-- which aggregates transaction data with welfare requests

-- Index for member transaction lookups (critical for welfare summary)
CREATE INDEX IF NOT EXISTS idx_ledger_transactions_member_type 
ON ledger_transactions(member_id, transaction_type);

-- Index for date-based sorting and filtering
CREATE INDEX IF NOT EXISTS idx_ledger_transactions_created_at 
ON ledger_transactions(created_at DESC);

-- Index for transaction type lookups (welfare contributions vs credits)
CREATE INDEX IF NOT EXISTS idx_ledger_transactions_type 
ON ledger_transactions(transaction_type);

-- ============================================================================
-- NOTIFICATIONS TABLE INDEXES
-- ============================================================================
-- These indexes support the optimized get_unread_notification_count() query

-- Index for unread notification count queries (critical path)
CREATE INDEX IF NOT EXISTS idx_notifications_recipient_read 
ON notifications(recipient_id, is_read);

-- Index for read status filtering
CREATE INDEX IF NOT EXISTS idx_notifications_read_status 
ON notifications(is_read);

-- ============================================================================
-- WELFARE_MESSAGES TABLE INDEXES
-- ============================================================================
-- These indexes support message retrieval for welfare cases

-- Index for request-based message lookups
CREATE INDEX IF NOT EXISTS idx_welfare_messages_request 
ON welfare_messages(request_id);

-- ============================================================================
-- WELFARE_AUDIT_LOG TABLE INDEXES
-- ============================================================================
-- These indexes support audit trail retrieval

-- Index for request-based audit lookups
CREATE INDEX IF NOT EXISTS idx_welfare_audit_log_request 
ON welfare_audit_log(request_id);

-- Index for user action tracking
CREATE INDEX IF NOT EXISTS idx_welfare_audit_log_user 
ON welfare_audit_log(user_id);

-- ============================================================================
-- WELFARE_CATEGORIES TABLE INDEXES (if caching is disabled)
-- ============================================================================
-- These are optional since categories are cached for 1 hour,
-- but useful for category administration queries

CREATE INDEX IF NOT EXISTS idx_welfare_categories_active 
ON welfare_categories(is_active);

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Run these queries to verify indexes were created successfully

-- List all welfare-related indexes:
-- SELECT 
--     tablename,
--     indexname,
--     indexdef
-- FROM pg_indexes
-- WHERE tablename IN (
--     'welfare_requests',
--     'ledger_transactions',
--     'notifications',
--     'welfare_messages',
--     'welfare_audit_log',
--     'welfare_categories'
-- )
-- ORDER BY tablename, indexname;

-- ============================================================================
-- PERFORMANCE BASELINE QUERIES (for before/after comparison)
-- ============================================================================

-- Welfare summary query (should now use composite index)
-- EXPLAIN ANALYZE
-- SELECT
--     COALESCE(SUM(CASE WHEN lt.transaction_type = 'Welfare Support Credit' THEN lt.amount ELSE 0 END), 0) AS credits,
--     COALESCE(SUM(CASE WHEN lt.transaction_type = 'Welfare Contribution' THEN ABS(lt.amount) ELSE 0 END), 0) AS contributions,
--     MAX(CASE WHEN lt.transaction_type = 'Welfare Contribution' THEN lt.created_at ELSE NULL END) AS last_contribution_date,
--     COUNT(DISTINCT wr1.id) AS cases_requested,
--     COUNT(DISTINCT CASE WHEN wr2.status = 'Paid' THEN wr2.id ELSE NULL END) AS cases_received
-- FROM ledger_transactions lt
-- LEFT JOIN welfare_requests wr1 ON wr1.member_id = lt.member_id
-- LEFT JOIN welfare_requests wr2 ON wr2.member_id = lt.member_id AND wr2.status = 'Paid'
-- WHERE lt.member_id = 'test_member_id';

-- Chairperson role filter query (should use status index)
-- EXPLAIN ANALYZE
-- SELECT id, case_number, member_id, member_name, status, created_at
-- FROM welfare_requests
-- WHERE status IN ('Approved by Welfare Officer', 'Pending Chairperson Approval', 'Returned for Review')
-- ORDER BY created_at DESC;

-- Unread notification count (should use composite index)
-- EXPLAIN ANALYZE
-- SELECT COUNT(*) AS unread_count FROM notifications
-- WHERE is_read = FALSE AND recipient_id = 'test_member_id';

-- ============================================================================
-- NOTES
-- ============================================================================
-- 1. These indexes should be created on the production database after
--    deploying the optimized welfare_support.py module
--
-- 2. Index creation typically takes <100ms on production datasets but may
--    lock tables briefly. Schedule during low-traffic period.
--
-- 3. Indexes will be maintained automatically by PostgreSQL on INSERT/UPDATE
--
-- 4. Monitor index usage and re-analyze after 1 week of production traffic:
--    SELECT * FROM pg_stat_user_indexes WHERE relname LIKE '%welfare%'
--
-- 5. If performance doesn't improve as expected:
--    - Run ANALYZE on tables to update query planner statistics
--    - Review EXPLAIN ANALYZE output for bottlenecks
--    - Consider additional indexes based on slow query logs
--
-- 6. Remove unused indexes after analysis to reduce maintenance overhead:
--    DROP INDEX IF EXISTS index_name;

-- ============================================================================
-- END OF WELFARE MODULE INDEX CREATION SCRIPT
-- ============================================================================
