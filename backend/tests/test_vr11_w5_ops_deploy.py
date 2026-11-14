"""Vollreview 11/2026, Welle 5 — Fixer «ops»: ``scripts/prod_deploy.sh``.

- R-schemaops-1: ``umask 077`` galt für den ganzen Lauf, also auch für
  ``git pull``. Gepullte Dateien bekamen Modus 600 und waren im Image für den
  Prozess (uid 1000) unlesbar. Nachtrag Welle 6: Das Skript setzt ``umask 022``
  selbst, damit eine strenge umask des Betreiber-Kontos nicht dasselbe bewirkt.
- R-schemaops-2: ``chmod 700`` traf jeden frei gewählten ``BACKUP_DIR``, auch
  einen bestehenden, geteilten Ordner wie ``/tmp``.

Das Skript läuft wirklich, gegen die Attrappen aus ``test_vr11_scripts_shell``.
Der ursprüngliche Befund K155 (Dump 600, eigener Ordner 700) bleibt geprüft.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_vr11_scripts_shell import _mode, _run_deploy

_OLD_DUMP = "prod-pre-deploy-20250101-0000.sql"

# Wie die einfache sudo-Attrappe, leitet aber den Default-Ordner des Skripts in
# ein Testverzeichnis um. Das Skript fasst Ordner und Dump nur über sudo an.
_REDIRECTING_SUDO_STUB = """
args=()
for a in "$@"; do
  case "$a" in /var/backups/openfolio*) a="$STUB_FAKE_ROOT$a";; esac
  args+=("$a")
done
exec "${args[@]}"
"""


def _world_readable_old_dump(directory: Path) -> Path:
    old_dump = directory / _OLD_DUMP
    old_dump.write_text("-- old")
    old_dump.chmod(0o644)
    return old_dump


def _assert_dumps_are_private(directory: Path) -> None:
    dumps = sorted(directory.glob("prod-pre-deploy-*.sql"))
    assert len(dumps) == 2, "ohne BACKUP_KEEP löscht das Skript nichts"
    assert {_mode(d) for d in dumps} == {0o600}
    new_dump = next(d for d in dumps if d.name != _OLD_DUMP)
    assert new_dump.read_text() == "-- dump\n"


@pytest.mark.parametrize("caller_umask", ["022", "077", "027"])
def test_deploy_runs_git_pull_with_umask_022_whatever_the_caller_has(tmp_path, caller_umask):
    """R-schemaops-1: gepullte Dateien behalten die Rechte, die das Image braucht.

    Das Skript setzt ``umask 022`` selbst. Mit der umask des Aufrufers erzeugte
    ein Betreiber-Konto mit 077 oder 027 denselben Fehler wie die frühere
    ``umask 077`` im Skript.
    """
    proc, state, backups = _run_deploy(tmp_path, caller_umask=caller_umask)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (state / "git_pull.umask").read_text().strip() == "0022"
    project = tmp_path / "project"
    assert _mode(project / "backend" / "version.py") == 0o644
    assert _mode(project / "backend" / "alembic" / "versions") == 0o755
    # K155 bleibt behoben, auch mit umask 022.
    assert _mode(backups) == 0o700
    assert {_mode(d) for d in backups.glob("prod-pre-deploy-*.sql")} == {0o600}


def test_deploy_leaves_the_mode_of_an_existing_custom_backup_dir(tmp_path):
    """R-schemaops-2: ``BACKUP_DIR=/tmp`` darf ``/tmp`` nicht auf 700 setzen."""
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o1777)
    _world_readable_old_dump(shared)

    proc, _, _ = _run_deploy(tmp_path, BACKUP_DIR=str(shared))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _mode(shared) == 0o1777
    assert "behält seinen Modus" in proc.stdout
    _assert_dumps_are_private(shared)


def test_deploy_makes_an_existing_default_backup_dir_private(tmp_path):
    """K155: der Default-Ordner besteht auf Prod schon und wird trotzdem 700."""
    fake_root = tmp_path / "fakeroot"
    default_dir = fake_root / "var" / "backups" / "openfolio"
    default_dir.mkdir(parents=True)
    default_dir.chmod(0o755)
    _world_readable_old_dump(default_dir)

    proc, _, _ = _run_deploy(
        tmp_path, sudo_stub=_REDIRECTING_SUDO_STUB, BACKUP_DIR="", STUB_FAKE_ROOT=str(fake_root),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Backup OK: /var/backups/openfolio/prod-pre-deploy-" in proc.stdout
    assert "behält seinen Modus" not in proc.stdout
    assert _mode(default_dir) == 0o700
    _assert_dumps_are_private(default_dir)
