"""
Предохранители образа: заголовки безопасности Apache, скрытая версия,
пароль администратора не в аргументах, сайт не владельцем базы; на
боевой машине сайта нет пароля владельца базы.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .pg_admin import КОРЕНЬ

APACHE = (КОРЕНЬ / "docker/apache-python.conf").read_text()
ЗАПУСК = (КОРЕНЬ / "docker/render-entrypoint.sh").read_text()


def test_заголовки_безопасности():
    for строка in (
        'Header set X-Content-Type-Options "nosniff"',
        'Header set X-Frame-Options "SAMEORIGIN"',
        "Header set Strict-Transport-Security",
    ):
        assert строка in APACHE


def test_загрузки_без_скриптов():
    блок = APACHE[APACHE.index('<Location "/storage/">') :]
    блок = блок[: блок.index("</Location>")]

    assert "sandbox" in блок and "default-src 'none'" in блок


def test_версия_apache_не_видна():
    assert "ServerTokens Prod" in ЗАПУСК and "ServerSignature Off" in ЗАПУСК


def test_пароль_администратора_не_в_аргументах():
    assert '--password "$ADMIN_PASSWORD"' not in ЗАПУСК
    assert "--password-from-env" in ЗАПУСК


def test_боевой_сайт_не_владельцем_базы():
    проверка = '[ -z "${DJANGO_DATABASE_URL:-}" ]'
    assert проверка in ЗАПУСК and "не задан DJANGO_DATABASE_URL" in ЗАПУСК


# ── Пароль владельца базы — только на машине админки (Т13) ──────────

РОЛЬ = "postgresql://savdex_django:p@10.0.1.30:5432/savdex"
ВЛАДЕЛЕЦ = "postgresql://savdex:p@10.0.1.30:5432/savdex"


def выкладка(
    tmp_path: Path, роль: str, db_env: str, *args: str, app_env: str = "APP_KEY=x\n"
) -> subprocess.CompletedProcess[str]:
    """prod-app.sh до первого обращения к Docker: дальше — заглушка «нет образа»."""
    env_dir = tmp_path / "env"
    env_dir.mkdir(parents=True)
    (env_dir / "db.env").write_text(db_env)
    (env_dir / "app.env").write_text(app_env)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n")
    docker.chmod(0o755)

    return subprocess.run(
        ["bash", str(КОРЕНЬ / "deploy/server/prod-app.sh"), "abc123", *args],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SAVDEX_ROLE": роль,
            "SAVDEX_HOME": str(tmp_path),
            "DB_IP": "10.0.1.30",
            "ADMIN_IP": "10.0.1.16",
        },
        capture_output=True,
        text=True,
    )


def test_сайт_не_запускается_с_паролем_владельца(tmp_path: Path):
    итог = выкладка(tmp_path, "web", f"DB_URL={ВЛАДЕЛЕЦ}\nDJANGO_DATABASE_URL={РОЛЬ}\n")

    assert итог.returncode == 1
    assert "db.env на машине сайта — адрес базы с паролем владельца" in итог.stderr
    assert "нет образа" not in итог.stderr


def test_сайт_не_запускается_с_адресом_владельца_в_настройках(tmp_path: Path):
    # Тот же адрес под другим именем — в настройках, перенесённых с Render
    for имя in ("DATABASE_URL", "TARGET_DB_URL"):
        итог = выкладка(
            tmp_path / имя, "web", f"DJANGO_DATABASE_URL={РОЛЬ}\n", app_env=f"{имя}={ВЛАДЕЛЕЦ}\n"
        )

        assert итог.returncode == 1
        assert "app.env на машине сайта — адрес базы с паролем владельца" in итог.stderr


def test_сайт_без_migrate(tmp_path: Path):
    итог = выкладка(tmp_path, "web", f"DJANGO_DATABASE_URL={РОЛЬ}\n", "--migrate")

    assert итог.returncode == 1
    assert "--migrate — только на машине админки" in итог.stderr


def test_сайт_с_ролью_django_и_админка_с_владельцем_идут_дальше(tmp_path: Path):
    # Обе доходят до проверки образа — значит, предохранитель их пропустил
    сайт = выкладка(tmp_path / "web", "web", f"DB_CONNECTION=pgsql\nDJANGO_DATABASE_URL={РОЛЬ}\n")
    админка = выкладка(
        tmp_path / "admin", "admin", f"DB_URL={ВЛАДЕЛЕЦ}\nDJANGO_DATABASE_URL={РОЛЬ}\n", "--migrate"
    )

    for итог in (сайт, админка):
        assert итог.returncode == 1
        assert "нет образа savdex:abc123" in итог.stderr
        assert "пароль владельца" not in итог.stderr


def test_машине_сайта_уходит_адрес_без_владельца():
    база = (КОРЕНЬ / "deploy/server/prod-db.sh").read_text()
    сайту = база[база.index('} > "$ENV_DIR/app-db.env"') :]
    сайту = сайту[: сайту.index('} > "$ENV_DIR/web-db.env"')]
    выкладка_yml = (КОРЕНЬ / ".github/workflows/prod.yml").read_text()

    assert "DJANGO_DATABASE_URL=" in сайту and "DB_URL=postgresql://savdex:" not in сайту
    assert "web:web-db.env" in выкладка_yml and "admin:app-db.env" in выкладка_yml
    assert "web:app-db.env" not in выкладка_yml
