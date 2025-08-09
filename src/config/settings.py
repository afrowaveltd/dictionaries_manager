# src/config/settings.py
from __future__ import annotations

import json
import locale
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional


# ----------------------------
# Helpers for language handling
# ----------------------------

def _normalize_lang(code: Optional[str]) -> str:
    """Return ISO-639-1 lowercased language code (e.g., 'cs' from 'cs_CZ' or 'cs-CZ')."""
    if not code:
        return "en"
    code = code.replace("-", "_")
    base = code.split("_", 1)[0]
    return (base or "en").lower()


def detect_system_language() -> str:
    """Best-effort language autodetection with sensible fallbacks."""
    # 1) locale.getlocale()
    try:
        loc = locale.getlocale()[0]  # e.g., 'cs_CZ'
        if loc:
            return _normalize_lang(loc)
    except Exception:
        pass

    # 2) Environment variables (common on Unix)
    env = os.environ.get("LANG") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
    if env:
        return _normalize_lang(env)

    # 3) Fallback: getdefaultlocale (legacy but still useful)
    try:
        loc = locale.getdefaultlocale()[0]  # type: ignore[call-arg]
        if loc:
            return _normalize_lang(loc)
    except Exception:
        pass

    return "en"


# ---------------------------------
# Language & Country lightweight DBs
# ---------------------------------

class LanguageCatalog:
    """
    Loads languages.json (array of { code, name, native, rtl? }) and exposes quick helpers.
    If the file is missing or invalid, falls back to minimal defaults.
    """

    def __init__(self, languages_path: Path):
        self.path = languages_path
        self.by_code: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            # Minimal fallback: keep it tiny but functional
            self.by_code = {
                "en": {"code": "en", "name": "English", "native": "English", "rtl": 0},
                "cs": {"code": "cs", "name": "Czech", "native": "Česky", "rtl": 0},
                "ar": {"code": "ar", "name": "Arabic", "native": "العربية", "rtl": 1},
            }
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for row in data:
                    code = _normalize_lang(str(row.get("code", "")))
                    if code:
                        self.by_code[code] = {
                            "code": code,
                            "name": row.get("name") or code,
                            "native": row.get("native") or row.get("name") or code,
                            "rtl": 1 if str(row.get("rtl", 0)).lower() in ("1", "true") else 0,
                        }
        except Exception:
            # Keep the minimal fallback if parsing fails
            self.by_code = {
                "en": {"code": "en", "name": "English", "native": "English", "rtl": 0},
            }

    def exists(self, code: str) -> bool:
        return _normalize_lang(code) in self.by_code

    def is_rtl(self, code: str) -> bool:
        row = self.by_code.get(_normalize_lang(code))
        return bool(row and row.get("rtl"))

    def display_name(self, code: str, *, native: bool = True) -> str:
        row = self.by_code.get(_normalize_lang(code))
        if not row:
            return code.lower()
        return str(row["native"] if native else row["name"])

    def all_codes(self) -> List[str]:
        return sorted(self.by_code.keys())


class CountryCatalog:
    """
    Loads countries.json (array of { name, code, dial_code, emoji }) for registration/profile UIs.
    Non-critical if missing.
    """
    def __init__(self, countries_path: Path):
        self.path = countries_path
        self.rows: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.rows = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.rows = data
        except Exception:
            self.rows = []

    def all(self) -> List[Dict[str, Any]]:
        return list(self.rows)


# -----------------------
# Themes metadata support
# -----------------------

_FIRST_COMMENT_RE = re.compile(r"^\s*/\*([\s\S]*?)\*/", re.MULTILINE)
_THEME_FILE_RE = re.compile(r"^(?P<base>[a-z0-9_\-]+?)(?P<custom>\.custom)?\.tcss$", re.IGNORECASE)

@dataclass(frozen=True)
class ThemeInfo:
    name: str        # logical name (base name without .custom)
    path: str        # full path
    kind: str        # "system" | "custom"
    title: str = ""
    description: str = ""
    meta_lang: str = "en"
    author: str = ""
    version: str = ""
    tags: List[str] = None  # type: ignore

    def display_title(self) -> str:
        return self.title or self.name


# -----------------------
# Settings (Singleton API)
# -----------------------

