"""Vollreview 11/2026 — Shell-Skripte und Stage-Konfiguration.

- K083, X24, K155: ``scripts/prod_deploy.sh``
- K121, K155:      ``init.sh``
- K107:            ``scripts/stage_restore.sh``
- K144, K156:      ``docker-compose.stage.yml``
- K120:            ``.env.stage.example``

Die Skripte laufen hier wirklich (``bash``), aber gegen Attrappen fuer
``docker``, ``sudo``, ``git``, ``curl``, ``openssl`` und ``sleep`` in einem
temporaeren Verzeichnis. Nichts davon beruehrt Docker, das Netz oder das Repo.

Alle Dateien liegen ausserhalb von ``backend/``. Im Test-Container sind sie nur
sichtbar, wenn sie gemountet sind (``./scripts:/scripts``, ``./init.sh:/init.sh``,
``./docker-compose.stage.yml:/docker-compose.stage.yml``,
``./.env.stage.example:/.env.stage.example``). Fehlt eine Datei, wird der Test
uebersprungen.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

# Repo-Root: auf dem Host zwei Ebenen ueber tests/, im Container "/".
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _repo_file(rel: str) -> Path:
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{path} nicht sichtbar (Datei ist nicht in den Container gemountet)")
    return path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _write_stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


_COUNT_FN = """
count() {
    local f="$STUB_STATE/$1.count" n=0
    [ -f "$f" ] && n=$(cat "$f")
    n=$((n + 1)); echo "$n" > "$f"; echo "$n"
}
"""


def _common_stubs(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    _write_stub(bin_dir, "sudo", 'exec "$@"\n')
    _write_stub(bin_dir, "sleep", "exit 0\n")
    _write_stub(bin_dir, "curl", "echo '{\"status\":\"ok\"}'\n")
    return bin_dir, state


def _env(bin_dir: Path, state: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    env["STUB_STATE"] = str(state)
    env.update(extra)
    return env


def _docker_log(state: Path) -> list[str]:
    log = state / "docker.log"
    return log.read_text().splitlines() if log.exists() else []


# ===========================================================================
# scripts/prod_deploy.sh
# ===========================================================================

_DEPLOY_DOCKER_STUB = _COUNT_FN + """
printf '%s\\n' "$(echo "$*" | tr '\\n' ' ')" >> "$STUB_STATE/docker.log"
args="$*"
healthy() { [ -f "$STUB_STATE/healthy" ]; }
case "$args" in
  "compose exec -T db pg_dump"*) echo "-- dump";;
  "compose build backend") ;;
  "compose up -d backend") ;;
  "compose ps -aq backend") echo "cid-backend";;
  "inspect -f"*)
      n=$(count inspect)
      case "${STUB_SCENARIO:-ok}" in
        restart_loop)
          if [ "$n" -ge 2 ]; then echo "restarting starting 1"; else echo "running starting 0"; fi;;
        never_healthy) echo "running unhealthy 0";;
        *)
          if [ "$n" -gt "${STUB_POLLS_UNTIL_HEALTHY:-0}" ]; then
            touch "$STUB_STATE/healthy"; echo "running healthy 0"
          else
            echo "running starting 0"
          fi;;
      esac;;
  "compose logs backend"*) cat "$STUB_STATE/backend.log";;
  "compose exec -T backend alembic heads") echo "102 (head)";;
  # Solange die Migration laeuft, steht in der DB noch der alte Head.
  "compose exec -T db psql"*"SELECT version_num"*) if healthy; then echo "102"; else echo "099"; fi;;
  "compose exec -T db psql"*) ;;
  "compose up -d --build frontend worker") ;;
  "compose ps --format"*) ;;
  "compose exec -T backend python -c"*) echo "0.67.0";;
  "compose logs worker"*) echo "worker log without the scheduler line";;
  *) echo "unexpected docker call: $args" >&2; exit 97;;
