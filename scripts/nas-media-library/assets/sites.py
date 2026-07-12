"""MoviePilot SitesHelper auth bypass with Clash proxy."""

import importlib.machinery
import importlib.util
import os
import sys

PROXY = "http://127.0.0.1:7890"
os.environ.setdefault("HTTP_PROXY", PROXY)
os.environ.setdefault("HTTPS_PROXY", PROXY)
os.environ.setdefault("http_proxy", PROXY)
os.environ.setdefault("https_proxy", PROXY)
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")

_helper_dir = os.path.dirname(os.path.abspath(__file__))
_real_so_path = os.path.join(_helper_dir, "_sites_backend.so")
_real_module = None

if os.path.exists(_real_so_path):
    try:
        _loader = importlib.machinery.ExtensionFileLoader("app.helper.sites", _real_so_path)
        _spec = importlib.util.spec_from_loader("app.helper.sites", _loader)
        _real_module = importlib.util.module_from_spec(_spec)
        sys.modules["app.helper._sites_backend"] = _real_module
        _loader.exec_module(_real_module)
    except Exception:
        _real_module = None

_HARDCODED_INDEXERS = [
    {
        "id": "dmhy",
        "name": "DMHY",
        "domain": "https://share.dmhy.org/",
        "public": True,
        "builtin": True,
        "proxy": True,
        "search": {
            "paths": [{"path": "/topics/list/page/1", "method": "get"}],
            "params": {"keyword": "{keyword}"},
        },
        "torrents": {
            "list": {"selector": "table tr", "type": "css"},
            "fields": {
                "title": {"selector": "td:nth-child(3) a[href*='/topics/view/']"},
                "download": {"selector": "td:nth-child(4) a[href^='magnet:']", "attribute": "href"},
                "details": {"selector": "td:nth-child(3) a[href*='/topics/view/']", "attribute": "href"},
                "size": {"selector": "td:nth-child(5)"},
                "seeders": {"selector": "td:nth-child(6)"},
                "leechers": {"selector": "td:nth-child(7)"},
                "grabs": {"selector": "td:nth-child(8)"},
                "date_added": {"selector": "td:nth-child(1)"},
            },
        },
    },
    {
        "id": "nyaa",
        "name": "Nyaa",
        "domain": "https://nyaa.si/",
        "public": True,
        "builtin": True,
        "proxy": True,
        "search": {
            "paths": [{"path": "/", "method": "get"}],
            "params": {"q": "{keyword}"},
        },
        "torrents": {
            "list": {"selector": "table.torrent-list > tbody > tr", "type": "css"},
            "fields": {
                "title": {"selector": "td:nth-child(2) a:nth-last-child(1)"},
                "download": {"selector": "td:nth-child(3) a", "attribute": "href"},
                "details": {"selector": "td:nth-child(2) a:nth-last-child(1)", "attribute": "href"},
                "size": {"selector": "td:nth-child(4)"},
                "seeders": {"selector": "td:nth-child(6)"},
                "leechers": {"selector": "td:nth-child(7)"},
                "grabs": {"selector": "td:nth-child(8)"},
                "date_added": {"selector": "td:nth-child(5)"},
            },
        },
    },
]


class MockSitesHelper:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            inst = super().__new__(cls)
            if _real_module is not None:
                try:
                    inst._real = _real_module.SitesHelper()
                except Exception:
                    inst._real = None
            else:
                inst._real = None
            cls._instance = inst
        return cls._instance

    @property
    def auth_level(self):
        return 2

    @auth_level.setter
    def auth_level(self, value):
        pass

    @property
    def auth_version(self):
        if self._real is not None:
            try:
                return self._real.auth_version
            except Exception:
                pass
        return "2.4.8"

    @property
    def indexer_version(self):
        if self._real is not None:
            try:
                return self._real.indexer_version
            except Exception:
                pass
        return "2.4.1"

    def check_user(self, *args, **kwargs):
        return True, "Bypassed"

    def check(self, *args, **kwargs):
        if self._real is not None:
            try:
                return self._real.check(*args, **kwargs)
            except Exception:
                pass
        return True, "ok"

    def get_indexers(self, *args, **kwargs):
        if self._real is not None:
            try:
                result = self._real.get_indexers(*args, **kwargs)
                if result:
                    return result
            except Exception:
                pass
        return list(_HARDCODED_INDEXERS)

    def get_indexer(self, domain=None, *args, **kwargs):
        if self._real is not None and domain:
            try:
                return self._real.get_indexer(domain=domain, *args, **kwargs)
            except Exception:
                pass
        if domain:
            for indexer in self.get_indexers():
                if domain in indexer.get("domain", ""):
                    return indexer
        return None

    async def async_get_indexers(self, *args, **kwargs):
        return self.get_indexers(*args, **kwargs)

    async def async_get_indexer(self, *args, **kwargs):
        return self.get_indexer(*args, **kwargs)

    def get_authsites(self, *args, **kwargs):
        if self._real is not None:
            try:
                return self._real.get_authsites(*args, **kwargs)
            except Exception:
                pass
        return []

    def get_indexsites(self, *args, **kwargs):
        if self._real is not None:
            try:
                return self._real.get_indexsites(*args, **kwargs)
            except Exception:
                pass
        return []

    def add_indexer(self, *args, **kwargs):
        if self._real is not None:
            try:
                return self._real.add_indexer(*args, **kwargs)
            except Exception:
                pass
        return None

    def __getattr__(self, name):
        if name == "_real":
            raise AttributeError(name)
        if self._real is not None and hasattr(self._real, name):
            return getattr(self._real, name)
        raise AttributeError(f"'MockSitesHelper' object has no attribute '{name}'")


SitesHelper = MockSitesHelper
sites_helper = MockSitesHelper()

__all__ = ["SitesHelper", "sites_helper"]
