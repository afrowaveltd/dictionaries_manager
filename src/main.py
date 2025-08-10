# src/main.py
from __future__ import annotations
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from src.config.settings import Settings
from src.services.localization_service import LocalizationService
from src.ui.screens.settings_screen import SettingsScreen


class DMApp(App):
    """Main Textual application."""
    CSS_PATH = None  # themes loaded dynamically

    def __init__(self):
        super().__init__()
        # Load settings relative to project root (settings.json location)
        self.settings = Settings.load(Path("settings.json"))
        self.i18n = LocalizationService(self.settings)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    async def on_mount(self) -> None:
        # Load CSS: base + selected theme (with fallback logic)
        await self._apply_theme()
        # For now, open Settings so we can test language/theme stuff
        await self.push_screen(SettingsScreen(self.settings, self.i18n))

    async def _apply_theme(self, name: str | None = None) -> None:
        """Load base.tcss + selected theme file(s) with best-effort compatibility across Textual versions."""
        files = self.settings.resolve_theme_files(name)
        self.console.log(f"[debug] applying CSS files: {files}")
        for css_path in files:
            p = Path(css_path)
            if not p.exists():
                self.console.log(f"[warn] CSS not found (abs): {p} | cwd={Path.cwd()}")
                continue
            css_text = p.read_text(encoding="utf-8")

            # Try modern API: load_css(css_text, path=...)
            try:
                self.load_css(css_text, path=str(p))  # newer Textual
                continue
            except Exception as e1:
                # Fallback 1: old API: load_css("path/to.css")
                try:
                    self.load_css(str(p))  # older Textual
                    continue
                except Exception as e2:
                    # Fallback 2: set_css(css_text)
                    try:
                        self.set_css(css_text)  # very old Textual
                        continue
                    except Exception as e3:
                        self.console.log(
                            f"[warn] Unable to apply CSS ({css_path}): {e1} | {e2} | {e3}"
                        )

    async def switch_theme(self, theme_name: str) -> None:
        """Switch theme at runtime; persist only on explicit save in UI."""
        self.settings.theme = theme_name
        await self._apply_theme(theme_name)
        # Optionally persist here:
        # self.settings.save()


def main() -> None:
    DMApp().run()


if __name__ == "__main__":
    main()
