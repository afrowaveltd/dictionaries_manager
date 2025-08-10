# src/services/localization_service.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Set

from src.config.settings import Settings

_LANG_FILE_RE = re.compile(r"^([a-z]{2})\.json$", re.IGNORECASE)


@dataclass(frozen=True)
class LanguageInfo:
    code: str
    name: str         # display name (non-native)
    native: str       # native display name
    rtl: bool
    path: Path


class LocalizationService:
    """
    JSON-based localization with flat default dictionary:

    - default_language file maps key -> key
    - target languages map key -> translated value (or missing/empty)

    Fallback order: primary language -> default_language -> key.
    Cache: language dicts are cached; cache is invalidated if the source file mtime changes.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: Dict[str, Dict[str, str]] = {}    # lang -> dict(key->value)
        self._mtimes: Dict[str, float] = {}            # lang -> last known file mtime
        self._runtime_cache: Dict[Tuple[str, str, str], str] = {}  # (text, src, dest) -> translated

    # --- Files & I/O -----------------------------------------------------------

    def _lang_file(self, lang: str) -> Path:
        base = self.settings._abs(self.settings.locales_path)
        return base / f"{lang.lower()}.json"

    def _file_mtime(self, lang: str) -> float:
        fp = self._lang_file(lang)
        try:
            return fp.stat().st_mtime
        except FileNotFoundError:
            return -1.0

    def _load_lang(self, lang: str) -> Dict[str, str]:
        """
        Load language file into cache if:
        - not cached yet, or
        - file mtime changed since last load.
        """
        lang = lang.lower()
        current_mtime = self._file_mtime(lang)
        cached_mtime = self._mtimes.get(lang)

        if lang in self._cache and cached_mtime is not None and cached_mtime == current_mtime:
            return self._cache[lang]

        # (Re)load from disk
        fp = self._lang_file(lang)
        data: Dict[str, str] = {}
        if fp.exists():
            try:
                raw = fp.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                data = parsed if isinstance(parsed, dict) else {}
            except Exception:
                data = {}

        self._cache[lang] = data
        self._mtimes[lang] = current_mtime
        return data

    def _write_lang(self, lang: str, data: Dict[str, str]) -> None:
        fp = self._lang_file(lang)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # Update cache & mtime
        self._cache[lang.lower()] = dict(data)
        self._mtimes[lang.lower()] = self._file_mtime(lang)

    # --- Flat default helpers ---------------------------------------------------

    def ensure_default_key(self, key: str) -> None:
        """
        Ensure default_language dictionary contains key -> key.
        Useful when adding new phrases at runtime.
        """
        dlang = self.settings.default_language.lower()
        d = self._load_lang(dlang)
        if key not in d:
            d[key] = key
            self._write_lang(dlang, d)

    def sync_language_with_default(self, lang: str) -> bool:
        """
        Make sure target `lang` has exactly keys of default_language:
        - remove extra keys
        - add missing keys with empty value ""
        Returns True if changes were made.
        """
        lang = lang.lower()
        src = self._load_lang(self.settings.default_language)
        tgt = self._load_lang(lang)
        changed = False

        # remove extra keys
        for k in list(tgt.keys()):
            if k not in src:
                del tgt[k]
                changed = True

        # add missing keys (empty string ⇒ easy to detect untranslated)
        for k in src.keys():
            if k not in tgt:
                tgt[k] = ""
                changed = True

        if changed:
            self._write_lang(lang, tgt)
        return changed

    def compute_diff_with_default(self, lang: str) -> Tuple[Set[str], Set[str]]:
        """
        Return (missing_keys, extra_keys) for `lang` vs. default_language, without writing anything.
        """
        lang = lang.lower()
        src = self._load_lang(self.settings.default_language)
        tgt = self._load_lang(lang)

        src_keys = set(src.keys())
        tgt_keys = set(tgt.keys())

        missing = src_keys - tgt_keys    # in default, missing in target
        extra = tgt_keys - src_keys      # in target, not in default
        return missing, extra

    # --- Language discovery & cache control ------------------------------------

    def available_languages(self) -> List[LanguageInfo]:
        """
        Discover available languages by listing files in locales/ and
        picking only two-letter codes with '.json' extension.
        """
        base = self.settings._abs(self.settings.locales_path)
        langs: List[LanguageInfo] = []
        if not base.exists():
            return langs

        for p in base.iterdir():
            if not p.is_file():
                continue
            m = _LANG_FILE_RE.match(p.name)
            if not m:
                continue
            code = m.group(1).lower()
            # names & rtl from languages catalog
            name = self.settings.language_display(code, native=False)
            native = self.settings.language_display(code, native=True)
            rtl = self.settings.is_rtl(code)
            langs.append(LanguageInfo(code=code, name=name, native=native, rtl=rtl, path=p))

        # sort by native label (nice UX)
        langs.sort(key=lambda x: (x.native.lower(), x.code))
        return langs

    def refresh_language_cache(self, lang: Optional[str] = None) -> None:
        """
        Invalidate cache for a specific language or for all languages.
        Next access will reload from disk.
        """
        if lang:
            lang = lang.lower()
            self._cache.pop(lang, None)
            self._mtimes.pop(lang, None)
        else:
            self._cache.clear()
            self._mtimes.clear()

    # --- Live translate (for theme descriptions, etc.) --------------------------

    def translate_runtime(self, text: str, src_lang: str, dest_lang: str, translator=None) -> str:
        """
        Live translate (no persistence). First return original if lang same,
        then optional translator; cached in memory.
        """
        src = (src_lang or self.settings.default_language).lower()
        dest = (dest_lang or self.settings.ui_language).lower()
        if src == dest:
            return text

        key = (text, src, dest)
        if key in self._runtime_cache:
            return self._runtime_cache[key]

        if translator is not None:
            try:
                translated = translator.translate(text=text, src=src, dest=dest)  # adapter later
                if isinstance(translated, str) and translated.strip():
                    self._runtime_cache[key] = translated
                    return translated
            except Exception:
                pass

        self._runtime_cache[key] = text
        return text

    # --- Public API -------------------------------------------------------------

    def set_language(self, lang: str) -> None:
        self.settings.ui_language = lang.lower()

    def get(self, key: str, *, lang: Optional[str] = None, fmt: Optional[Dict] = None) -> str:
        """
        Resolve a localized string:
        1) primary language value if present and non-empty
        2) default_language value (== key in flat model)
        3) the key itself
        """
        primary = (lang or self.settings.ui_language).lower()
        default = self.settings.default_language.lower()

        v = self._load_lang(primary).get(key)
        if v:
            return v.format(**fmt) if fmt else v

        dv = self._load_lang(default).get(key)
        if dv:
            return dv.format(**fmt) if fmt else dv

        return key if not fmt else key.format(**fmt)

    def is_rtl(self, lang: Optional[str] = None) -> bool:
        return self.settings.is_rtl(lang)
