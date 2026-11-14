-- Anonymisierungs-Skript fuer Stage-Env.
--
-- Ausfuehrung: psql -v ON_ERROR_STOP=1 -U <user> -d <db> -f anonymize_dump.sql
-- Wird vom Helper-Skript scripts/stage_restore.sh nach dem Restore aufgerufen.
--
-- IMMER mit ON_ERROR_STOP=1: ohne den Schalter macht ein Fehler aus dem COMMIT
-- ein ROLLBACK, psql endet trotzdem mit 0, und die echten Daten bleiben stehen.
--
-- Strategie:
--   - User-Emails werden deterministisch durch user-{id}@example.test ersetzt.
--   - Passwoerter werden auf einen bekannten Bcrypt-Hash gesetzt (Stage-Login mit "stage123").
--   - MFA wird abgeschaltet (Konten und globale Policy), sonst sperrt die Policy
--     jedes Stage-Konto bis zur MFA-Einrichtung.
--   - Fernet-encrypted Felder werden auf NULL gesetzt: der Stage-Key kann sie nicht lesen.
--   - Session-/Token-Tabellen und Einladungscodes werden vollstaendig geleert.
--   - Externe Webhook-Configs werden geleert (verhindert versehentliches Senden auf echte Topics).
--   - Freitext der Nutzer (Notizen, Reports, Beschreibungen, eigene Namen) wird
--     geleert oder durch Platzhalter ersetzt.
--
-- Pflege: Jede Text-Spalte des Schemas steht in backend/tests/test_vr11_scripts_anonymize.py
-- entweder als anonymisiert oder als bewusst behalten. Eine neue Text-Spalte
-- laesst den Test scheitern, bis sie dort und hier eingeordnet ist.
--
-- Das Skript erwartet die Spalten des Dumps: nennt es eine Spalte, die der Dump
-- noch nicht hat, bricht es ab und stage_restore.sh loescht die Stage-DB wieder.
--
-- Idempotent: Mehrfach ausfuehrbar.
-- Wichtig: NICHT auf Production-DB ausfuehren — pruefe DB-Name vor Aufruf.

BEGIN;

-- ============================================================================
-- 1. Users — Emails deterministisch anonymisieren, MFA abschalten
-- ============================================================================
UPDATE users
SET email = 'user-' || substring(id::text, 1, 8) || '@example.test',
    -- Bcrypt-Hash fuer "stage123" (12 Rounds), erzeugt mit
    -- services.auth_service.hash_password. Erlaubt Login auf Stage.
    password_hash = '$2b$12$8qvrXiV0LAtIL9TyTDwaWO/ZcWGreswgIQrpKxD22OurP4H6GTK2m',
    totp_secret = NULL,
    mfa_enabled = false,
    mfa_required = false,
    force_password_change = false;

-- Admins bekommen eindeutige Adressen: users.email ist UNIQUE, zwei Admins auf
-- derselben Adresse liessen die ganze Transaktion scheitern. Der aelteste Admin
-- erhaelt die bekannte Stage-Adresse admin@example.test.
UPDATE users
SET email = 'admin-' || substring(id::text, 1, 8) || '@example.test'
WHERE is_admin = true;

UPDATE users
SET email = 'admin@example.test'
WHERE id = (SELECT id FROM users WHERE is_admin = true ORDER BY created_at, id LIMIT 1);

-- Globale MFA-Policy: Migration 094 seedet 'all'. Ohne MFA-Geraet antwortet das
-- Backend dann auf fast jedem Endpoint mit 403.
UPDATE app_settings SET value = 'off' WHERE key = 'mfa_policy';

-- ============================================================================
-- 2. Sessions / Tokens / Einladungscodes loeschen
-- ============================================================================
DELETE FROM refresh_tokens;
DELETE FROM password_reset_tokens;
DELETE FROM mfa_backup_codes;
DELETE FROM api_tokens;
DELETE FROM admin_audit_log;
DELETE FROM api_write_log;
-- Aktive Codes aus dem Dump gelten auf Production weiter.
DELETE FROM invite_codes;

-- ============================================================================
-- 3. User-Settings — verschluesselte API-Keys und FIRE-Annahmen leeren
-- ============================================================================
UPDATE user_settings
SET fred_api_key = NULL,
    fmp_api_key = NULL,
    finnhub_api_key = NULL,
    fire_assumptions = NULL;

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
SET name = 'Mortgage ' || substring(id::text, 1, 8),
    bank = NULL,
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

