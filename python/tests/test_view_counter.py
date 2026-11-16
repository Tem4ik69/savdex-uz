"""Н22: предел засчитанных просмотров в час с одного посетителя."""

from __future__ import annotations

from types import SimpleNamespace

from django.test import RequestFactory

from savdex.web import view_counter

БРАУЗЕР = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0"


def _ctx(user_id: int | None = None, агент: str = БРАУЗЕР) -> SimpleNamespace:
    request = RequestFactory().get("/", HTTP_USER_AGENT=агент, REMOTE_ADDR="198.51.100.9")

    return SimpleNamespace(request=request, visitor=SimpleNamespace(user_id=user_id))


def test_сверх_часового_предела_не_засчитывается(settings, tmp_path, monkeypatch):
    settings.LARAVEL_ROOT = tmp_path
    monkeypatch.setenv("CACHE_STORE", "file")
    monkeypatch.setattr(view_counter, "HOURLY_CAP", 3)
    ctx = _ctx()

    засчитано = [view_counter.should_count(ctx, "tenders", i) for i in range(1, 6)]  # type: ignore[arg-type]

    # Разные страницы: первые три засчитаны, дальше — предел
    assert засчитано == [True, True, True, False, False]
    # Вошедший считается отдельно от гостя с того же адреса
    assert view_counter.should_count(_ctx(user_id=7), "tenders", 9)  # type: ignore[arg-type]


def test_повтор_и_робот(settings, tmp_path, monkeypatch):
    settings.LARAVEL_ROOT = tmp_path
    monkeypatch.setenv("CACHE_STORE", "file")

    assert view_counter.should_count(_ctx(), "resumes", 1)  # type: ignore[arg-type]
    assert not view_counter.should_count(_ctx(), "resumes", 1)  # type: ignore[arg-type]
    assert view_counter.should_count(_ctx(), "it_tasks", 1)  # type: ignore[arg-type]
    assert not view_counter.should_count(_ctx(агент="Googlebot/2.1"), "resumes", 2)  # type: ignore[arg-type]
    assert not view_counter.should_count(_ctx(агент=""), "resumes", 3)  # type: ignore[arg-type]


def test_без_файлового_кэша_считается_всё(monkeypatch):
    monkeypatch.setenv("CACHE_STORE", "array")

    assert view_counter.should_count(_ctx(агент="curl/8"), "tenders", 1)  # type: ignore[arg-type]