esac
"""

_GIT_STUB = """
case "$*" in
  "rev-parse HEAD") if [ -f "$STUB_STATE/pulled" ]; then echo "bbb2222"; else echo "aaa1111"; fi;;
  "pull origin main")
      [ -z "${STUB_GIT_PULL_FAILS:-}" ] || { echo "fatal: unable to access origin" >&2; exit 1; }
      # Ein Pull schreibt in den Arbeitsbaum, mit der umask des Skripts.
      umask > "$STUB_STATE/git_pull.umask"
      mkdir -p backend/alembic/versions
      echo 'APP_VERSION = "0.0.0"' > backend/version.py
      touch "$STUB_STATE/pulled";;
  *) ;;
esac
"""

_MIGRATION_LOG = (
    "backend-1  | Existing database (56 tables). Running migrations...\n"
    "backend-1  | INFO  [alembic.runtime.migration] Running upgrade 099 -> 100, price_cache widen\n"
    "backend-1  | Migrations complete.\n"
    "backend-1  | === Starting: uvicorn main:app ===\n"
)


def _run_deploy(
    tmp_path: Path,
    *,
    backend_log: str = _MIGRATION_LOG,
    env_file: str = "POSTGRES_USER=openfolio\nPOSTGRES_DB=openfolio\n",
    sudo_stub: str | None = None,
    caller_umask: str = "022",
    **extra_env: str,
):
    script = _repo_file("scripts/prod_deploy.sh")
    bin_dir, state = _common_stubs(tmp_path)
    if sudo_stub is not None:
        _write_stub(bin_dir, "sudo", sudo_stub)
    _write_stub(bin_dir, "docker", _DEPLOY_DOCKER_STUB)
    _write_stub(bin_dir, "git", _GIT_STUB)
    (state / "backend.log").write_text(backend_log)

    project = tmp_path / "project"
    project.mkdir()
    (project / "docker-compose.yml").write_text("services: {}\n")
    (project / ".env").write_text(env_file)
    backups = tmp_path / "backups"

    # BACKUP_DIR laesst sich ueber extra_env ersetzen; leer heisst Default des Skripts.
    env = _env(bin_dir, state, **{"BACKUP_DIR": str(backups), "DEPLOY_WAIT_SECONDS": "9", **extra_env})
    # Feste umask: ohne den Fix entstuende der Dump damit weltlesbar (644).
    # caller_umask stellt ein Betreiber-Konto mit strenger umask nach.
    proc = subprocess.run(
        ["bash", "-c", f'umask {caller_umask}; exec bash "$0"', str(script)],
        cwd=project, env=env, capture_output=True, text=True, timeout=120,
    )
    return proc, state, backups


def _assert_rollback_is_usable(output: str) -> None:
    """X24: DROP und CREATE in getrennten Aufrufen, je gegen die DB postgres."""
    lines = output.splitlines()
    drop = [line for line in lines if "DROP DATABASE" in line]
    create = [line for line in lines if "CREATE DATABASE" in line]
    assert len(drop) == 1 and len(create) == 1, output
    assert "CREATE DATABASE" not in drop[0], "DROP und CREATE in einem psql -c sind eine Transaktion"
    for line in (drop[0], create[0]):
        assert "psql -U openfolio -d postgres -c" in line, line
        assert '"openfolio"' in line, line
    restore = [line for line in lines if "prod-pre-deploy-" in line and "psql" in line]
    assert len(restore) == 1, output
    assert "-v ON_ERROR_STOP=1" in restore[0] and "-d openfolio" in restore[0]
    assert restore[0].lstrip().startswith("sudo cat "), "der Dump ist nur fuer root lesbar"
    assert any("git reset --hard aaa1111" in line for line in lines), output


def test_deploy_waits_for_running_migration(tmp_path):
    """K083: der DB-Head wird erst geprueft, wenn das Backend healthy ist."""
    proc, state, _ = _run_deploy(tmp_path, STUB_POLLS_UNTIL_HEALTHY="2")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "=== Deploy erfolgreich ===" in proc.stdout
    assert "Alembic-Head 102 == Code-Head." in proc.stdout
    assert "Running upgrade 099 -> 100" in proc.stdout

    log = _docker_log(state)
    inspects = [i for i, line in enumerate(log) if line.startswith("inspect -f")]
    head_check = next(i for i, line in enumerate(log) if "SELECT version_num" in line)
    assert len(inspects) == 3
    assert inspects[-1] < head_check
    assert any(line.startswith("compose up -d --build frontend worker") for line in log)
    _assert_rollback_is_usable(proc.stdout)


def test_deploy_without_migration_lines_does_not_end_silently(tmp_path):
    """K083: kein Treffer im grep beendete das Skript unter ``set -e`` wortlos."""
    proc, _, _ = _run_deploy(tmp_path, backend_log="backend-1  | INFO: Application startup complete.\n")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Migration OK." in proc.stdout
    assert "=== Deploy erfolgreich ===" in proc.stdout


def test_deploy_ignores_app_errors_after_the_entrypoint(tmp_path):
    """Nur die Ausgabe bis «=== Starting:» zaehlt als Migrationslog."""
    noisy = _MIGRATION_LOG + "backend-1  | ERROR services.cache_service: yfinance timeout\n"
    proc, _, _ = _run_deploy(tmp_path, backend_log=noisy)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FEHLER in Migrationen" not in proc.stdout


def test_deploy_stops_on_migration_error_line(tmp_path):
    broken = (
        "backend-1  | Existing database (56 tables). Running migrations...\n"
        "backend-1  | ERROR [alembic.util.messaging] Can't locate revision identified by '103'\n"
        "backend-1  | === Starting: uvicorn main:app ===\n"
    )
    proc, state, _ = _run_deploy(tmp_path, backend_log=broken)

    assert proc.returncode != 0
    assert "FEHLER in Migrationen" in proc.stdout
    assert not any("frontend worker" in line for line in _docker_log(state))


def test_deploy_failure_prints_rollback_instructions(tmp_path):
    """K083: die Anleitung erschien nur nach einem erfolgreichen Lauf."""
    proc, state, _ = _run_deploy(tmp_path, STUB_SCENARIO="restart_loop")

    assert proc.returncode != 0
    assert "=== Deploy erfolgreich ===" not in proc.stdout
    assert "=== Deploy abgebrochen" in proc.stdout
    assert "neu gestartet" in proc.stdout
    _assert_rollback_is_usable(proc.stdout)
    # Kein Head-Vergleich und kein Frontend-/Worker-Start nach dem Abbruch.
    log = _docker_log(state)
    assert not any("SELECT version_num" in line for line in log)
    assert not any("frontend worker" in line for line in log)


def test_deploy_gives_up_after_the_wait_timeout(tmp_path):
    proc, state, _ = _run_deploy(tmp_path, STUB_SCENARIO="never_healthy")

    assert proc.returncode != 0
    assert "nach 9s nicht healthy" in proc.stdout
    assert "=== Deploy abgebrochen" in proc.stdout
    # «unhealthy» allein bricht nicht ab: gepollt wird bis zum Timeout.
    assert sum(line.startswith("inspect -f") for line in _docker_log(state)) == 4


def test_deploy_failure_before_backend_start_does_not_suggest_a_restore(tmp_path):
    """Scheitert schon der Pull, ist die Datenbank unberuehrt: kein DROP in der Anleitung."""
    proc, state, _ = _run_deploy(tmp_path, STUB_GIT_PULL_FAILS="1")

    assert proc.returncode != 0
    assert "=== Deploy abgebrochen" in proc.stdout
    assert "die Datenbank ist unverändert" in proc.stdout
    assert "git reset --hard aaa1111" in proc.stdout
    assert "DROP DATABASE" not in proc.stdout
    assert not any(line.startswith("compose up") for line in _docker_log(state))


def test_deploy_reports_missing_database_settings(tmp_path):
    """Ohne Treffer endete das Skript vor seiner eigenen Fehlermeldung."""
    proc, state, _ = _run_deploy(tmp_path, env_file="JWT_SECRET=x\n")

    assert proc.returncode == 1
    assert "POSTGRES_USER oder POSTGRES_DB nicht in .env gefunden" in proc.stdout
    assert _docker_log(state) == []


def test_deploy_backup_is_private(tmp_path):
    """K155: Dump 600, und ein Ordner, den das Skript anlegt, 700.

    Bestehende Ordner und Dumps frueherer Laeufe: ``test_vr11_w5_ops_deploy.py``
    (R-schemaops-2). Einen bestehenden, frei gewaehlten Ordner setzt das Skript
    nicht mehr auf 700.
    """
    proc, _, backups = _run_deploy(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _mode(backups) == 0o700
    dumps = sorted(backups.glob("prod-pre-deploy-*.sql"))
    assert len(dumps) == 1
    assert _mode(dumps[0]) == 0o600
    assert dumps[0].read_text() == "-- dump\n"


def test_deploy_rotation_is_opt_in(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    for stamp in ("20250101-0000", "20250102-0000", "20250103-0000"):
        (backups / f"prod-pre-deploy-{stamp}.sql").write_text("-- old")
    other = backups / "pre-reattr-20250101-0000.sql"
    other.write_text("-- other backup")

    proc, _, _ = _run_deploy(tmp_path, BACKUP_KEEP="2")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    remaining = sorted(p.name for p in backups.glob("prod-pre-deploy-*.sql"))
    assert len(remaining) == 2
    assert remaining[0] == "prod-pre-deploy-20250103-0000.sql"  # der neue Dump sortiert dahinter
    assert other.exists(), "fremde Dateien im Backup-Verzeichnis bleiben"
    assert proc.stdout.count("Alter Dump entfernt") == 2


# ===========================================================================
# init.sh
# ===========================================================================

_INIT_DOCKER_STUB = """
echo "$*" >> "$STUB_STATE/docker.log"
case "$*" in
  "compose version"|"info") ;;
  "volume inspect"*) exit 1;;
  "compose build --quiet"|"compose up -d") ;;
  "compose exec -T db sh -c"*) echo "${STUB_ADMIN_COUNT:-1}";;
  *) echo "unexpected docker call: $*" >&2; exit 97;;