class Settings:
    """
    Singleton settings object with JSON (de)serialization and soft validation.

    - Uses a flat default dictionary model: the 'default_language' file maps key->key.
    - Detects system language on first run, validates it against languages.json.
    - Determines RTL based on languages.json (fallback to small hardcoded map if missing).
    - Collects validation warnings into self.warnings; throws only on unrecoverable issues.
    """

    _instance: ClassVar[Optional["Settings"]] = None

    # ---- Construction ----------------------------------------------------------

    def __init__(self, data: Dict[str, Any], path: Path):
        self._path = path

        self._root = self._path.parent

        def _abs(self, p: str | os.PathLike[str]) -> Path:
            q = Path(p)
            return q if q.is_absolute() else (self._root / q)

        # Buffers for UI diagnostics (soft validation)
        self.warnings: List[str] = []
        self.errors: List[str] = []

        # --- App & file locations (robust) ---
        app_cfg = data.get("app", {}) or {}
        if not isinstance(app_cfg, dict):
            app_cfg = {}

        self.schema_version: int = int(app_cfg.get("schema_version", 1))
        self.locales_path: str = app_cfg.get("locales_path", "locales")
        self.jsons_path: str = app_cfg.get("jsons_path", "jsons")
        self.languages_path: str = app_cfg.get("languages_path", "jsons/languages.json")
        self.countries_path: str = app_cfg.get("countries_path", "jsons/countries.json")

        # Global write protection policy
        self.write_protection: str = app_cfg.get("write_protection", "strict")  # "strict" | "confirm" | "off"

        # Themes (single folder for system+custom)
        self.theme: str = app_cfg.get("theme", "as400")
        self.themes_path: str = app_cfg.get("themes_path", "src/ui/themes")

        # Load catalogs (non-fatal if missing)
        self.languages = LanguageCatalog(Path(self.languages_path))
        self.countries = CountryCatalog(Path(self.countries_path))

        # --- i18n ---
        i18n_cfg = data.get("i18n", {}) or {}
        if not isinstance(i18n_cfg, dict):
            i18n_cfg = {}

        # ui_language: empty → detect at runtime, normalization happens later
        self.ui_language: str = i18n_cfg.get("ui_language", "")
        self.fallback_language: str = i18n_cfg.get("fallback_language", "en")
        # Flat default dictionary: key->key in this language
        self.default_language: str = i18n_cfg.get("default_language", "en")

        # --- Plugin sections (ensure dicts) ---
        self.backends: Dict[str, Any] = data.get("backends", {}) or {}
        if not isinstance(self.backends, dict):
            self.backends = {}

        self.translators: Dict[str, Any] = data.get("translators", {}) or {}
        if not isinstance(self.translators, dict):
            self.translators = {}

        self.middleware: Dict[str, Any] = data.get("middleware", {}) or {}
        if not isinstance(self.middleware, dict):
            self.middleware = {}

        self.communication: Dict[str, Any] = data.get("communication", {}) or {}
        if not isinstance(self.communication, dict):
            self.communication = {}

        # --- Auth (placeholder, real crypto later) ---
        self.auth: Dict[str, Any] = data.get("auth", {}) or {}
        if not isinstance(self.auth, dict):
            self.auth = {}

        # --- First run marker (None means infer later) ---
        fr = data.get("_first_run", None)
        self._first_run: Optional[bool] = fr if isinstance(fr, bool) else None

        # Normalize and validate language settings (sets ui_language if empty)
        self._post_init_language_normalization()

        # Collect soft warnings (do not raise; UI will guide user to fix)
        self._soft_validate()

    # ---- Loading ---------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "Settings":
        """Load once and return singleton instance. Never crashes on missing/empty file; creates defaults."""
        if getattr(cls, "_instance", None) is not None:
            return cls._instance  # type: ignore[attr-defined]

        if not path.exists():
            # First run: sane defaults
            defaults: Dict[str, Any] = {
                "_first_run": True,
                "app": {
                    "schema_version": 1,
                    "locales_path": "locales",
                    "jsons_path": "jsons",
                    "languages_path": "jsons/languages.json",
                    "countries_path": "jsons/countries.json",
                    "theme": "as400",
                    "themes_path": "src/ui/themes",
                    "write_protection": "strict",
                },
                "i18n": {
                    "ui_language": "",           # empty → detect at runtime
                    "fallback_language": "en",
                    "default_language": "en",
                },
                "auth": {},
                "backends": {},
                "translators": {},
                "middleware": {},
                "communication": {},
            }
            inst = cls(defaults, path)
            cls._instance = inst  # type: ignore[attr-defined]
            return inst

        # Safely read JSON; handle empty/invalid content
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                raise ValueError("Empty settings file")
            data = json.loads(raw)
        except Exception as ex:
            defaults = {
                "_first_run": True,
                "app": {
                    "schema_version": 1,
                    "locales_path": "locales",
                    "jsons_path": "jsons",
                    "languages_path": "jsons/languages.json",
                    "countries_path": "jsons/countries.json",
                    "theme": "as400",
                    "themes_path": "src/ui/themes",
                    "write_protection": "strict",
                },
                "i18n": {"ui_language": "", "fallback_language": "en", "default_language": "en"},
                "auth": {},
                "backends": {},
                "translators": {},
                "middleware": {},
                "communication": {},
            }
            inst = cls(defaults, path)
            # keep a visible warning for UI
            inst.warnings.append(
                f"Settings file '{path}' could not be parsed (using in-memory defaults): {ex}"
            )
            cls._instance = inst  # type: ignore[attr-defined]
            return inst

        inst = cls(data, path)
        cls._instance = inst  # type: ignore[attr-defined]
        return inst

    # ---- Themes helpers --------------------------------------------------------

    def _parse_theme_meta(self, css_text: str) -> Dict[str, Any]:
        """
        Parse first comment block. Try JSON first; fallback to @key: value lines.
        Returns dict with keys: title, description, lang, author, version, tags(list)
        """
        m = _FIRST_COMMENT_RE.search(css_text)
        if not m:
            return {}
        block = m.group(1).strip()

        # Try JSON
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                if isinstance(data.get("tags"), str):
                    data["tags"] = [t.strip() for t in data["tags"].split(",")]
                return data
        except Exception:
            pass

        # Fallback @key: value
        meta: Dict[str, Any] = {}
        for line in block.splitlines():
            line = line.strip().lstrip("*").strip()
            if not line or not line.startswith("@"):
                continue
            if ":" in line:
                key, val = line[1:].split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                if key == "tags":
                    meta[key] = [t.strip() for t in val.split(",") if t.strip()]
                else:
                    meta[key] = val
        return meta

    def _scan_themes(self) -> List[ThemeInfo]:
        """Scan themes_path for *.tcss and *.custom.tcss and classify them + read meta."""
        base = Path(self.themes_path)
        results: List[ThemeInfo] = []
        if not base.exists():
            return results
        for p in base.iterdir():
            if not p.is_file():
                continue
            m = _THEME_FILE_RE.match(p.name)
            if not m:
                continue
            base_name = m.group("base").lower()
            kind = "custom" if m.group("custom") else "system"

            # Read and parse meta
            text = ""
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
            meta = self._parse_theme_meta(text)

            results.append(
                ThemeInfo(
                    name=base_name,
                    path=str(p),
                    kind=kind,
                    title=str(meta.get("title", "")),
                    description=str(meta.get("description", "")),
                    meta_lang=str(meta.get("lang", "en")).lower() or "en",
                    author=str(meta.get("author", "")),
                    version=str(meta.get("version", "")),
                    tags=meta.get("tags") if isinstance(meta.get("tags"), list) else [],
                )
            )
        return results

    def available_themes(self) -> List[ThemeInfo]:
        """
        Return a list of themes; if both system and custom exist for the same name,
        custom will be listed first (preferred).
        """
        scanned = self._scan_themes()
        # sort: by name, but prefer custom over system for the same name
        scanned.sort(key=lambda t: (t.name, 0 if t.kind == "custom" else 1))
        # unique by name, prefer first (custom if present)
        seen = set()
        unique: List[ThemeInfo] = []
        for t in scanned:
            if t.name in seen:
                continue
            seen.add(t.name)
            unique.append(t)
        return unique

    def resolve_theme_files(self, name: Optional[str] = None) -> List[str]:
        """
        Resolve CSS load order:
        1) styles/base.tcss
        2) {name}.custom.tcss or {name}.tcss
        Fallback to 'as400' if selected name not found. Last resort: only base.
        """
        name = (name or self.theme or "as400").lower()
        base_css = "src/ui/styles/base.tcss"

        # try custom first
        candidate_custom = Path(self.themes_path) / f"{name}.custom.tcss"
        candidate_system = Path(self.themes_path) / f"{name}.tcss"

        if candidate_custom.exists():
            return [base_css, str(candidate_custom)]
        if candidate_system.exists():
            return [base_css, str(candidate_system)]

        # fallback to as400
        fallback_custom = Path(self.themes_path) / "as400.custom.tcss"
        fallback_system = Path(self.themes_path) / "as400.tcss"
        if fallback_custom.exists():
            return [base_css, str(fallback_custom)]
        if fallback_system.exists():
            return [base_css, str(fallback_system)]

        # last resort: only base
        return [base_css]

    # ---- Validation & normalization -------------------------------------------

    def _post_init_language_normalization(self) -> None:
        """Ensure ui_language is set and valid; if not, detect and/or fallback to 'en'."""
        # Normalize everything
        self.fallback_language = _normalize_lang(self.fallback_language)
        self.default_language = _normalize_lang(self.default_language)

        if not self.ui_language:
            self.ui_language = detect_system_language()

        self.ui_language = _normalize_lang(self.ui_language)

        # If UI language not in catalog, warn and fallback
        if not self.languages.exists(self.ui_language):
            self.warnings.append(
                f"Unknown UI language '{self.ui_language}' - falling back to 'en'."
            )
            self.ui_language = "en"

        # If fallback not in catalog, warn and set to 'en'
        if not self.languages.exists(self.fallback_language):
            self.warnings.append(
                f"Unknown fallback language '{self.fallback_language}' - using 'en'."
            )
            self.fallback_language = "en"

        # If default (flat source) not in catalog, warn and set to 'en'
        if not self.languages.exists(self.default_language):
            self.warnings.append(
                f"Unknown default language '{self.default_language}' - using 'en'."
            )
            self.default_language = "en"

    def _soft_validate(self) -> None:
        """Collect fixable issues as warnings. Only unrecoverable problems should go to errors."""
        # Ensure jsons directory exists lazily (we warn but don't fail)
        jsons_dir = Path(self.jsons_path)
        if not jsons_dir.exists():
            self.warnings.append(
                f"Helper JSONs folder '{self.jsons_path}' does not exist yet. "
                f"It will be created on demand."
            )

        # locales dir existence (warning, we can create later)
        if not Path(self.locales_path).exists():
            self.warnings.append(
                f"Locales path '{self.locales_path}' does not exist yet. "
                f"It will be created on demand."
            )

        # Minimal structure checks
        for sec in ("backends", "translators", "middleware", "communication"):
            if not isinstance(getattr(self, sec), dict):
                self.warnings.append(f"Section '{sec}' should be an object; resetting to empty.")
                setattr(self, sec, {})

        if not isinstance(self.auth, dict):
            self.warnings.append("Section 'auth' should be an object; resetting to empty.")
            self.auth = {}

    # ---- Public API ------------------------------------------------------------

    def save(self) -> None:
        """Serialize to JSON on disk (idempotent)."""
        data: Dict[str, Any] = {
            "app": {
                "schema_version": self.schema_version,
                "locales_path": self.locales_path,
                "jsons_path": self.jsons_path,
                "languages_path": self.languages_path,
                "countries_path": self.countries_path,
                "write_protection": self.write_protection,
                "theme": self.theme,
                "themes_path": self.themes_path,
            },
            "i18n": {
                "ui_language": self.ui_language,
                "fallback_language": self.fallback_language,
                "default_language": self.default_language,
            },
            "auth": self.auth,
            "backends": self.backends,
            "translators": self.translators,
            "middleware": self.middleware,
            "communication": self.communication,
            "_first_run": False,
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def is_first_run(self) -> bool:
        """Infer first-run if marker missing but config is still essentially empty."""
        if self._first_run is None:
            empty = not self.auth and not self.backends and not self.translators and not self.middleware
            return bool(empty)
        return bool(self._first_run)

    # ---- i18n helpers ----------------------------------------------------------

    def is_rtl(self, lang: Optional[str] = None) -> bool:
        """Return True if given (or current UI) language is RTL according to languages.json."""
        code = _normalize_lang(lang or self.ui_language)
        return self.languages.is_rtl(code)

    def language_display(self, code: str, *, native: bool = True) -> str:
        """Return human-friendly language label."""
        return self.languages.display_name(code, native=native)

    # ---- Convenience getters/setters for plugin options -----------------------

    def get_plugin_options(self, category: str, name: str) -> Dict[str, Any]:
        """
        Returns options dict for a plugin (creating the section on demand).
        category: 'backends' | 'translators' | 'middleware' | 'communication'
        """
        if category not in ("backends", "translators", "middleware", "communication"):
            raise ValueError(f"Unknown plugin category: {category}")
        section: Dict[str, Any] = getattr(self, category)
        if name not in section or not isinstance(section[name], dict):
            section[name] = {}
        return section[name]

    def set_plugin_enabled(self, category: str, name: str, enabled: bool) -> None:
        opts = self.get_plugin_options(category, name)
        opts["enabled"] = bool(enabled)

    def plugin_enabled(self, category: str, name: str) -> bool:
        opts = self.get_plugin_options(category, name)
        return bool(opts.get("enabled", False))

    # ---- JSON helpers ----------------------------------------------------------

    def helper_json_path(self, filename: str) -> Path:
        """
        Return a Path to a helper JSON file under the jsons/ folder.
        This is the canonical place for static JSON catalogs used by the app.
        """
        return Path(self.jsons_path) / filename

    # ---- UI guidance -----------------------------------------------------------

    def should_open_settings(self) -> bool:
        """
        Return True if the app should open the Settings screen/wizard early.
        Criteria: first run OR validation warnings present OR known soft errors.
        """
        if self.is_first_run:
            return True
        if self.warnings:
            return True
        if self.errors:
            return True
        return False
