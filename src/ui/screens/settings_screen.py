# src/ui/screens/settings_screen.py
from __future__ import annotations
from typing import List, Tuple

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static, Select, Button
from textual.containers import Vertical, Horizontal

from src.config.settings import Settings
from src.services.localization_service import LocalizationService

class LanguageSelect(Select[str]):
    """Select that refreshes options from locales/ when focused or opened."""
    def __init__(self, i18n: LocalizationService, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.i18n = i18n

    async def refresh_options(self) -> None:
        langs = self.i18n.available_languages()
        items: List[Tuple[str, str]] = [(f"{l.native} ({l.code})", l.code) for l in langs]
        # Fallback: ensure current UI language is at least present
        cur = self.app.settings.ui_language
        if cur and all(code != cur for _, code in items):
            items.insert(0, (f"{self.app.settings.language_display(cur)} ({cur})", cur))
        self.set_options(items)

    async def on_focus(self, event) -> None:
        await self.refresh_options()

    async def on_click(self, event) -> None:
        # Some Textual versions don't have a specific "opened" event; refresh on click, too.
        await self.refresh_options()


class SettingsScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, settings: Settings, i18n: LocalizationService):
        super().__init__()
        self.settings = settings
        self.i18n = i18n

        self._status = Static("")  # status line

        # Controls (constructed in compose)
        self.lang_select = LanguageSelect(self.i18n, prompt="Select language…", allow_blank=False)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Settings", id="title"),
            Static("Language", id="section-title"),
            Horizontal(
                self.lang_select,
                Button("Apply (no save)", id="apply"),
                Button("Save", id="save"),    # explicit save to disk (with confirmation later)
                classes="row",
            ),
            self._status,
            id="content",
        )

    async def on_mount(self) -> None:
        # Pre-select current UI language; don't write anything.
        await self.lang_select.refresh_options()
        self.lang_select.value = self.settings.ui_language
        self._update_status()

    def _update_status(self) -> None:
        rtl = self.i18n.is_rtl(self.settings.ui_language)
        self._status.update(
            f"UI: {self.settings.ui_language} | RTL: {rtl} | write_protection: {self.settings.write_protection}"
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            # Apply in-memory only; do not persist
            chosen = self.lang_select.value or self.settings.ui_language
            self.settings.ui_language = chosen
            self._update_status()
            # Optional: play a bell or show a small notice
            self.app.bell()

        elif event.button.id == "save":
            # Explicit write; you can add a confirmation dialog later based on write_protection
            chosen = self.lang_select.value or self.settings.ui_language
            self.settings.ui_language = chosen
            self.settings.save()
            self._update_status()
            self.app.bell()
