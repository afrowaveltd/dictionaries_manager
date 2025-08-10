# src/ui/screens/settings_screen.py
from __future__ import annotations
from typing import List, Tuple, Optional

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static, Select, Button
from textual.containers import Vertical, Horizontal

from src.config.settings import Settings
from src.services.localization_service import LocalizationService


class LanguageSelect(Select[str]):
    """Select that refreshes options from locales/ when focused or clicked."""

    def __init__(self, i18n: LocalizationService):
        # Be compatible with multiple Textual versions:
        try:
            super().__init__(options=[])
        except TypeError:
            super().__init__([])  # very old signature
        self.i18n = i18n
        if hasattr(self, "prompt"):
            try:
                self.prompt = "Select language…"
            except Exception:
                pass

    async def refresh_options(self) -> None:
        langs = self.i18n.available_languages()
        items: List[Tuple[str, str]] = [(f"{l.native} ({l.code})", l.code) for l in langs]

        # Fallback when locales/ is empty: offer ui/fallback/default languages
        if not items:
            app = getattr(self, "app", None)
            if app and hasattr(app, "settings"):
                candidates = [
                    app.settings.ui_language,         # type: ignore[attr-defined]
                    app.settings.fallback_language,   # type: ignore[attr-defined]
                    app.settings.default_language,    # type: ignore[attr-defined]
                ]
                seen = set()
                fb_items: List[Tuple[str, str]] = []
                for code in candidates:
                    code = (code or "").lower()
                    if code and code not in seen:
                        seen.add(code)
                        try:
                            label = app.settings.language_display(code)  # type: ignore[attr-defined]
                        except Exception:
                            label = code
                        fb_items.append((f"{label} ({code})", code))
                if fb_items:
                    items = fb_items

        self.set_options(items)

    async def on_focus(self, event) -> None:
        await self.refresh_options()

    async def on_click(self, event) -> None:
        await self.refresh_options()


class SettingsScreen(Screen):
    """Minimal settings screen with language selection."""
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, settings: Settings, i18n: LocalizationService):
        super().__init__()
        self.settings = settings
        self.i18n = i18n
        self._status = Static("")  # status line
        self._hint = Static("", id="hint")  # small hint/warning
        self.lang_select = LanguageSelect(self.i18n)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Settings", id="title"),
            Static("Language", id="section-title"),
            Horizontal(
                self.lang_select,
                Button("Apply (no save)", id="apply"),
                Button("Save", id="save"),
                classes="row",
            ),
            self._hint,
            self._status,
            id="content",
        )

    async def on_mount(self) -> None:
        await self.lang_select.refresh_options()
        # Try to preselect current language if present among options
        try:
            self.lang_select.value = self.settings.ui_language
        except Exception:
            pass
        self._update_status()

    def _update_status(self) -> None:
        rtl = self.i18n.is_rtl(self.settings.ui_language)
        # diagnostics: how many languages we see in locales/
        langs = self.i18n.available_languages()
        n = len(langs)
        locales_path = str(self.settings._abs(self.settings.locales_path))
        self._status.update(
            f"UI: {self.settings.ui_language} | RTL: {rtl} | write_protection: {self.settings.write_protection} "
            f"| locales: {n} @ {locales_path}"
        )
        if n == 0:
            self._hint.update("No language files found in 'locales/'. Create e.g. locales/en.json and locales/cs.json.")
        else:
            self._hint.update("")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            chosen = self.lang_select.value or self.settings.ui_language
            self.settings.ui_language = chosen
            self._update_status()
            self.app.bell()
        elif event.button.id == "save":
            chosen = self.lang_select.value or self.settings.ui_language
            self.settings.ui_language = chosen
            self.settings.save()
            self._update_status()
            self.app.bell()