-- Konten und Vorsorge tragen frei gewaehlte Namen ("Lohnkonto <Bank>"). Namen
-- von Wertschriften sind Firmennamen und bleiben. Der Ticker bleibt ueberall:
-- an ihm haengen die Kursdaten und die CASH_-Logik der App.
UPDATE positions
SET name = initcap(replace(type::text, '_', ' ')) || ' ' || substring(id::text, 1, 8)
WHERE type::text IN ('cash', 'pension', 'real_estate', 'private_equity');

UPDATE position_bucket_history SET note = NULL WHERE note IS NOT NULL;

-- Eigene Buckets tragen frei gewaehlte Namen; System-Buckets heissen in jeder
-- Instanz gleich. Der Platzhalter bleibt je Nutzer eindeutig
-- (uq_bucket_user_name_active).
UPDATE buckets
SET name = 'Bucket ' || substring(id::text, 1, 8)
WHERE kind = 'user';

UPDATE buckets SET description = NULL WHERE description IS NOT NULL;

-- ============================================================================
-- 8. Transactions — Order-IDs und Notes anonymisieren
-- ============================================================================
UPDATE transactions
SET notes = NULL,
    order_id = NULL,
    import_batch_id = NULL,
    raw_symbol = NULL;

UPDATE fx_transactions
SET order_id = NULL,
    import_batch_id = NULL;

UPDATE pending_dividends SET notes = NULL WHERE notes IS NOT NULL;

UPDATE import_profiles
SET name = 'Import Profile ' || substring(id::text, 1, 8);

-- ============================================================================
-- 9. Precious Metals — Seriennummer, Lagerort und Notes sind Fernet-Chiffrate
-- ============================================================================
UPDATE precious_metal_items
SET serial_number = NULL,
    storage_location = NULL,
    notes = NULL;

UPDATE precious_metal_expenses
SET description = 'Stage Expense'
WHERE description IS NOT NULL;

-- ============================================================================
-- 10. Watchlist, Orders, Alerts — Notes leeren
-- ============================================================================
UPDATE watchlist
SET notes = NULL,
    notes_last_api_token_name = NULL;

UPDATE watchlist_tags
SET name = 'Tag ' || substring(id::text, 1, 8);

UPDATE pending_orders
SET notes = NULL,
    notes_last_api_token_name = NULL;

UPDATE price_alerts SET note = NULL WHERE note IS NOT NULL;

-- ============================================================================
-- 11. Reports — Inhalte ersetzen, Zeilen behalten (Kategorie, Datum, Ticker und
--     der Link auf die Transaktion bleiben fuer das Trade-Journal)
-- ============================================================================
UPDATE reports
SET title = 'Stage Report ' || substring(id::text, 1, 8),
    body = 'Anonymized stage report ' || id::text,
    tags = '[]',
    source = NULL,
    source_path = NULL,
    -- wie api/external_v1.py: SHA-256 ueber den Body
    content_hash = encode(sha256(convert_to('Anonymized stage report ' || id::text, 'UTF8')), 'hex');

-- ============================================================================
-- 12. Fehlertexte der Jobs — koennen Hostnamen und Adressen enthalten
-- ============================================================================
UPDATE worker_job_health SET last_error = NULL WHERE last_error IS NOT NULL;
UPDATE screening_scans SET error = NULL WHERE error IS NOT NULL;

-- ============================================================================
-- 13. Sanity-Check: keine produktiven Emails, Einladungscodes oder MFA-Zwang
-- ============================================================================
DO $$
DECLARE
    leaked_count INT;
BEGIN
    SELECT COUNT(*) INTO leaked_count FROM users WHERE email NOT LIKE '%@example.test';
    IF leaked_count > 0 THEN
        RAISE EXCEPTION 'Anonymization failed: % users still have non-stage emails', leaked_count;
    END IF;

    SELECT COUNT(*) INTO leaked_count FROM invite_codes;
    IF leaked_count > 0 THEN
        RAISE EXCEPTION 'Anonymization failed: % invite codes left', leaked_count;
    END IF;

    SELECT COUNT(*) INTO leaked_count FROM app_settings WHERE key = 'mfa_policy' AND value <> 'off';
    IF leaked_count > 0 THEN
        RAISE EXCEPTION 'Anonymization failed: mfa_policy is not off';
    END IF;
END $$;

COMMIT;

-- Optimieren nach Bulk-Updates
VACUUM ANALYZE;

\echo 'Stage anonymization complete. All users now have @example.test emails. Stage login password: stage123'