esac
"""

_VALID_PASSWORD = "Valid-Passw0rd-123!"


def _run_init(tmp_path: Path, stdin: str, *, existing_env: str | None = None, **extra_env: str):
    script = _repo_file("init.sh")
    bin_dir, state = _common_stubs(tmp_path)
    _write_stub(bin_dir, "docker", _INIT_DOCKER_STUB)
    _write_stub(bin_dir, "openssl", 'echo "c3R1Yi1zZWNyZXQtZm9yLXRlc3Rz"\n')
    _write_stub(bin_dir, "ss", "exit 0\n")

    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(script, app / "init.sh")
    (app / "docker-compose.yml").write_text("services: {}\n")
    env_file = app / ".env"
    if existing_env is not None:
        env_file.write_text(existing_env)
        env_file.chmod(0o644)

    proc = subprocess.run(
        ["bash", "-c", "umask 022; exec bash init.sh"],
        cwd=app, env=_env(bin_dir, state, **extra_env),
        input=stdin, capture_output=True, text=True, timeout=120,
    )
    return proc, env_file, state


def _fresh_answers(password: str, email: str = "admin@example.test") -> str:
    # E-Mail, Passwort, Bestaetigung, zwei Ports mit Vorgabewert.
    return f"{email}\n{password}\n{password}\n\n\n"


@pytest.mark.parametrize("password", ["Sup3r$ecret!Pass#1x", "Abc def #Xy12345!", 'Back\\slash"Dq${HOME}9!'])
def test_init_writes_admin_password_literally(tmp_path, password):
    """K121: ohne Quotes ersetzte Compose ``$name`` und schnitt ab `` #`` ab."""
    proc, env_file, _ = _run_init(tmp_path, _fresh_answers(password), STUB_ADMIN_COUNT="0")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = env_file.read_text().splitlines()
    assert f"ADMIN_PASSWORD='{password}'" in lines
    # Kein Admin in der DB: das Passwort bleibt stehen, und das Skript sagt es.
    assert "Admin fehlt" in proc.stdout


