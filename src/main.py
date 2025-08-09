# src/main.py
from __future__ import annotations
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from src.config.settings import Settings
from src.services.localization_service import LocalizationService
from src.ui.screens.settings_screen import SettingsScreen

class DMApp(App):
    CSS_PATH = None  # themes loaded dynamically

    def __init__(self):
        super().__init__()
        self.settings = Settings.load(Path("settings.json"))
        self.i18n = LocalizationService(self.settings)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    async def on_mount(self) -> None:
        # Load CSS: base + selected theme (with fallback logic)
        await self._apply_theme()
        # Open Settings for now so we can test language/theme stuff
        await self.push_screen(SettingsScreen(self.settings, self.i18n))

    async def _apply_theme(self, name: str | None = None) -> None:
        """Load base.tcss + selected theme file(s)."""
        for css_path in self.settings.resolve_theme_files(name):
            try:
                self.load_css(Path(css_path).read_text(encoding="utf-8"), path=css_path)
            except FileNotFoundError:
                self.console.log(f"[warn] CSS not found: {css_path}")

    async def switch_theme(self, theme_name: str) -> None:
        """Switch theme at runtime; persist only on explicit save in UI."""
        self.settings.theme = theme_name
        await self._apply_theme(theme_name)
        # If you want immediate persistence here, uncomment:
        # self.settings.save()

def main() -> None:
    DMApp().run()

if __name__ == "__main__":
    main()
