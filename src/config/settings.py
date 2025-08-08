import json
from pathlib import Path
from typing import Any, Dict, List, Type

from app.services.auth_service import AuthService
from app.config.plugin_loader import PluginLoader
from app.backends.base import Plugin 
from app.security.crypto_utils import decrypt, encrypt

class ConfigError(Exception):
    """Custom exception for configuration errors."""
    pass

class ConfigManager:
    def __init__(self, path: Path, master_key: bytes):
        self.path = path
        self.master_key = master_key
        self._raw: Dict[str, Any] = {}
        self._plugins: Dict[str, Plugin] = {}

    def load(self) -> None:
        if not self.path.exists():
            raise ConfigError(f"Configuration file {self.path} does not exist.")
        with open(self.path, 'r', encoding='utf-8') as f:
            self._raw = json.load(f)

            # Decript sensitive fields in-place
            self._decrypt_secrets()

            # Validate high level structure
            self._validate_structure()

            # Load plugins
            self._load_plugins()

    def _decrypt_secrets(self) -> None:
        # Goes through all fields starting with "<encrypted>" and decrypts them
        def recurse(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and v.startswith("<encrypted>"):
                        ciphertext = v[len("<encrypted>"):]
                        obj[k] = decrypt(ciphertext, self.master_key)
                    else:
                        recurse(v)
            if isinstance(obj, list):
                for item in obj:
                    recurse(item)
        recurse(self._raw)

    def _validate_structure(self) -> None:
        # Simple checks
        if 'auth' not in self._raw:
            raise ConfigError("Missing 'auth' section in configuration.")
        if 'backends' not in self._raw:
            raise ConfigError("Missing 'backends' section in configuration.")
        
    def _load_plugins(self) -> None:
        loader = PluginLoader()
        # backends
        for name, cfg in self._raw.get('backends', {}).items():
            plugin = loader.load('backend', name, cfg)
            self._plugins[name] = plugin
        # translators, middleware, communication 

    def get_plugin(self, name: str) -> Plugin:
        try:
            return self._plugins[name]
        except KeyError:
            raise ConfigError(f"Plugin {name} not found.")
        
    def list_plugins(self, type: str) -> List[str]:
        return [name for name, plugin in self._plugins.items() if  plugin.__class__.__module__.endswith(type)]