def test_init_rejects_single_quote_in_password(tmp_path):
    bad = "It's-Secret-123!"
    stdin = f"admin@example.test\n{bad}\n{_VALID_PASSWORD}\n{_VALID_PASSWORD}\n\n\n"
    proc, env_file, _ = _run_init(tmp_path, stdin, STUB_ADMIN_COUNT="0")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "einfaches Anführungszeichen" in proc.stderr
    assert f"ADMIN_PASSWORD='{_VALID_PASSWORD}'" in env_file.read_text().splitlines()


def test_init_env_file_is_private(tmp_path):
    """K155: auch eine alte, weltlesbare .env wird beim Ueberschreiben auf 600 gesetzt."""
    stdin = "j\n" + _fresh_answers(_VALID_PASSWORD)
    proc, env_file, _ = _run_init(
        tmp_path, stdin, existing_env="POSTGRES_PASSWORD=old\n", STUB_ADMIN_COUNT="0"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _mode(env_file) == 0o600
    assert "JWT_SECRET=" in env_file.read_text()


def test_init_removes_admin_password_once_the_admin_exists(tmp_path):
    """K155: das Klartext-Passwort blieb dauerhaft in der .env stehen."""
    proc, env_file, _ = _run_init(tmp_path, _fresh_answers(_VALID_PASSWORD), STUB_ADMIN_COUNT="1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    content = env_file.read_text()
    assert "ADMIN_PASSWORD=" not in content
    assert _VALID_PASSWORD not in content
    for key in ("ADMIN_EMAIL=admin@example.test", "JWT_SECRET=", "ENCRYPTION_KEY=", "POSTGRES_PASSWORD=", "BACKEND_PORT=8000"):
        assert key in content
    assert _mode(env_file) == 0o600
    assert not (env_file.parent / ".env.tmp").exists()
    assert "wurde aus der .env entfernt" in proc.stdout


def test_init_reports_the_admin_account_it_created(tmp_path):
    """Drei Zahlen: Admins gesamt, aktive Admins, aktive Admins mit ADMIN_EMAIL."""
    proc, env_file, state = _run_init(tmp_path, _fresh_answers(_VALID_PASSWORD), STUB_ADMIN_COUNT="1|1|1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ADMIN_PASSWORD=" not in env_file.read_text()
    assert "der Admin-Account ist angelegt" in proc.stdout
    assert "Anmelden mit:" in proc.stdout
    # Die Adresse geht als Argument an die Shell im Container, nicht in den SQL-Text.
    call = next(
        line for line in (state / "docker.log").read_text().splitlines()
        if line.startswith("compose exec -T db sh -c")
    )
    assert call.endswith(" sh admin@example.test")
    assert "-v email=" in call


def test_init_says_when_the_entered_admin_was_not_used(tmp_path):
    """Nachabnahme: Auf einer bestehenden Installation existiert schon ein aktiver
    Admin mit anderer Adresse. Der Start legt dann kein Konto an. Das Skript
    meldete trotzdem «angelegt» und nannte die neue Adresse zum Anmelden."""
    proc, env_file, _ = _run_init(tmp_path, _fresh_answers(_VALID_PASSWORD), STUB_ADMIN_COUNT="1|1|0")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ADMIN_PASSWORD=" not in env_file.read_text()
    assert "wurden nicht verwendet" in proc.stdout
    assert "der Admin-Account ist angelegt" not in proc.stdout
    assert "Anmelden mit:" not in proc.stdout


def test_init_keeps_the_password_while_only_deactivated_admins_exist(tmp_path):
    """Ohne aktiven Admin läuft der Bootstrap beim nächsten Start noch einmal."""
    proc, env_file, _ = _run_init(tmp_path, _fresh_answers(_VALID_PASSWORD), STUB_ADMIN_COUNT="2|0|0")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"ADMIN_PASSWORD='{_VALID_PASSWORD}'" in env_file.read_text().splitlines()
    assert "Admin fehlt" in proc.stdout


def test_init_leaves_a_kept_env_file_alone(tmp_path):
    existing = "POSTGRES_PASSWORD=old\nADMIN_EMAIL=a@example.test\nADMIN_PASSWORD=Keep-Me-12345!\n"
    proc, env_file, state = _run_init(tmp_path, "n\n", existing_env=existing, STUB_ADMIN_COUNT="1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert env_file.read_text() == existing
    assert not any("exec -T db" in line for line in _docker_log(state))
    assert "ADMIN_PASSWORD aus .env entfernen" in proc.stdout


# ===========================================================================
# scripts/stage_restore.sh
# ===========================================================================

_RESTORE_DOCKER_STUB = _COUNT_FN + """
echo "$*" >> "$STUB_STATE/docker.log"
args="$*"
strict=0
case "$args" in *"ON_ERROR_STOP=1"*) strict=1;; esac
case "$args" in
  *" ps db") echo "openfolio-stage-db   Up 2 minutes (healthy)";;
  *" ps backend") ;;
  *" exec -T db psql "*" -c "*) ;;
  *" exec -T db psql "*)
      n=$(count stdin)
      cat > "$STUB_STATE/stdin-$n.sql"
      # Wie psql: ohne ON_ERROR_STOP endet es trotz Fehler mit 0.
      if [ "$n" = "${STUB_FAIL_STDIN_CALL:-0}" ] && [ "$strict" = 1 ]; then
        echo "ERROR:  stub failure" >&2; exit 3
      fi;;
  *) echo "unexpected docker call: $args" >&2; exit 97;;
esac
"""

_DUMP = (
    "SET statement_timeout = 0;\n"
    "CREATE TABLE public.users (id uuid);\n"
    "ALTER TABLE public.users OWNER TO openfolio;\n"
    'ALTER TYPE public.assettype OWNER TO "prod-role";\n'
    "ALTER SEQUENCE public.price_cache_id_seq OWNER TO openfolio;\n"
    "ALTER TABLE ONLY public.users ADD CONSTRAINT users_pkey PRIMARY KEY (id);\n"
    "COPY public.reports (id, body) FROM stdin;\n"
    "1\tALTER TABLE x OWNER TO y; steht mitten im Text\n"
    "\\.\n"
)

_FORCE_DROP = "DROP DATABASE IF EXISTS finance_stage WITH (FORCE);"


def _run_restore(tmp_path: Path, **extra_env: str):
    script = _repo_file("scripts/stage_restore.sh")
    anonymize = _repo_file("scripts/anonymize_dump.sql")
    bin_dir, state = _common_stubs(tmp_path)
    _write_stub(bin_dir, "docker", _RESTORE_DOCKER_STUB)

    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy(script, project / "scripts" / "stage_restore.sh")
    shutil.copy(anonymize, project / "scripts" / "anonymize_dump.sql")
    (project / ".env.stage").write_text(
        "POSTGRES_USER=finance_stage\nPOSTGRES_DB=finance_stage\nREDIS_PASSWORD=x\n"
    )
    dump = tmp_path / "prod.sql"
    dump.write_text(_DUMP)

    proc = subprocess.run(
        ["bash", str(project / "scripts" / "stage_restore.sh"), str(dump)],
        cwd=tmp_path, env=_env(bin_dir, state, **extra_env),
        capture_output=True, text=True, timeout=120,
    )
    return proc, state, anonymize


def test_restore_success_runs_both_steps_strictly(tmp_path):
    proc, state, anonymize = _run_restore(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Stage restore complete." in proc.stdout
    log = _docker_log(state)
    stdin_calls = [line for line in log if " exec -T db psql " in line and " -c " not in line]
    assert len(stdin_calls) == 2
    assert all("-v ON_ERROR_STOP=1" in line for line in stdin_calls)
    assert all("-p openfolio-stage" in line for line in log)
    assert not any("WITH (FORCE)" in line for line in log)
    assert (state / "stdin-2.sql").read_text() == anonymize.read_text()

    # Eigentuemer-Zeilen fallen weg (die Rolle der Quell-DB fehlt auf Stage), der
    # Rest des Dumps bleibt Byte fuer Byte.
    restored = (state / "stdin-1.sql").read_text()
    expected = "".join(
        line for line in _DUMP.splitlines(keepends=True)
        if not (line.startswith("ALTER ") and " OWNER TO " in line)
    )
    assert restored == expected
    assert "OWNER TO y; steht mitten im Text" in restored


def test_restore_drops_stage_db_when_anonymization_fails(tmp_path):
    """K107: das Skript meldete Erfolg, obwohl die Anonymisierung zurueckrollte."""
    proc, state, _ = _run_restore(tmp_path, STUB_FAIL_STDIN_CALL="2")

    assert proc.returncode != 0
    assert "Stage restore complete." not in proc.stdout
    log = _docker_log(state)
    anonymize_call = max(i for i, line in enumerate(log) if " -c " not in line and " psql " in line)
    force_drops = [i for i, line in enumerate(log) if _FORCE_DROP in line]
    assert len(force_drops) == 1 and force_drops[0] > anonymize_call
    assert "-d postgres" in log[force_drops[0]]
    assert "Stage DB dropped" in proc.stderr


def test_restore_drops_stage_db_when_the_restore_fails(tmp_path):
    proc, state, _ = _run_restore(tmp_path, STUB_FAIL_STDIN_CALL="1")

    assert proc.returncode != 0
    assert "Stage restore complete." not in proc.stdout
    assert not (state / "stdin-2.sql").exists(), "nach einem Restore-Fehler laeuft keine Anonymisierung"
    assert sum(_FORCE_DROP in line for line in _docker_log(state)) == 1


# ===========================================================================
# docker-compose.stage.yml und .env.stage.example
# ===========================================================================

def _stage_compose() -> tuple[str, dict]:
    import yaml

    raw = _repo_file("docker-compose.stage.yml").read_text(encoding="utf-8")
    return raw, yaml.safe_load(raw)


def test_stage_compose_has_its_own_project_name_and_image():
    """K144: ohne eigenen Namen ersetzte Stage die Container db und redis des Hauptstacks."""
    raw, compose = _stage_compose()

    assert compose["name"] == "openfolio-stage"
    images = {compose["services"][svc]["image"] for svc in ("backend", "worker")}
    assert images == {"openfolio-backend-stage"}

    commands = [line for line in raw.splitlines() if line.startswith("#") and "docker-compose.stage.yml up" in line]
    assert commands, "Kopfkommentar nennt den Startbefehl"
    assert all("-p openfolio-stage" in line for line in commands)
    for script in ("scripts/stage_restore.sh", "scripts/stage_smoke.sh"):
        assert "docker compose -p openfolio-stage " in _repo_file(script).read_text(encoding="utf-8")


def test_stage_compose_shares_the_import_volume():
    """K156: Backend schreibt die Uploads, der Worker raeumt sie auf."""
    _, compose = _stage_compose()

    def _imports_source(service: str) -> str:
        mounts = [v for v in compose["services"][service].get("volumes", []) if v.endswith(":/app/data/imports")]
        assert len(mounts) == 1, f"{service}: {mounts}"
        return mounts[0].split(":", 1)[0]

    source = _imports_source("backend")
    assert source == _imports_source("worker")
    assert source in compose["volumes"]
    # Fester Name: unabhaengig vom Projektnamen nie das Volume des Hauptstacks.
    assert compose["volumes"][source]["name"] == "openfolio_import_uploads_stage"


def _assert_bootstrap_password_is_usable(password: str) -> None:
    from services.auth_service import validate_password

    assert validate_password(password) == []
    # Compose ersetzt $name und schneidet ab " #" ab.
    assert "$" not in password and " #" not in password and "'" not in password


def test_stage_env_example_admin_password_passes_the_password_rule():
    """K120: mit ``stage123`` legte das Backend auf einer leeren Stage-DB keinen Admin an."""
    text = _repo_file(".env.stage.example").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")
    )
    _assert_bootstrap_password_is_usable(values["ADMIN_PASSWORD"])
    assert "stage123" in text, "das Passwort nach dem Restore bleibt dokumentiert"


def test_stage_compose_default_admin_password_passes_the_password_rule():
    raw, _ = _stage_compose()
    default = re.search(r"ADMIN_PASSWORD: \$\{ADMIN_PASSWORD:-([^}]+)\}", raw)
    assert default
    _assert_bootstrap_password_is_usable(default.group(1))


def test_stage_smoke_logs_in_with_the_documented_password():
    smoke = _repo_file("scripts/stage_smoke.sh").read_text(encoding="utf-8")
    assert '"email":"admin@example.test","password":"stage123"' in smoke
    assert "FROM invite_codes" in smoke
