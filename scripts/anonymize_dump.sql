-- Anonymisierungs-Skript fuer Stage-Env.
--
-- Ausfuehrung: psql -U <user> -d <db> -f anonymize_dump.sql
-- Wird vom Helper-Skript scripts/stage_restore.sh nach pg_restore aufgerufen.
--
-- Strategie:
--   - User-Emails werden deterministisch durch user{id}@example.test ersetzt.
--   - Passwoerter werden auf einen bekannten Bcrypt-Hash gesetzt (Stage-Login mit "stage123").
--   - Fernet-encrypted Felder werden auf NULL gesetzt, weil Re-Encryption mit gleichem Key gebrochen waere.
--   - Session-/Token-Tabellen werden vollstaendig geleert (Force-Re-Login auf Stage).
--   - Externe Webhook-Configs werden geleert (verhindert versehentliches Senden auf echte Topics).
--   - Adressen, IBANs, Bank-Namen, Tenant-Namen, Order-IDs, Notes werden mit Platzhaltern ueberschrieben.
--
-- Idempotent: Mehrfach ausfuehrbar.
-- Wichtig: NICHT auf Production-DB ausfuehren — pruefe DB-Name vor Aufruf.

BEGIN;

-- ============================================================================
-- 1. Users — Emails deterministisch anonymisieren
-- ============================================================================
UPDATE users
SET email = 'user-' || substring(id::text, 1, 8) || '@example.test',
    -- Bcrypt-Hash fuer "stage123" (gerundet, 12 Rounds). Erlaubt Login auf Stage.
    password_hash = '$2b$12$LX5wXG4r8YQ9XaTKsHbz5e/H6sB.RkqfqWxtmDqPLNgaENrPmCnxq',
    totp_secret = NULL,
    mfa_enabled = false,
    force_password_change = false;

-- Admin bekommt eine bekannte Stage-Email (alle Admins werden auf admin@example.test
-- gesetzt — in Production existiert i.d.R. nur einer)
UPDATE users SET email = 'admin@example.test' WHERE is_admin = true;

-- ============================================================================
-- 2. Sessions / Tokens loeschen (Force-Re-Login)
-- ============================================================================
DELETE FROM refresh_tokens;
DELETE FROM password_reset_tokens;
DELETE FROM mfa_backup_codes;
DELETE FROM api_tokens;
DELETE FROM admin_audit_log;
DELETE FROM api_write_log;

-- ============================================================================
-- 3. User-Settings — verschluesselte API-Keys leeren
-- ============================================================================
UPDATE user_settings
SET fred_api_key = NULL,
    fmp_api_key = NULL,
    finnhub_api_key = NULL;

-- ============================================================================
-- 4. SMTP & NTFY Configs — externe Endpoints neutralisieren
-- ============================================================================
UPDATE smtp_config
SET host = 'smtp.example.test',
    username = 'stage@example.test',
    password_encrypted = 'STAGE-DISABLED',
    from_email = 'noreply@example.test',
    provider = 'stage'
WHERE host IS NOT NULL;

UPDATE ntfy_config
SET server_url = 'http://ntfy.example.test',
    topic = 'stage-disabled',
    access_token_encrypted = NULL;

-- ============================================================================
-- 5. Properties — Adressen, Notes, Tenant-Daten anonymisieren
-- ============================================================================
UPDATE properties
SET name = 'Property ' || substring(id::text, 1, 8),
    address = 'Anonymized Address, Stage',
    notes = NULL;

UPDATE mortgages
SET bank = NULL,
    notes = NULL;

UPDATE property_expenses
SET description = 'Stage Expense'
WHERE description IS NOT NULL;

UPDATE property_income
SET description = 'Stage Income',
    tenant = NULL
WHERE description IS NOT NULL OR tenant IS NOT NULL;

-- ============================================================================
-- 6. Private Equity — verschluesselte PII auf NULL
-- ============================================================================
UPDATE private_equity_holdings
SET company_name = 'PE Holding ' || substring(id::text, 1, 8),
    uid_number = NULL,
    register_nr = NULL,
    notes = NULL;

UPDATE private_equity_valuations
SET notes = NULL,
    source = NULL;

UPDATE private_equity_dividends
SET notes = NULL;

-- ============================================================================
-- 7. Positions — Bank-Details, IBAN, Notes leeren
-- ============================================================================
UPDATE positions
SET notes = NULL,
    bank_name = NULL,
    iban = NULL;

-- ============================================================================
-- 8. Transactions — Order-IDs und Notes anonymisieren
-- ============================================================================
UPDATE transactions
SET notes = NULL,
    order_id = NULL,
    import_batch_id = NULL,
    raw_symbol = NULL;

-- ============================================================================
-- 9. Precious Metals — (notes-Spalten existieren in v0.36 nicht; nichts zu tun)
-- ============================================================================
-- Platzhalter fuer zukuenftige Schema-Erweiterungen

-- ============================================================================
-- 10. Watchlist — Notes leeren
-- ============================================================================
UPDATE watchlist SET notes = NULL WHERE notes IS NOT NULL;

-- ============================================================================
-- 11. Sanity-Check: keine produktiven Emails mehr
-- ============================================================================
DO $$
DECLARE
    leaked_count INT;
BEGIN
    SELECT COUNT(*) INTO leaked_count FROM users WHERE email NOT LIKE '%@example.test';
    IF leaked_count > 0 THEN
        RAISE EXCEPTION 'Anonymization failed: % users still have non-stage emails', leaked_count;
    END IF;
END $$;

COMMIT;

-- Optimieren nach Bulk-Updates
VACUUM ANALYZE;

\echo 'Stage anonymization complete. All users now have @example.test emails. Stage login password: stage123'
