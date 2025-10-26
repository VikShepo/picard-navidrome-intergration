"""
MusicBrainz Picard plugin (single file): Navidrome / Subsonic integration

Adds:
- Options page under Options > Plugins > Navidrome, including:
  * Server base URL, username, password
  * SSL verification toggle
  * Optional "Save credentials" toggle
  * Smart caching system with configurable TTL for faster subsequent fetches
- Subsonic-compatible client for Navidrome with token-based auth (salt + MD5)
- Context menu actions (album/track/file):
  * Fetch Playlists…
  * Browse Navidrome Library…
  * Create playlist and send to Navidrome …
- Playlists browser:
  * Lists server playlists and their tracks
  * Local drag-and-drop reordering of tracks for review
  * Resizable and re-orderable header columns
  * Safe drag/drop behavior with clear visual indicators
- Library browser:
  * Live progress dialog while fetching ("Fetched song X of Y")
  * Smart caching: Second and subsequent fetches are dramatically faster
  * "Filter" button to hide/show columns via checkboxes
  * Search box filtering across visible columns
  * First column shows cleaned file "dataname" (removes prefixes like "NN-NN - ")
  * Columns adjustable (resizable & re-orderable by drag)
  * Rows height-adjustable; local drag-and-drop reordering that does not change server order
  * Create playlist from selected rows; IDs are taken from the table order, unaffected by sorting/reordering
- Review and confirmation dialogs:
  * Preview and finalize playlist order before sending to Navidrome
  * Keep or discard current selection
- Error handling and responsiveness:
  * Clear error messages for network/HTTP/API issues
  * Non-blocking operations with responsive UI and status updates
- Compatibility and settings persistence:
  * Works with PyQt5 or PySide2 in the Picard environment
  * Uses Picard options (TextOption/BoolOption) to persist settings
- Security:
  * Subsonic token authentication; optional SSL verification
  * Option to avoid persisting credentials
- Notes/Limitations:
  * Drag-and-drop reorders locally; server order changes only when creating a new playlist
  * Does not modify or upload audio files; reads metadata and sends playlist definitions only

Tested with PyQt5 / PySide2 style imports used by Picard.

This file is provided as a drop-in replacement for your previous single-file plugin.
"""

# ---- Plugin metadata (required by Picard) ----
PLUGIN_NAME = "Navidrome (Subsonic) Integration"
PLUGIN_AUTHOR = "Viktor Shepotynnyk"
PLUGIN_DESCRIPTION = (
    "Integrates Navidrome (Subsonic) API with Picard: options page (URL, credentials, SSL, caching), "
    "Navidrome menu/actions, playlists and library browsers with Filter, search, adjustable "
    "columns/rows and live progress, smart caching for faster subsequent fetches, local reordering "
    "and playlist creation with a review dialog. Compatibility: Picard API 2.0–2.14; Subsonic 1.16.1+ (Navidrome); Docker Picard supported."
)
PLUGIN_VERSION = "0.7.1"
PLUGIN_API_VERSIONS = [
    "2.0",
    "2.1",
    "2.2",
    "2.3",
    "2.4",
    "2.5",
    "2.6",
    "2.7",
    "2.8",
    "2.9",
    "2.10",
    "2.11",
    "2.12",
    "2.13",
    "2.14",
]

from typing import Dict, List, Optional, Tuple, Callable, Generator, Set
import os
import re
import hashlib
import json
import random
import string
import urllib.parse
import urllib.request
import webbrowser
import time

# Qt bindings (prefer PyQt5, fall back to PySide2)
QMessageBox = None
QCheckBox = None
QFormLayout = None
QLineEdit = None
QWidget = None
QCoreApplication = None
QInputDialog = None
QAbstractItemView = None
QComboBox = None
QProgressBar = None
QToolButton = None
QMenu = None
QAction = None
QTextEdit = None
_QT_LIB = None

try:
    from PyQt5.QtWidgets import (  # type: ignore
        QMessageBox,
        QCheckBox,
        QFormLayout,
        QLineEdit,
        QWidget,
        QApplication,
        QPushButton,
        QDialog,
        QListWidget,
        QListWidgetItem,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QDialogButtonBox,
        QInputDialog,
        QAbstractItemView,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QComboBox,
        QProgressBar,
        QToolButton,
        QMenu,
        QAction,
        QTextEdit,
    )
    from PyQt5.QtCore import QCoreApplication, QTimer, Qt, QEvent, QMimeData, QPoint  # type: ignore
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QDrag, QPen  # type: ignore
    _QT_LIB = "pyqt5"
except Exception:
    try:
        from PySide2.QtWidgets import (  # type: ignore
            QMessageBox,
            QCheckBox,
            QFormLayout,
            QLineEdit,
            QWidget,
            QApplication,
            QPushButton,
            QDialog,
            QListWidget,
            QListWidgetItem,
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QDialogButtonBox,
            QInputDialog,
            QAbstractItemView,
            QTableWidget,
            QTableWidgetItem,
            QHeaderView,
            QComboBox,
            QProgressBar,
            QToolButton,
            QMenu,
            QAction,
            QTextEdit,
        )
        from PySide2.QtCore import QCoreApplication, QTimer, Qt, QEvent, QMimeData, QPoint  # type: ignore
        from PySide2.QtGui import QPixmap, QPainter, QColor, QDrag, QPen  # type: ignore
        _QT_LIB = "pyside2"
    except Exception:  # pragma: no cover
        _QT_LIB = None

# Picard API
from picard import log  # type: ignore
from picard.config import config, BoolOption, TextOption, IntOption  # type: ignore
from picard.ui.options import OptionsPage, register_options_page  # type: ignore

# Safely create options - ignore if already declared
def _safe_create_option(option_class, *args, **kwargs):
    """Safely create an option, ignoring duplicate declaration errors."""
    try:
        return option_class(*args, **kwargs)
    except Exception:
        # Option already exists, return None
        return None
from picard.ui.itemviews import BaseAction, register_album_action, register_track_action  # type: ignore
try:
    from picard.ui.itemviews import register_file_action  # type: ignore
except Exception:
    register_file_action = None  # type: ignore


# -----------------------------
# Navidrome Cache System
# -----------------------------
class NavidromeCache:
    """Simple in-memory cache for Navidrome API responses. Cache persists until manually cleared."""
    
    def __init__(self):
        self._cache: Dict[str, any] = {}  # key -> data
    
    def get(self, key: str) -> Optional[any]:
        """Get cached data if it exists."""
        return self._cache.get(key, None)
    
    def set(self, key: str, data: any) -> None:
        """Store data in cache."""
        self._cache[key] = data
    
    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()


# Global cache instance - shared across all SubsonicClient instances
_global_cache: Optional[NavidromeCache] = None

def _get_global_cache(enable_cache: bool = True) -> Optional[NavidromeCache]:
    """Get or create the global cache instance."""
    global _global_cache
    if not enable_cache:
        return None
    if _global_cache is None:
        _global_cache = NavidromeCache()
    return _global_cache

def _clear_global_cache() -> None:
    """Clear the global cache."""
    global _global_cache
    if _global_cache:
        _global_cache.clear()


# -----------------------------
# Minimal Subsonic API client
# -----------------------------
class SubsonicClient:
    """Minimal Subsonic API client compatible with Navidrome."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        api_version: str = "1.16.1",
        app_name: str = "PicardNavidrome",
        verify_ssl: bool = True,
        timeout_seconds: int = 15,
        enable_cache: bool = True,
    ) -> None:
        if base_url.endswith("/"):
            base_url = base_url[:-1]
        self.base_url = base_url
        self.username = username
        self.password = password
        self.api_version = api_version
        self.app_name = app_name
        self.verify_ssl = verify_ssl
        self.timeout_seconds = timeout_seconds
        
        # Initialize cache - use global cache for persistence across instances
        self.enable_cache = enable_cache
        self.cache = _get_global_cache(enable_cache)
    
    def clear_cache(self) -> None:
        """Clear all cached data."""
        _clear_global_cache()
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get basic cache statistics."""
        if not self.cache:
            return {"enabled": 0, "entries": 0}
        return {"enabled": 1, "entries": len(self.cache._cache)}

    # ---- HTTP helpers ----
    def _auth_params(self) -> Dict[str, str]:
        salt = "".join(random.choices(string.ascii_letters + string.digits, k=12))
        token = hashlib.md5((self.password + salt).encode("utf-8")).hexdigest()
        return {
            "u": self.username,
            "t": token,
            "s": salt,
            "v": self.api_version,
            "c": self.app_name,
            "f": "json",
        }

    def _request(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        method: str = "GET",
        song_ids: Optional[List[str]] = None,
    ) -> Dict:
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        params = params or {}
        all_params = {**self._auth_params(), **params}

        url = f"{self.base_url}{endpoint}"
        request = None
        data_bytes = None

        if method.upper() == "GET":
            qs = urllib.parse.urlencode(all_params, doseq=True)
            url = f"{url}?{qs}"
            request = urllib.request.Request(url, method="GET")
        else:
            # Handle repeated songId parameters (Subsonic expects multiple songId= entries)
            if song_ids:
                param_pairs = [(k, v) for k, v in all_params.items()]
                for sid in song_ids:
                    param_pairs.append(("songId", sid))
                body = urllib.parse.urlencode(param_pairs)
            else:
                body = urllib.parse.urlencode(all_params, doseq=True)
            data_bytes = body.encode("utf-8")
            request = urllib.request.Request(url, data=data_bytes, method="POST")
            request.add_header("Content-Type", "application/x-www-form-urlencoded")

        # SSL context (optional)
        context = None
        if not self.verify_ssl:
            try:
                import ssl
                context = ssl._create_unverified_context()  # type: ignore[attr-defined]
            except Exception:
                context = None

        try:
            with urllib.request.urlopen(request, context=context, timeout=self.timeout_seconds) as response:
                data = response.read().decode("utf-8")
        except Exception as exc:
            raise ValueError(f"HTTP error calling {endpoint}: {exc}")

        try:
            payload = json.loads(data)
        except Exception as exc:
            raise ValueError(f"Invalid JSON from {endpoint}: {exc}")

        if "subsonic-response" not in payload:
            raise ValueError("Unexpected response: missing 'subsonic-response'")
        resp = payload["subsonic-response"]
        if resp.get("status") != "ok":
            error = resp.get("error", {})
            code = error.get("code")
            msg = error.get("message")
            raise ValueError(f"Subsonic error {code}: {msg}")
        return resp

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        return self._request(endpoint, params, method="GET")

    def _post(self, endpoint: str, params: Optional[Dict] = None, song_ids: Optional[List[str]] = None) -> Dict:
        return self._request(endpoint, params, method="POST", song_ids=song_ids)

    # ---- API calls we use ----
    def ping(self) -> bool:
        resp = self._get("/rest/ping.view")
        return resp.get("status") == "ok"

    def get_playlists(self) -> List[Dict]:
        resp = self._get("/rest/getPlaylists.view")
        playlists = resp.get("playlists", {}).get("playlist", [])
        if isinstance(playlists, dict):
            playlists = [playlists]
        return playlists

    def get_playlist_tracks(self, playlist_id: str) -> List[Dict]:
        resp = self._get("/rest/getPlaylist.view", {"id": playlist_id})
        entries = resp.get("playlist", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        return entries

    def create_playlist(self, name: str, song_ids: List[str]) -> Optional[str]:
        """Create a playlist with provided song IDs. Returns playlist id if available."""
        params = {"name": name}
        resp = self._post("/rest/createPlaylist.view", params, song_ids=song_ids)
        pl = resp.get("playlist", {})
        pl_id = str(pl.get("id", "")) if isinstance(pl, dict) else ""
        return pl_id or None

    def update_playlist(self, playlist_id: str, *, name: Optional[str] = None, public: Optional[bool] = None) -> None:
        """Update playlist name or visibility."""
        params = {"playlistId": playlist_id}
        if name is not None:
            params["name"] = name
        if public is not None:
            params["public"] = "true" if public else "false"
        self._post("/rest/updatePlaylist.view", params)

    def delete_playlist(self, playlist_id: str) -> None:
        self._post("/rest/deletePlaylist.view", {"id": playlist_id})

    def search_songs(self, query: str, *, count: int = 10, offset: int = 0) -> List[Dict]:
        params = {"query": query, "songCount": str(count), "songOffset": str(offset)}
        resp = self._get("/rest/search3.view", params)
        songs = resp.get("searchResult3", {}).get("song", [])
        if isinstance(songs, dict):
            songs = [songs]
        return songs

    def get_album_list2(self, *, list_type: str = "alphabeticalByName", size: int = 500, offset: int = 0) -> List[Dict]:
        # Generate cache key based on server URL and parameters
        cache_key = f"{self.base_url}_album_list2_{list_type}_{size}_{offset}"
        
        # Try to get from cache first
        if self.cache:
            cached_albums = self.cache.get(cache_key)
            if cached_albums is not None:
                try:
                    log.debug("Navidrome: Cache HIT for album_list2 %s/%s/%s", list_type, size, offset)
                except Exception:
                    pass
                return cached_albums
        
        # Fetch from API if not cached
        try:
            log.debug("Navidrome: Cache MISS for album_list2 %s/%s/%s - fetching from server", list_type, size, offset)
        except Exception:
            pass
        params = {"type": list_type, "size": str(size), "offset": str(offset)}
        resp = self._get("/rest/getAlbumList2.view", params)
        albums = resp.get("albumList2", {}).get("album", [])
        if isinstance(albums, dict):
            albums = [albums]
        
        # Cache the result
        if self.cache:
            self.cache.set(cache_key, albums)
            try:
                log.debug("Navidrome: Cached album_list2 result (%d albums)", len(albums))
            except Exception:
                pass
        
        return albums

    def get_album(self, album_id: str) -> List[Dict]:
        # Generate cache key based on server URL and album_id
        cache_key = f"{self.base_url}_album_{album_id}"
        
        # Try to get from cache first
        if self.cache:
            cached_songs = self.cache.get(cache_key)
            if cached_songs is not None:
                try:
                    log.debug("Navidrome: Cache HIT for album %s", album_id)
                except Exception:
                    pass
                return cached_songs
        
        # Fetch from API if not cached
        try:
            log.debug("Navidrome: Cache MISS for album %s - fetching from server", album_id)
        except Exception:
            pass
        resp = self._get("/rest/getAlbum.view", {"id": album_id})
        songs = resp.get("album", {}).get("song", [])
        if isinstance(songs, dict):
            songs = [songs]
        
        # Cache the result
        if self.cache:
            self.cache.set(cache_key, songs)
            try:
                log.debug("Navidrome: Cached album result (%d songs)", len(songs))
            except Exception:
                pass
        
        return songs

    # ---- Iterators for library traversal ----
    def iter_all_songs(
        self, *, page_size: int = 500, max_pages: int = 10000
    ) -> List[Dict]:
        collected: List[Dict] = []
        offset = 0
        pages = 0
        while pages < max_pages:
            albums = self.get_album_list2(size=page_size, offset=offset)
            if not albums:
                break
            for album in albums:
                album_id = str(album.get("id", ""))
                if not album_id:
                    continue
                try:
                    songs = self.get_album(album_id)
                    collected.extend(songs)
                except Exception:
                    continue
            if len(albums) < page_size:
                break
            offset += page_size
            pages += 1
        return collected

    def iter_all_songs_stream(
        self,
        *,
        page_size: int = 500,
        max_pages: int = 10000,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> Generator[Dict, None, None]:
        """Yield songs one-by-one; update progress; allow cancel."""
        # First pass: Calculate total song count for accurate progress
        total_songs = 0
        all_albums = []
        offset = 0
        pages = 0
        
        try:
            log.debug("Navidrome: Calculating total songs for accurate progress...")
        except Exception:
            pass
        
        while pages < max_pages:
            if cancel_flag and cancel_flag():
                return
            albums = self.get_album_list2(size=page_size, offset=offset)
            if not albums:
                break
            
            # Count total songs from this page
            page_song_count = 0
            for album in albums:
                sc = album.get("songCount", 0)
                try:
                    page_song_count += int(sc)
                except Exception:
                    pass
            
            total_songs += page_song_count
            all_albums.extend(albums)
            
            if len(albums) < page_size:
                break
            offset += page_size
            pages += 1
        
        try:
            log.debug("Navidrome: Total songs calculated: %d", total_songs)
        except Exception:
            pass
        
        # Initial progress update with correct total
        if progress_cb:
            try:
                progress_cb(0, total_songs)
            except Exception:
                pass
        
        # Second pass: Actually fetch and yield songs
        fetched = 0
        for album in all_albums:
            if cancel_flag and cancel_flag():
                return
            album_id = str(album.get("id", ""))
            if not album_id:
                continue
            try:
                songs = self.get_album(album_id)
            except Exception:
                songs = []
            for s in songs:
                if cancel_flag and cancel_flag():
                    return
                fetched += 1
                if progress_cb:
                    try:
                        progress_cb(fetched, total_songs)
                    except Exception:
                        pass
                yield s

        # Final progress update
        if progress_cb:
            try:
                progress_cb(fetched, total_songs)
            except Exception:
                pass


# -----------------------------
# Options page for Picard
# -----------------------------
class NavidromeOptionsPage(OptionsPage):
    NAME = "navidrome"
    TITLE = "Navidrome"
    PARENT = "plugins"

    options = [opt for opt in [
        _safe_create_option(TextOption, "setting", "navidrome_base_url", ""),
        _safe_create_option(TextOption, "setting", "navidrome_username", ""),
        _safe_create_option(TextOption, "setting", "navidrome_password", ""),
        _safe_create_option(BoolOption, "setting", "navidrome_verify_ssl", True),
        _safe_create_option(BoolOption, "setting", "navidrome_save_credentials", False),
        _safe_create_option(BoolOption, "setting", "navidrome_enable_cache", True),
    ] if opt is not None]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QFormLayout(self)

        self.base_url = QLineEdit(self)
        self.username = QLineEdit(self)
        self.password = QLineEdit(self)
        try:
            self.password.setEchoMode(QLineEdit.EchoMode.Password)  # PyQt6 sig
        except Exception:
            try:
                self.password.setEchoMode(QLineEdit.Password)
            except Exception:
                pass
        self.verify_ssl = QCheckBox(self)

        self.layout.addRow("Server URL (e.g. https://navidrome.local)", self.base_url)
        self.layout.addRow("Username", self.username)
        self.layout.addRow("Password", self.password)
        self.layout.addRow("Verify SSL", self.verify_ssl)

        self.save_credentials = QCheckBox(self)
        self.layout.addRow("Save credentials", self.save_credentials)
        
        self.conn_status = QLabel("Not connected!")
        try:
            self.conn_status.setStyleSheet("color: red;")
        except Exception:
            pass
        self.layout.addRow(self.conn_status)

        # Test Connection button
        self.test_button = QPushButton("Test Connection", self)
        self.test_button.clicked.connect(self._test_connection)  # type: ignore[attr-defined]
        self.layout.addRow(self.test_button)
        
        # Add spacing before cache settings
        self.layout.addRow("", QLabel(""))  # Empty row for spacing
        
        # Cache settings - simple checkbox
        self.enable_cache = QCheckBox("Enable caching (persists until manually cleared)")
        try:
            self.enable_cache.setToolTip(
                "Enable in-memory caching to speed up subsequent library fetches.\n"
                "Cache persists until you manually clear it using the 'Clear Cache' button."
            )
        except Exception:
            pass
        self.layout.addRow("", self.enable_cache)

        self.browse_button = QPushButton("Edit Playlists in Navidrome...", self)
        self.browse_button.clicked.connect(self._open_browser)  # type: ignore[attr-defined]
        self.layout.addRow(self.browse_button)

        self.library_button = QPushButton("Create Playlist from Navidrome Library...", self)
        self.library_button.clicked.connect(self._open_library)  # type: ignore[attr-defined]
        self.layout.addRow(self.library_button)

        # Clear cache button
        self.clear_cache_button = QPushButton("Clear Cache", self)
        self.clear_cache_button.clicked.connect(self._clear_cache)  # type: ignore[attr-defined]
        self.layout.addRow(self.clear_cache_button)

        # About button
        self.about_button = QPushButton("About...", self)
        self.about_button.clicked.connect(self._open_about)  # type: ignore[attr-defined]
        self.layout.addRow(self.about_button)

    def load(self) -> None:
        self.base_url.setText(config.setting["navidrome_base_url"])
        self.username.setText(config.setting["navidrome_username"])
        self.password.setText(config.setting["navidrome_password"])
        self.verify_ssl.setChecked(bool(config.setting["navidrome_verify_ssl"]))
        try:
            self.save_credentials.setChecked(bool(config.setting["navidrome_save_credentials"]))
        except Exception:
            pass
        try:
            self.enable_cache.setChecked(bool(config.setting["navidrome_enable_cache"]))
        except Exception:
            pass
        try:
            self._update_conn_status(connected=None, test=True)
        except Exception:
            pass

    def save(self) -> None:
        self.base_url.setText(self.base_url.text().strip())
        config.setting["navidrome_base_url"] = self.base_url.text().strip()
        config.setting["navidrome_username"] = self.username.text().strip()
        config.setting["navidrome_password"] = self.password.text()
        config.setting["navidrome_verify_ssl"] = bool(self.verify_ssl.isChecked())
        try:
            config.setting["navidrome_save_credentials"] = bool(self.save_credentials.isChecked())
        except Exception:
            pass
        try:
            config.setting["navidrome_enable_cache"] = bool(self.enable_cache.isChecked())
        except Exception:
            pass
        try:
            self._update_conn_status(connected=None, test=True)
        except Exception:
            pass

    def restore_defaults(self) -> None:
        self.base_url.clear()
        self.username.clear()
        self.password.clear()
        self.verify_ssl.setChecked(True)
        try:
            self.save_credentials.setChecked(False)
        except Exception:
            pass
        try:
            self._update_conn_status(connected=False)
        except Exception:
            pass

    def get_widget(self) -> QWidget:
        return self

    # ---- internal helpers ----
    def _update_conn_status(self, *, connected: Optional[bool] = None, test: bool = False) -> None:
        try:
            if connected is None and test:
                base_url = self.base_url.text().strip()
                username = self.username.text().strip()
                password = self.password.text()
                verify_ssl = bool(self.verify_ssl.isChecked())
                if not (base_url and username and password):
                    connected = False
                else:
                    try:
                        client = SubsonicClient(base_url=base_url, username=username, password=password, app_name="PicardNavidrome", verify_ssl=verify_ssl, timeout_seconds=5)
                        connected = bool(client.ping())
                    except Exception:
                        connected = False
            elif connected is None:
                base_url = self.base_url.text().strip()
                username = self.username.text().strip()
                password = self.password.text()
                connected = bool(base_url and username and password)
                if connected:
                    connected = False
            if connected:
                self.conn_status.setText("Connected!")
                self.conn_status.setStyleSheet("color: green;")
            else:
                self.conn_status.setText("Not connected!")
                self.conn_status.setStyleSheet("color: red;")
        except Exception:
            pass

    def _test_connection(self) -> None:
        base_url = self.base_url.text().strip()
        username = self.username.text().strip()
        password = self.password.text()
        app_name = "PicardNavidrome"
        verify_ssl = bool(self.verify_ssl.isChecked())

        if not base_url or not username or not password:
            QMessageBox.warning(self, "Navidrome", "Please fill in Server URL, Username and Password.")
            self._update_conn_status(connected=False)
            return

        try:
            client = SubsonicClient(
                base_url=base_url,
                username=username,
                password=password,
                app_name=app_name,
                verify_ssl=verify_ssl,
            )
            if client.ping():
                self._update_conn_status(connected=True)
                QMessageBox.information(self, "Navidrome", f"Logged successfully as {username}.")
            else:
                self._update_conn_status(connected=False)
                QMessageBox.critical(self, "Navidrome", "Connection failed. Please check your credentials and server URL.")
        except Exception as exc:
            self._update_conn_status(connected=False)
            QMessageBox.critical(self, "Navidrome", f"Connection error: {exc}")

    def _open_browser(self) -> None:
        base_url = self.base_url.text().strip()
        username = self.username.text().strip()
        password = self.password.text()
        app_name = "PicardNavidrome"
        verify_ssl = bool(self.verify_ssl.isChecked())
        if not base_url or not username or not password:
            QMessageBox.warning(None, "Navidrome", "Please fill in Server URL, Username and Password.")
            return
        try:
            self.save()
            try:
                enable_cache = bool(config.setting["navidrome_enable_cache"])
            except (KeyError, ValueError):
                enable_cache = True
            client = SubsonicClient(
                base_url=base_url, 
                username=username, 
                password=password, 
                app_name=app_name, 
                verify_ssl=verify_ssl,
                enable_cache=enable_cache
            )
            dlg = NavidromeBrowserDialog(None, client)
            try:
                dlg.exec()
            except Exception:
                try:
                    dlg.exec_()
                except Exception:
                    dlg.show()
        except Exception as exc:
            QMessageBox.critical(None, "Navidrome", f"Error: {exc}")

    def _open_library(self) -> None:
        base_url = self.base_url.text().strip()
        username = self.username.text().strip()
        password = self.password.text()
        app_name = "PicardNavidrome"
        verify_ssl = bool(self.verify_ssl.isChecked())
        if not base_url or not username or not password:
            QMessageBox.warning(None, "Navidrome", "Please fill in Server URL, Username and Password.")
            return
        try:
            self.save()
            try:
                enable_cache = bool(config.setting["navidrome_enable_cache"])
            except (KeyError, ValueError):
                enable_cache = True
            client = SubsonicClient(
                base_url=base_url, 
                username=username, 
                password=password, 
                app_name=app_name, 
                verify_ssl=verify_ssl,
                enable_cache=enable_cache
            )
            dlg = NavidromeLibraryDialog(None, client)
            try:
                dlg.exec()
            except Exception:
                try:
                    dlg.exec_()
                except Exception:
                    dlg.show()
        except Exception as exc:
            QMessageBox.critical(None, "Navidrome", f"Error: {exc}")

    def _clear_cache(self) -> None:
        """Clear the Navidrome cache."""
        try:
            # Create a temporary client just to clear cache
            base_url = self.base_url.text().strip()
            username = self.username.text().strip()
            password = self.password.text()
            verify_ssl = bool(self.verify_ssl.isChecked())
            
            if base_url and username and password:
                client = SubsonicClient(
                    base_url=base_url, 
                    username=username, 
                    password=password, 
                    verify_ssl=verify_ssl,
                    enable_cache=True
                )
                client.clear_cache()
                QMessageBox.information(self, "Navidrome", "Cache cleared successfully!")
            else:
                QMessageBox.warning(self, "Navidrome", "Please configure connection settings first.")
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Error clearing cache: {exc}")

    def _open_about(self) -> None:
        try:
            _open_about_dialog()
        except Exception as exc:
            QMessageBox.critical(None, "Navidrome", f"Unable to open About: {exc}")


# -----------------------------
# Context menu action
# -----------------------------
class NavidromeFetchPlaylistsAction(BaseAction):
    NAME = "navidrome_fetch_playlists"
    TITLE = "Navidrome: List Playlists"

    def callback(self, objs) -> None:  # objs: selected items (unused)
        base_url = config.setting["navidrome_base_url"].strip()
        username = config.setting["navidrome_username"].strip()
        password = config.setting["navidrome_password"]
        app_name = "PicardNavidrome"
        verify_ssl = bool(config.setting["navidrome_verify_ssl"])

        if not base_url or not username or not password:
            QMessageBox.warning(
                None,
                "Navidrome",
                "Please configure Navidrome settings in Options > Plugins > Navidrome.",
            )
            return

        try:
            client = SubsonicClient(
                base_url=base_url,
                username=username,
                password=password,
                app_name=app_name,
                verify_ssl=verify_ssl,
            )
            playlists = client.get_playlists()
            if not playlists:
                QMessageBox.information(None, "Navidrome", "No playlists found.")
                return
            names = "\n".join(p.get("name", "(unnamed)") for p in playlists)
            QMessageBox.information(None, "Navidrome Playlists", names)
        except Exception as exc:
            QMessageBox.critical(None, "Navidrome", f"Error: {exc}")


# -----------------------------
# Draggable list widget for tracks
# -----------------------------
class _DraggableListWidget(QListWidget):
    """Custom QListWidget with safer DnD and transparent drag pixmap."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._drop_row = -1
        self._drop_above = True

    def startDrag(self, supportedActions):  # type: ignore[override]
        try:
            it = self.currentItem()
            if it is None:
                return
            try:
                self.setCursor(Qt.ClosedHandCursor)  # type: ignore
            except Exception:
                pass
            # Use model's mime data so InternalMove works for single or multiple selection
            try:
                indexes = self.selectedIndexes()
                mime = self.model().mimeData(indexes)
            except Exception:
                mime = QMimeData()
            drag = QDrag(self)
            drag.setMimeData(mime)
            # No custom pixmap: default is fine for multi-select
            self._dragging = True
            try:
                drag.exec(Qt.MoveAction)  # type: ignore[attr-defined]
            finally:
                self._dragging = False
                try:
                    self.setCursor(Qt.OpenHandCursor)  # type: ignore
                except Exception:
                    pass
        except Exception:
            try:
                return super().startDrag(supportedActions)
            except Exception:
                return

    def dragEnterEvent(self, event):  # type: ignore[override]
        try:
            event.acceptProposedAction()
        except Exception:
            try:
                event.accept()
            except Exception:
                pass
        # Initialize drop indicator
        try:
            pos = event.position() if hasattr(event, 'position') else event.pos()
            pt = pos.toPoint() if hasattr(pos, 'toPoint') else pos
            idx_item = self.itemAt(pt)
            if idx_item is None:
                self._drop_row = self.count() - 1
                self._drop_above = False
            else:
                row = self.row(idx_item)
                r = self.visualItemRect(idx_item)
                self._drop_row = row
                self._drop_above = (pt.y() < (r.top() + r.height() // 2))
            self.viewport().update()
        except Exception:
            pass

    def dragMoveEvent(self, event):  # type: ignore[override]
        # Update visual drop indicator line and accept
        try:
            pos = event.position() if hasattr(event, 'position') else event.pos()
            pt = pos.toPoint() if hasattr(pos, 'toPoint') else pos
            idx_item = self.itemAt(pt)
            if idx_item is None:
                self._drop_row = self.count() - 1
                self._drop_above = False
            else:
                row = self.row(idx_item)
                r = self.visualItemRect(idx_item)
                self._drop_row = row
                self._drop_above = (pt.y() < (r.top() + r.height() // 2))
            self.viewport().update()
        except Exception:
            pass
        try:
            event.acceptProposedAction()
        except Exception:
            try:
                event.accept()
            except Exception:
                pass

    def dropEvent(self, event):  # type: ignore[override]
        # Guard against dropping directly below itself causing disappear
        try:
            src_row = self.currentRow()
            pos = event.position() if hasattr(event, 'position') else event.pos()  # PyQt6 vs 5
            dst_row = self.row(self.itemAt(pos.toPoint() if hasattr(pos, 'toPoint') else pos))
            if dst_row < 0:
                dst_row = self.count() - 1
            if dst_row == src_row:
                # True no-op move: ignore
                event.ignore()
                return
        except Exception:
            pass
        try:
            super().dropEvent(event)
            try:
                event.acceptProposedAction()
            except Exception:
                pass
        except Exception:
            event.ignore()
        # Clear indicator
        try:
            self._drop_row = -1
            self.viewport().update()
        except Exception:
            pass
        # Clear selection after successful drop to meet UX requirement
        try:
            self.clearSelection()
        except Exception:
            pass
        # Ensure cursor restored after drop
        try:
            self.setCursor(Qt.OpenHandCursor)  # type: ignore
        except Exception:
            pass

    def mousePressEvent(self, event):  # type: ignore[override]
        try:
            self.setCursor(Qt.ClosedHandCursor)  # type: ignore
        except Exception:
            pass
        try:
            super().mousePressEvent(event)
        finally:
            pass

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        try:
            self.setCursor(Qt.OpenHandCursor)  # type: ignore
        except Exception:
            pass
        try:
            super().mouseReleaseEvent(event)
        finally:
            pass

    def dragLeaveEvent(self, event):  # type: ignore[override]
        try:
            self._drop_row = -1
            self.viewport().update()
        except Exception:
            pass
        try:
            super().dragLeaveEvent(event)
        except Exception:
            pass

    def paintEvent(self, event):  # type: ignore[override]
        # Default paint
        try:
            super().paintEvent(event)
        except Exception:
            pass
        # Draw custom drop indicator line
        try:
            if self._drop_row >= 0:
                p = QPainter(self.viewport())
                try:
                    p.setRenderHint(QPainter.Antialiasing, True)
                    pen_color = QColor(0, 120, 215)
                    pen = QPen(pen_color, 2)
                    p.setPen(pen)
                    # Determine y position
                    if self._drop_row < self.count():
                        ref_item = self.item(self._drop_row)
                        rect = self.visualItemRect(ref_item)
                        y = rect.top() if self._drop_above else rect.bottom()
                    else:
                        y = self.viewport().rect().bottom()
                    p.drawLine(0, y, self.viewport().width(), y)
                finally:
                    p.end()
        except Exception:
            pass

# -----------------------------
# Simple playlists browser dialog
# -----------------------------
class NavidromeBrowserDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], client: SubsonicClient) -> None:
        super().__init__(parent)
        self.setWindowTitle("Navidrome Playlists")
        self.client = client
        try:
            self.resize(1200, 800)
        except Exception:
            pass

        # Configure window buttons
        try:
            self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore
            except Exception:
                pass
        try:
            self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)  # type: ignore
            except Exception:
                pass

        self.info_label = QLabel("Select a playlist to view and reorder tracks", self)

        # Left panel: Playlists list with better styling
        self.playlists_list = QListWidget(self)
        try:
            self.playlists_list.setAlternatingRowColors(True)
            self.playlists_list.setSelectionMode(QAbstractItemView.SingleSelection)  # type: ignore[attr-defined]
            try:
                self.playlists_list.setSpacing(2)
            except Exception:
                pass
            try:
                self.playlists_list.setStyleSheet(
                    """
                    QListWidget {
                        background-color: #fafafa;
                        border: none;
                        padding: 4px;
                        outline: none;
                    }
                    QListWidget:focus {
                        border: none;
                        outline: none;
                    }
                    QListWidget::item {
                        padding: 8px 12px;
                        border-radius: 6px;
                        margin: 2px;
                        font-weight: normal;
                        border: none;
                        background: transparent;
                    }
                    /* Edited (selected) playlist in blue */
                    QListWidget::item:selected {
                        background-color: #2196F3;
                        color: white;
                        font-weight: bold;
                        border: none;
                    }
                    QListWidget::item:hover {
                        background-color: #e3f2fd;
                        color: #1976d2;
                    }
                    QListWidget::item:focus {
                        outline: none;
                        border: none;
                    }
                    """
                )
            except Exception:
                pass
        except Exception:
            pass

        # Right panel: List widget for tracks (same as Review Selected Tracks)
        self.tracks_list = _DraggableListWidget(self)
        try:
            # Enable dragging by allowing selection and internal move
            self.tracks_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.tracks_list.setDefaultDropAction(Qt.MoveAction)  # type: ignore
            self.tracks_list.setDragDropMode(QAbstractItemView.InternalMove)
            self.tracks_list.setDropIndicatorShown(True)
            # Connect reordering signal
            self.tracks_list.orderChanged.connect(self._on_tracks_reordered)  # type: ignore[attr-defined]
        except Exception:
            pass

        # Left controls panel
        left_controls = QVBoxLayout()
        try:
            lbl_playlists = QLabel("Playlists", self)
            font = lbl_playlists.font()
            font.setBold(True)
            lbl_playlists.setFont(font)
            left_controls.addWidget(lbl_playlists)
        except Exception:
            pass
        left_controls.addWidget(self.playlists_list, 1)
        # Show which playlist is being edited
        try:
            self.playlists_list.currentTextChanged.connect(self._update_editing_label)  # type: ignore[attr-defined]
        except Exception:
            pass

        # Playlist action buttons
        try:
            lbl_actions = QLabel("Playlist Actions", self)
            font = lbl_actions.font()
            font.setBold(True)
            lbl_actions.setFont(font)
            left_controls.addWidget(lbl_actions)
        except Exception:
            pass

        self.rename_button = QPushButton("✏️ Rename", self)
        try:
            self.rename_button.setToolTip("Rename the selected playlist")
        except Exception:
            pass
        left_controls.addWidget(self.rename_button)

        self.delete_button = QPushButton("🗑️ Delete", self)
        try:
            self.delete_button.setToolTip("Delete the selected playlist")
            self.delete_button.setStyleSheet("color: #b00020;")
        except Exception:
            pass
        left_controls.addWidget(self.delete_button)

        self.public_checkbox = QCheckBox("📢 Make Public", self)
        try:
            self.public_checkbox.setToolTip("Toggle playlist visibility")
        except Exception:
            pass
        left_controls.addWidget(self.public_checkbox)

        self.owner_label = QLabel("Owner: ", self)
        try:
            self.owner_label.setWordWrap(True)
            self.owner_label.setStyleSheet("color: #1976d2; padding: 4px;")
            self.owner_label.setToolTip("Playlist owner")
        except Exception:
            pass
        left_controls.addWidget(self.owner_label)

        left_container = QWidget(self)
        left_container.setLayout(left_controls)
        try:
            left_container.setFixedWidth(250)  # Fixed width in pixels
        except Exception:
            pass

        # Right controls panel for tracks
        right_controls = QVBoxLayout()
        try:
            lbl_tracks = QLabel("Tracks", self)
            font = lbl_tracks.font()
            font.setBold(True)
            lbl_tracks.setFont(font)
            right_controls.addWidget(lbl_tracks)
        except Exception:
            pass

        tracks_info = QLabel("Drag tracks to order your playlist. Drag column headers to reorder, use ⋮ handles to resize columns.", self)
        try:
            font = tracks_info.font()
            font.setItalic(True)
            tracks_info.setFont(font)
        except Exception:
            pass
        right_controls.addWidget(tracks_info)

        # Custom column headers
        self._create_custom_headers()
        right_controls.addWidget(self.headers_widget)

        right_controls.addWidget(self.tracks_list, 1)

        # Track action buttons
        try:
            lbl_track_actions = QLabel("Track Actions", self)
            font = lbl_track_actions.font()
            font.setBold(True)
            lbl_track_actions.setFont(font)
            right_controls.addWidget(lbl_track_actions)
        except Exception:
            pass

        self.randomize_button = QPushButton("🎲 Randomize", self)
        try:
            self.randomize_button.setToolTip("Shuffle the track order randomly")
            self.randomize_button.setStyleSheet("color: #6200ea;")
        except Exception:
            pass
        right_controls.addWidget(self.randomize_button)

        self.add_songs_button = QPushButton("➕ Add new Track", self)
        try:
            self.add_songs_button.setToolTip("Add new tracks to the selected playlist")
            self.add_songs_button.setStyleSheet("color: #2e7d32;")
        except Exception:
            pass
        right_controls.addWidget(self.add_songs_button)

        self.remove_track_button = QPushButton("− Remove Track", self)
        try:
            self.remove_track_button.setToolTip("Remove the selected track from this playlist")
            self.remove_track_button.setStyleSheet("color: #b00020;")
        except Exception:
            pass
        right_controls.addWidget(self.remove_track_button)

        right_container = QWidget(self)
        right_container.setLayout(right_controls)

        # Main layout: fixed left panel, flexible right panel
        main_layout = QHBoxLayout()
        main_layout.addWidget(left_container, 0)  # Fixed width left panel
        main_layout.addWidget(right_container, 1)  # Flexible right panel

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        try:
            buttons.rejected.connect(self.reject)  # type: ignore[attr-defined]
        except Exception:
            pass

        layout = QVBoxLayout(self)
        layout.addWidget(self.info_label)
        layout.addLayout(main_layout, 1)
        layout.addWidget(buttons)

        # Connect signals
        try:
            self.playlists_list.currentRowChanged.connect(self._on_playlist_selected)  # type: ignore[attr-defined]
            self.rename_button.clicked.connect(self._rename_playlist)  # type: ignore[attr-defined]
            self.delete_button.clicked.connect(self._delete_playlist)  # type: ignore[attr-defined]
            self.public_checkbox.stateChanged.connect(self._toggle_public)  # type: ignore[attr-defined]
            self.add_songs_button.clicked.connect(self._add_new_songs)  # type: ignore[attr-defined]
            self.randomize_button.clicked.connect(self._randomize_tracks)  # type: ignore[attr-defined]
            self.remove_track_button.clicked.connect(self._remove_selected_track)  # type: ignore[attr-defined]
        except Exception:
            pass

        # Track drag reordering
        try:
            self.tracks_list.model().rowsMoved.connect(self._on_tracks_reordered)  # type: ignore[attr-defined]
        except Exception:
            pass

        self._updating_ui = False
        self._current_playlist_tracks = []  # Store current tracks with IDs
        self._newly_added_track_ids: Set[str] = set()  # Track IDs of newly added tracks for green highlighting
        self._last_selected_playlist_id: str = ""  # Track last selected playlist to detect switching
        self._load_playlists()

    def _update_editing_label(self, name: str) -> None:
        """Show the currently edited playlist in black; use green only for success messages elsewhere."""
        try:
            self.info_label.setText(f"Editing: {name}")
            # Match size and weight with success message, but keep color black
            self.info_label.setStyleSheet("color: black; font-size: 14px; font-weight: bold;")
        except Exception:
            pass

    def _load_playlists(self) -> None:
        try:
            playlists = self.client.get_playlists()
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to load playlists: {exc}")
            return
        self._playlists = playlists
        self.playlists_list.clear()
        for pl in playlists:
            name = pl.get("name", "(unnamed)")
            item = QListWidgetItem(name)
            try:
                # Different, more elegant font for playlist names (not bold)
                font = item.font()
                try:
                    font.setFamily("Segoe UI")
                except Exception:
                    pass
                try:
                    font.setPointSize(font.pointSize() + 1)
                except Exception:
                    pass
                font.setBold(False)
                font.setItalic(False)
                item.setFont(font)
            except Exception:
                pass
            self.playlists_list.addItem(item)
        # Auto-select and highlight the first playlist if available
        try:
            if self.playlists_list.count() > 0:
                self.playlists_list.setCurrentRow(0)
                # Trigger loading of tracks and label update
                self._on_playlist_selected(0)
        except Exception:
            pass

    def _create_custom_headers(self) -> None:
        """Create custom draggable column headers."""
        self.headers_widget = QWidget(self)
        self.headers_layout = QHBoxLayout(self.headers_widget)
        try:
            self.headers_layout.setContentsMargins(8, 4, 8, 4)
            self.headers_layout.setSpacing(0)
        except Exception:
            pass

        # Column configuration: [name, default_width, stretch_factor]
        self.column_config = [
            ["#", 40, 0],
            ["Songname", 200, 2],
            ["Artist", 150, 1], 
            ["Album", 150, 1],
            ["Genre", 100, 1],
            ["Filename", 150, 1]
        ]
        
        self.column_headers = []
        self.column_containers = []
        self.column_order = list(range(len(self.column_config)))  # Track column order
        
        for i, (name, width, stretch) in enumerate(self.column_config):
            # Create header container with resize handle
            header_container = QWidget(self)
            header_layout = QHBoxLayout(header_container)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(0)
            
            # Create the main header label
            header = self._create_header_label(name, width)
            header_layout.addWidget(header)
            
            # Add resize handle for every column; we'll hide it on the last visually
            resize_handle = self._create_resize_handle()
            header_layout.addWidget(resize_handle, 0)
            header._resize_handle = resize_handle  # Store reference
            if i == len(self.column_config) - 1:
                try:
                    resize_handle.hide()
                except Exception:
                    pass
            
            self.column_headers.append(header)
            self.column_containers.append(header_container)
            self.headers_layout.addWidget(header_container)

        # Adjust label widths to account for handle width so total column width matches config
        try:
            self._apply_header_widths()
        except Exception:
            pass

        # Fill remaining space on the right so columns keep their fixed widths
        try:
            self.headers_layout.addStretch(1)
        except Exception:
            pass
            
        try:
            self.headers_widget.setStyleSheet("""
                QWidget {
                    background-color: #f5f5f5;
                    border-bottom: 2px solid #ddd;
                    border-left: 1px solid #ddd;
                    border-right: 1px solid #ddd;
                    border-top: 1px solid #ddd;
                }
            """)
        except Exception:
            pass

        # Ensure only non-last visible column shows a handle
        try:
            self._refresh_header_handles()
        except Exception:
            pass

    def _refresh_header_handles(self) -> None:
        """Show resize handles for all but the last visible column.
        If a header lacks a handle, create and attach one to its container.
        """
        try:
            last_idx = len(self.column_headers) - 1
            for i, header in enumerate(self.column_headers):
                handle = getattr(header, '_resize_handle', None)
                if handle is None:
                    # Create and attach a handle if missing
                    try:
                        container = self.column_containers[i]
                        layout = container.layout()
                        handle = self._create_resize_handle()
                        layout.addWidget(handle, 0)
                        header._resize_handle = handle  # type: ignore[attr-defined]
                    except Exception:
                        handle = None
                if handle is None:
                    continue
                if i == last_idx:
                    try:
                        handle.hide()
                    except Exception:
                        pass
                else:
                    try:
                        handle.show()
                    except Exception:
                        pass
        except Exception:
            pass

    def _apply_header_widths(self) -> None:
        """Set each header label width so (label + handle) equals configured column width."""
        try:
            for i, header in enumerate(self.column_headers):
                # Column width from config for visual index i
                try:
                    display_col_idx = self.column_order[i]
                except Exception:
                    display_col_idx = i
                total_width = self.column_config[display_col_idx][1]
                handle = getattr(header, '_resize_handle', None)
                handle_width = 0
                try:
                    if handle is not None and handle.isVisible():
                        handle_width = int(handle.width())
                except Exception:
                    handle_width = 0
                label_width = max(20, total_width - handle_width)
                try:
                    header.setFixedWidth(label_width)
                except Exception:
                    pass
        except Exception:
            pass

    def _create_resize_handle(self) -> QLabel:
        """Create a visible resize handle between columns."""
        handle = QLabel("⋮", self)  # Using vertical dots as resize indicator
        try:
            handle.setFixedWidth(8)
            handle.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)  # type: ignore
            handle.setCursor(Qt.SizeHorCursor)  # type: ignore
            handle.setStyleSheet("""
                QLabel {
                    background-color: #ddd;
                    border-left: 1px solid #bbb;
                    border-right: 1px solid #bbb;
                    color: #666;
                    font-weight: bold;
                    font-size: 12px;
                }
                QLabel:hover {
                    background-color: #2196F3;
                    color: white;
                    border-left: 1px solid #1976D2;
                    border-right: 1px solid #1976D2;
                }
            """)
            handle.setToolTip("↔ Drag to resize column")
            
            # Add mouse events for resizing
            handle.mousePressEvent = lambda event: self._handle_resize_press(event, handle)
            handle.mouseMoveEvent = lambda event: self._handle_resize_move(event, handle)
            handle.mouseReleaseEvent = lambda event: self._handle_resize_release(event, handle)
            
        except Exception:
            pass
        return handle

    def _create_header_label(self, text: str, width: int) -> QLabel:
        """Create a draggable, resizable header label."""
        header = QLabel(text, self)
        try:
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
            header.setFixedWidth(width)
            # Different styling for # column (fixed) vs other columns (draggable)
            if text == "#":
                header.setStyleSheet("""
                    QLabel {
                        padding: 8px 4px;
                        border-right: 2px solid #999;
                        background-color: #e8e8e8;
                        color: #333;
                        font-weight: bold;
                    }
                    QLabel:hover {
                        background-color: #d8d8d8;
                    }
                """)
            else:
                header.setStyleSheet("""
                    QLabel {
                        padding: 8px 4px;
                        border-right: 1px solid #ccc;
                        background-color: #f0f0f0;
                    }
                    QLabel:hover {
                        background-color: #e0e0e0;
                        cursor: pointer;
                    }
                """)
            # Set helpful tooltips
            if text == "#":
                header.setToolTip("Track order - fixed position, use ⋮ handles to resize")
            else:
                header.setToolTip("Column header - drag to move, use ⋮ handles to resize")
            
            # Enable drag functionality
            header.setProperty("draggable", True)
            header.mousePressEvent = lambda event, h=header: self._header_mouse_press(event, h)
            header.mouseMoveEvent = lambda event, h=header: self._header_mouse_move(event, h)
            header.mouseReleaseEvent = lambda event, h=header: self._header_mouse_release(event, h)
        except Exception:
            pass
        return header

    def _handle_resize_press(self, event, handle) -> None:
        """Handle resize handle mouse press."""
        try:
            if event.button() == Qt.LeftButton:  # type: ignore
                # Find which column this handle belongs to
                for i, header in enumerate(self.column_headers):
                    if hasattr(header, '_resize_handle') and header._resize_handle == handle:
                        self._resizing_header = header
                        self._resize_start_pos = event.globalPos()
                        self._original_width = header.width()
                        self._is_resizing = True
                        handle.setStyleSheet("""
                            QLabel {
                                background-color: #1976D2;
                                color: white;
                                border-left: 1px solid #0D47A1;
                                border-right: 1px solid #0D47A1;
                                font-weight: bold;
                                font-size: 12px;
                            }
                        """)
                        break
        except Exception:
            pass

    def _handle_resize_move(self, event, handle) -> None:
        """Handle resize handle mouse move."""
        try:
            if hasattr(self, '_is_resizing') and getattr(self, '_is_resizing', False):
                if hasattr(self, '_resizing_header') and hasattr(self, '_resize_start_pos'):
                    current_pos = event.globalPos()
                    delta = current_pos.x() - self._resize_start_pos.x()
                    new_width = max(60, self._original_width + delta)  # Minimum width of 60px
                    
                    self._resizing_header.setFixedWidth(new_width)
                    # Update the column config
                    header_index = self.column_headers.index(self._resizing_header)
                    col_index = self.column_order[header_index]
                    self.column_config[col_index][1] = new_width
                    # Show visual feedback
                    handle.setToolTip(f"↔ Width: {new_width}px")
                    # Re-apply header widths to account for handle size
                    try:
                        self._apply_header_widths()
                    except Exception:
                        pass
        except Exception:
            pass

    def _handle_resize_release(self, event, handle) -> None:
        """Handle resize handle mouse release."""
        try:
            if hasattr(self, '_is_resizing'):
                self._is_resizing = False
                delattr(self, '_is_resizing')
                # Refresh the display after resizing
                current_row = self.playlists_list.currentRow()
                if current_row >= 0:
                    self._on_playlist_selected(current_row)
                # Ensure header widths align including handles
                try:
                    self._apply_header_widths()
                    self._refresh_header_handles()
                except Exception:
                    pass
                # Reset handle styling
                handle.setStyleSheet("""
                    QLabel {
                        background-color: #ddd;
                        border-left: 1px solid #bbb;
                        border-right: 1px solid #bbb;
                        color: #666;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QLabel:hover {
                        background-color: #2196F3;
                        color: white;
                        border-left: 1px solid #1976D2;
                        border-right: 1px solid #1976D2;
                    }
                """)
                handle.setToolTip("↔ Drag to resize column")
                
            # Clean up state
            if hasattr(self, '_resizing_header'):
                delattr(self, '_resizing_header')
            if hasattr(self, '_resize_start_pos'):
                delattr(self, '_resize_start_pos')
            if hasattr(self, '_original_width'):
                delattr(self, '_original_width')
        except Exception:
            pass

    def _header_mouse_press(self, event, header) -> None:
        """Handle header mouse press for dragging."""
        try:
            if event.button() == Qt.LeftButton:  # type: ignore
                self._start_dragging(event, header)
        except Exception:
            pass

    def _start_dragging(self, event, header) -> None:
        """Start dragging a header (only if it's not the # column)."""
        try:
            header_index = self.column_headers.index(header)
            col_index = self.column_order[header_index]
            
            # Don't allow dragging the # column (column 0)
            if col_index == 0:
                return
                
            self._drag_start_pos = event.pos()
            self._dragging_header = header
            self._original_cursor = header.cursor()
            header.setCursor(Qt.ClosedHandCursor)  # type: ignore
            self._is_dragging = True
        except Exception:
            pass

    def _header_mouse_move(self, event, header) -> None:
        """Handle header mouse move for dragging."""
        try:
            if hasattr(self, '_is_dragging') and getattr(self, '_is_dragging', False):
                # Handle column reordering with better detection
                if hasattr(self, '_dragging_header'):
                    current_pos = event.globalPos()
                    current_index = self.column_headers.index(self._dragging_header)
                    
                    # Find which header we're over by checking center points
                    for i, other_header in enumerate(self.column_headers):
                        if other_header != self._dragging_header and i > 0:  # Skip # column
                            header_rect = other_header.geometry()
                            header_global_rect = other_header.mapToGlobal(header_rect.topLeft())
                            header_center_x = header_global_rect.x() + header_rect.width() // 2
                            
                            # Check if mouse is over the center area of another header
                            if abs(current_pos.x() - header_center_x) < header_rect.width() // 3:
                                if i != current_index:
                                    self._swap_columns(current_index, i)
                                    break
            else:
                # Show appropriate cursor when not dragging
                header_index = self.column_headers.index(header)
                col_index = self.column_order[header_index]
                
                # Show appropriate cursor based on whether column can be dragged
                if col_index == 0:  # # column - fixed
                    header.setCursor(Qt.ArrowCursor)  # type: ignore
                else:  # Other columns - draggable
                    header.setCursor(Qt.OpenHandCursor)  # type: ignore
        except Exception:
            pass

    def _header_mouse_release(self, event, header) -> None:
        """Handle header mouse release."""
        try:
            # Clean up dragging state
            if hasattr(self, '_is_dragging'):
                self._is_dragging = False
                delattr(self, '_is_dragging')
            if hasattr(self, '_dragging_header'):
                delattr(self, '_dragging_header')
            if hasattr(self, '_drag_start_pos'):
                delattr(self, '_drag_start_pos')
                
            # Reset cursor
            header_index = self.column_headers.index(header)
            col_index = self.column_order[header_index]
            if col_index == 0:  # # column
                header.setCursor(Qt.ArrowCursor)  # type: ignore
            else:  # Other columns
                header.setCursor(Qt.OpenHandCursor)  # type: ignore
        except Exception:
            pass

    def _swap_columns(self, from_index: int, to_index: int) -> None:
        """Swap two columns in the header and update display."""
        try:
            if from_index == to_index:
                return
            
            # Don't allow moving the # column (column 0) or moving anything to position 0
            from_col_index = self.column_order[from_index]
            to_col_index = self.column_order[to_index]
            
            if from_col_index == 0 or to_col_index == 0:
                return  # # column stays fixed at first position
                
            # Update column order tracking
            self.column_order[from_index], self.column_order[to_index] = \
                self.column_order[to_index], self.column_order[from_index]
            
            # Swap header widgets and their containers
            self.column_headers[from_index], self.column_headers[to_index] = \
                self.column_headers[to_index], self.column_headers[from_index]
            try:
                self.column_containers[from_index], self.column_containers[to_index] = \
                    self.column_containers[to_index], self.column_containers[from_index]
            except Exception:
                pass

            # Fully rebuild the headers layout so handles stay attached to columns
            try:
                while self.headers_layout.count():
                    item = self.headers_layout.takeAt(0)
                    try:
                        w = item.widget()
                        if w is not None:
                            w.setParent(None)
                    except Exception:
                        pass
            except Exception:
                pass

            for container in self.column_containers:
                self.headers_layout.addWidget(container)
            try:
                self.headers_layout.addStretch(1)
            except Exception:
                pass

            # Update header widths and handles visibility after reordering
            try:
                self._apply_header_widths()
                self._refresh_header_handles()
            except Exception:
                pass
                
            # Refresh the track display
            current_row = self.playlists_list.currentRow()
            if current_row >= 0:
                self._on_playlist_selected(current_row)
                
        except Exception:
            pass

    def _on_playlist_selected(self, row: int) -> None:
        self.tracks_list.clear()  # Clear list widget
        self._current_playlist_tracks = []
        if row < 0 or row >= len(getattr(self, "_playlists", [])):
            # Clear when no playlist is selected
            self._newly_added_track_ids = set()
            self._last_selected_playlist_id = ""
            try:
                self.owner_label.setText("<b>Owner:</b> ")
            except Exception:
                pass
            # Disable all modification buttons when no playlist is selected
            try:
                self.rename_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                self.public_checkbox.setEnabled(False)
                self.add_songs_button.setEnabled(False)
                self.remove_track_button.setEnabled(False)
                self.randomize_button.setEnabled(False)
            except Exception:
                pass
            return
        pl = self._playlists[row]
        playlist_id = str(pl.get("id", ""))
        
        # Clear green highlighting when switching to a different playlist
        if playlist_id != self._last_selected_playlist_id and self._last_selected_playlist_id != "":
            self._newly_added_track_ids = set()
        self._last_selected_playlist_id = playlist_id
        
        try:
            self._update_editing_label(pl.get('name', '(unnamed)'))
        except Exception:
            pass
        if not playlist_id:
            return
        self._refresh_public_checkbox()
        self._refresh_owner_label()
        self._update_modification_buttons_state()
        try:
            entries = self.client.get_playlist_tracks(playlist_id)
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to load tracks: {exc}")
            return

        # Populate list widget with track data (same as Review Selected Tracks)
        for i, e in enumerate(entries):
            track_id = str(e.get("id", ""))
            title = e.get("title", "")
            artist = e.get("artist", "")
            album = e.get("album", "")
            genre = e.get("genre", "")
            
            # Store track data
            self._current_playlist_tracks.append(e)

            # Extract filename from path
            filename = e.get("path", "").split("/")[-1] if e.get("path") else ""
            if filename:
                # Remove common prefixes like "04 - ", "001.", "Track 01 -", etc.
                filename = re.sub(r'^(\d+[-\.\s]*\d*[-\.\s]*[-\s]+|Track\s+\d+\s*[-\.\s]*)', '', filename, flags=re.IGNORECASE)
                filename = filename.strip(' -.')

            try:
                item = QListWidgetItem()
                try:
                    item.setData(Qt.UserRole, track_id)  # type: ignore
                except Exception:
                    pass
                try:
                    # Ensure item can be dragged
                    item.setFlags(item.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)  # type: ignore
                except Exception:
                    pass

                # Custom row widget with all track information
                row_w = QWidget(self)
                h = QHBoxLayout(row_w)
                try:
                    h.setContentsMargins(8, 4, 8, 4)
                    h.setSpacing(0)
                except Exception:
                    pass
                
                # Collect all track data (≡ only in # column)
                track_data = {
                    "#": f"≡ {i+1}",
                    "Songname": title or "Unknown Songname",
                    "Artist": artist or "Unknown Artist",
                    "Album": album or "Unknown Album", 
                    "Genre": genre or "Unknown Genre",
                    "Filename": filename or "Unknown File"
                }
                
                # Create labels in the order specified by column_order
                labels = []
                column_x = 0
                for col_idx in self.column_order:
                    col_name = self.column_config[col_idx][0]
                    col_width = self.column_config[col_idx][1]
                    stretch = self.column_config[col_idx][2]
                    
                    label = QLabel(str(track_data[col_name]), row_w)
                    try:
                        label.setFixedWidth(col_width)
                        if col_name == "#":
                            label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)  # type: ignore
                            font = label.font()
                            font.setBold(True)
                            try:
                                font.setPointSize(font.pointSize() + 1)
                            except Exception:
                                pass
                            label.setFont(font)
                            label.setStyleSheet(
                                "background-color: #f2f2f2;"
                                "border: 1px solid #d0d0d0;"
                                "border-radius: 4px;"
                                "color: #555;"
                                "font-weight: bold;"
                                "padding: 2px 6px;"
                            )
                        else:
                            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
                            font = label.font()
                            font.setPointSize(font.pointSize())
                            label.setFont(font)
                            label.setStyleSheet("padding: 2px 4px;")
                        if col_name == "#":
                            label.setToolTip("Drag to reorder tracks")
                            label.setCursor(Qt.OpenHandCursor)  # type: ignore
                        else:
                            label.setToolTip(str(col_name))
                    except Exception:
                        pass
                    
                    labels.append(label)
                    h.addWidget(label)
                    # Keep track of cumulative x if needed for pixel-perfect alignment later
                    try:
                        column_x += int(col_width)
                    except Exception:
                        pass
                try:
                    h.addStretch(1)
                except Exception:
                    pass
                
                # Store labels for renumbering
                try:
                    row_w._column_labels = labels  # type: ignore[attr-defined]
                    row_w._num_label = labels[self.column_order.index(0)] if 0 in self.column_order else None  # type: ignore[attr-defined]
                except Exception:
                    pass

                self.tracks_list.addItem(item)
                try:
                    item.setSizeHint(row_w.sizeHint())
                except Exception:
                    pass
                self.tracks_list.setItemWidget(item, row_w)
                
                # Highlight newly added tracks in green
                if track_id in self._newly_added_track_ids:
                    try:
                        row_w.setStyleSheet("background-color: #c8e6c9;")  # Light green background
                    except Exception:
                        pass
                
                # Make widgets transparent for mouse events (except drag handles)
                try:
                    row_w.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # type: ignore
                    for label in labels:
                        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # type: ignore
                except Exception:
                    pass
                    
            except Exception:
                pass
                
        # Renumber the tracks
        self._renumber_tracks()

    def _current_playlist(self) -> Tuple[int, Dict]:
        row = self.playlists_list.currentRow()
        if row < 0 or row >= len(getattr(self, "_playlists", [])):
            return -1, {}
        return row, self._playlists[row]

    @staticmethod
    def _truthy(val) -> bool:
        try:
            s = str(val).strip().lower()
            return s in ("1", "true", "yes", "on")
        except Exception:
            return False

    def _refresh_public_checkbox(self) -> None:
        idx, pl = self._current_playlist()
        self._updating_ui = True
        try:
            checked = self._truthy(pl.get("public"))
            self.public_checkbox.setChecked(bool(checked))
        except Exception:
            try:
                self.public_checkbox.setChecked(False)
            except Exception:
                pass
        self._updating_ui = False

    def _refresh_owner_label(self) -> None:
        """Update the owner label to show the playlist owner with bold 'Owner:' and normal username."""
        idx, pl = self._current_playlist()
        try:
            owner = pl.get("owner", "Unknown")
            # Use HTML to make "Owner:" bold and keep username normal
            html_text = f'<b>Owner:</b> {owner}'
            self.owner_label.setText(html_text)
        except Exception:
            try:
                self.owner_label.setText("<b>Owner:</b> Unknown")
            except Exception:
                pass

    def _is_current_user_owner(self) -> bool:
        """Check if the current user owns the selected playlist."""
        idx, pl = self._current_playlist()
        if idx < 0:
            return False
        try:
            owner = pl.get("owner", "")
            current_user = self.client.username
            return str(owner).lower() == str(current_user).lower()
        except Exception:
            return False

    def _update_modification_buttons_state(self) -> None:
        """Enable/disable modification buttons based on playlist ownership."""
        is_owner = self._is_current_user_owner()
        
        # Disable all modification buttons if user is not the owner
        try:
            self.rename_button.setEnabled(is_owner)
            self.delete_button.setEnabled(is_owner)
            self.public_checkbox.setEnabled(is_owner)
            self.add_songs_button.setEnabled(is_owner)
            self.remove_track_button.setEnabled(is_owner)
            self.randomize_button.setEnabled(is_owner)
            
            # Update tooltips to explain why buttons are disabled
            if not is_owner:
                self.rename_button.setToolTip("Only the playlist owner can rename this playlist")
                self.delete_button.setToolTip("Only the playlist owner can delete this playlist")
                self.public_checkbox.setToolTip("Only the playlist owner can change visibility")
                self.add_songs_button.setToolTip("Only the playlist owner can add tracks")
                self.remove_track_button.setToolTip("Only the playlist owner can remove tracks")
                self.randomize_button.setToolTip("Only the playlist owner can randomize tracks")
            else:
                # Restore original tooltips
                self.rename_button.setToolTip("Rename the selected playlist")
                self.delete_button.setToolTip("Delete the selected playlist")
                self.public_checkbox.setToolTip("Toggle playlist visibility")
                self.add_songs_button.setToolTip("Add new tracks to the selected playlist")
                self.remove_track_button.setToolTip("Remove the selected track from this playlist")
                self.randomize_button.setToolTip("Shuffle the track order randomly")
        except Exception:
            pass

    def _rename_playlist(self) -> None:
        idx, pl = self._current_playlist()
        if idx < 0:
            return
        # Safety check: only allow owner to rename
        if not self._is_current_user_owner():
            QMessageBox.warning(self, "Navidrome", "Only the playlist owner can rename this playlist.")
            return
        playlist_id = str(pl.get("id", ""))
        cur_name = pl.get("name", "")
        try:
            new_name, ok = QInputDialog.getText(self, "Rename Playlist", "New name:", text=str(cur_name))
        except Exception:
            ok = False
            new_name = ""
        if not ok:
            return
        new_name = (new_name or "").strip()
        if not new_name or new_name == cur_name:
            return
        try:
            self.client.update_playlist(playlist_id, name=new_name)
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to rename playlist: {exc}")
            return
        self._playlists[idx]["name"] = new_name
        try:
            self.playlists_list.item(idx).setText(new_name)
        except Exception:
            pass
        self.info_label.setText(f"Renamed to: {new_name}")

    def _delete_playlist(self) -> None:
        idx, pl = self._current_playlist()
        if idx < 0:
            return
        # Safety check: only allow owner to delete
        if not self._is_current_user_owner():
            QMessageBox.warning(self, "Navidrome", "Only the playlist owner can delete this playlist.")
            return
        playlist_id = str(pl.get("id", ""))
        name = pl.get("name", "(unnamed)")
        try:
            res = QMessageBox.question(self, "Delete Playlist", f"Delete '{name}'?", QMessageBox.Yes | QMessageBox.No)  # type: ignore[attr-defined]
            proceed = (res == QMessageBox.Yes)
        except Exception:
            proceed = True
        if not proceed:
            return
        try:
            self.client.delete_playlist(playlist_id)
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to delete playlist: {exc}")
            return
        try:
            self.playlists_list.takeItem(idx)
        except Exception:
            pass
        try:
            del self._playlists[idx]
        except Exception:
            pass
        self.tracks_list.clear()
        self.info_label.setText(f"Deleted: {name}")

    def _toggle_public(self, state) -> None:
        if self._updating_ui:
            return
        idx, pl = self._current_playlist()
        if idx < 0:
            return
        # Safety check: only allow owner to change visibility
        if not self._is_current_user_owner():
            QMessageBox.warning(self, "Navidrome", "Only the playlist owner can change visibility.")
            self._updating_ui = True
            try:
                self.public_checkbox.setChecked(self._truthy(pl.get("public")))
            except Exception:
                pass
            self._updating_ui = False
            return
        playlist_id = str(pl.get("id", ""))
        make_public = bool(self.public_checkbox.isChecked())
        try:
            self.client.update_playlist(playlist_id, public=make_public)
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to update playlist visibility: {exc}")
            self._updating_ui = True
            try:
                self.public_checkbox.setChecked(self._truthy(pl.get("public")))
            except Exception:
                pass
            self._updating_ui = False
            return
        self._playlists[idx]["public"] = make_public
        self.info_label.setText("Playlist is now " + ("Public" if make_public else "Private"))

    def _renumber_tracks(self) -> None:
        """Renumber track order labels after reordering (for list widget)."""
        try:
            for i in range(self.tracks_list.count()):
                item = self.tracks_list.item(i)
                if item is None:
                    continue
                widget = self.tracks_list.itemWidget(item)
                if widget is None:
                    continue
                try:
                    # Find the order label (stored as _num_label)
                    order_label = getattr(widget, '_num_label', None)
                    if order_label is not None:
                        order_label.setText(f"≡ {i+1}")
                except Exception:
                    pass
        except Exception:
            pass

    def _randomize_tracks(self) -> None:
        """Shuffle the track order randomly and save to Navidrome."""
        # Clear green highlighting when user randomizes tracks
        self._newly_added_track_ids = set()
        
        import random
        idx, pl = self._current_playlist()
        if idx < 0:
            return
        
        # Safety check: only allow owner to randomize
        if not self._is_current_user_owner():
            QMessageBox.warning(self, "Navidrome", "Only the playlist owner can randomize tracks.")
            return

        try:
            # Get current track order
            track_ids = []
            for i in range(self.tracks_list.count()):
                item = self.tracks_list.item(i)  # Get list item which contains track ID
                if item is None:
                    continue
                try:
                    track_id = str(item.data(Qt.UserRole))  # type: ignore
                    if track_id:
                        track_ids.append(track_id)
                except Exception:
                    continue

            if not track_ids:
                return

            # Shuffle the track IDs
            random.shuffle(track_ids)

            # Update playlist on server
            playlist_id = str(pl.get("id", ""))
            try:
                # Delete current playlist
                self.client.delete_playlist(playlist_id)
                # Recreate with shuffled order
                new_name = pl.get("name", "Shuffled Playlist")
                new_pl_id = self.client.create_playlist(new_name, track_ids)
                if new_pl_id:
                    # Update our local data
                    self._playlists[idx]["id"] = new_pl_id
                    # Reload tracks to reflect new order
                    self._on_playlist_selected(idx)
                    self.info_label.setText("Tracks shuffled successfully!")
                    try:
                        self.info_label.setStyleSheet("color: #2e7d32; font-size: 14px; font-weight: bold;")
                    except Exception:
                        pass
            except Exception as exc:
                QMessageBox.critical(self, "Navidrome", f"Failed to shuffle tracks: {exc}")
        except Exception:
            pass

    def _remove_selected_track(self) -> None:
        """Remove the selected track from the playlist."""
        # Clear green highlighting when user removes a track
        self._newly_added_track_ids = set()
        
        idx, pl = self._current_playlist()
        if idx < 0:
            return
        
        # Safety check: only allow owner to remove tracks
        if not self._is_current_user_owner():
            QMessageBox.warning(self, "Navidrome", "Only the playlist owner can remove tracks.")
            return

        current_row = self.tracks_list.currentRow()
        if current_row < 0:
            QMessageBox.information(self, "Navidrome", "No track selected for deletion. Nothing deleted from playlist.")
            return

        try:
            # Get all track IDs except the selected one
            track_ids = []
            for i in range(self.tracks_list.count()):
                if i == current_row:
                    continue  # Skip the selected track
                item = self.tracks_list.item(i)  # Get list item which contains track ID
                if item is None:
                    continue
                try:
                    track_id = str(item.data(Qt.UserRole))  # type: ignore
                    if track_id:
                        track_ids.append(track_id)
                except Exception:
                    continue

            # Update playlist on server
            playlist_id = str(pl.get("id", ""))
            try:
                # Delete current playlist
                self.client.delete_playlist(playlist_id)
                # Recreate without the removed track
                new_name = pl.get("name", "Updated Playlist")
                new_pl_id = self.client.create_playlist(new_name, track_ids)
                if new_pl_id:
                    # Update our local data
                    self._playlists[idx]["id"] = new_pl_id
                    # Reload tracks to reflect removal
                    self._on_playlist_selected(idx)
                    self.info_label.setText("Track removed successfully!")
            except Exception as exc:
                QMessageBox.critical(self, "Navidrome", f"Failed to remove track: {exc}")
        except Exception:
            pass

    def _add_new_songs(self) -> None:
        """Open library dialog to add new songs to the selected playlist."""
        idx, pl = self._current_playlist()
        if idx < 0:
            QMessageBox.information(self, "Navidrome", "No playlist selected!")
            return
        
        # Safety check: only allow owner to add tracks
        if not self._is_current_user_owner():
            QMessageBox.warning(self, "Navidrome", "Only the playlist owner can add tracks.")
            return
        
        # Open the library dialog for adding songs
        try:
            dialog = NavidromeLibraryDialogForAddingSongs(self, self.client)
            if dialog.exec_() == QDialog.Accepted:
                new_track_ids = dialog.selected_track_ids
                if not new_track_ids:
                    return
                
                # Get current track IDs
                current_track_ids = []
                for i in range(self.tracks_list.count()):
                    item = self.tracks_list.item(i)
                    if item is None:
                        continue
                    try:
                        track_id = str(item.data(Qt.UserRole))  # type: ignore
                        if track_id:
                            current_track_ids.append(track_id)
                    except Exception:
                        continue
                
                # Combine existing tracks with new ones
                all_track_ids = current_track_ids + new_track_ids
                
                # Update playlist on server
                playlist_id = str(pl.get("id", ""))
                try:
                    # Delete current playlist
                    self.client.delete_playlist(playlist_id)
                    # Recreate with all tracks
                    new_name = pl.get("name", "Updated Playlist")
                    new_pl_id = self.client.create_playlist(new_name, all_track_ids)
                    if new_pl_id:
                        # Update our local data
                        self._playlists[idx]["id"] = new_pl_id
                        
                        # Store newly added track IDs for green highlighting AFTER updating playlist ID
                        self._newly_added_track_ids = set(new_track_ids)
                        
                        # Update the last selected playlist ID to the NEW playlist ID
                        # This prevents _on_playlist_selected from clearing the highlighting
                        self._last_selected_playlist_id = new_pl_id
                        
                        # Reload tracks to reflect additions
                        self._on_playlist_selected(idx)
                        self.info_label.setText(f"Added {len(new_track_ids)} track(s) successfully!")
                        try:
                            self.info_label.setStyleSheet("color: #2e7d32; font-size: 14px; font-weight: bold;")
                        except Exception:
                            pass
                except Exception as exc:
                    QMessageBox.critical(self, "Navidrome", f"Failed to add tracks: {exc}")
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to open library dialog: {exc}")

    def _on_tracks_reordered(self) -> None:
        """Handle track reordering via drag and drop."""
        # Clear green highlighting when user reorders tracks
        self._newly_added_track_ids = set()
        
        idx, pl = self._current_playlist()
        if idx < 0:
            return
        
        # Safety check: only allow owner to reorder tracks
        if not self._is_current_user_owner():
            QMessageBox.warning(self, "Navidrome", "Only the playlist owner can reorder tracks.")
            # Reload the playlist to restore original order
            self._on_playlist_selected(self.playlists_list.currentRow())
            return

        try:
            # Get new track order after drag/drop
            track_ids = []
            for i in range(self.tracks_list.count()):
                item = self.tracks_list.item(i)  # Get list item which contains track ID
                if item is None:
                    continue
                try:
                    track_id = str(item.data(Qt.UserRole))  # type: ignore
                    if track_id:
                        track_ids.append(track_id)
                except Exception:
                    continue

            if not track_ids:
                return

            # Update playlist on server with new order
            playlist_id = str(pl.get("id", ""))
            try:
                # Delete current playlist
                self.client.delete_playlist(playlist_id)
                # Recreate with new order
                new_name = pl.get("name", "Reordered Playlist")
                new_pl_id = self.client.create_playlist(new_name, track_ids)
                if new_pl_id:
                    # Update our local data
                    self._playlists[idx]["id"] = new_pl_id
                    # Renumber the tracks
                    self._renumber_tracks()
                    self.info_label.setText("Track order saved!")
                    try:
                        self.info_label.setStyleSheet("color: #2e7d32; font-size: 14px; font-weight: bold;")
                    except Exception:
                        pass
            except Exception as exc:
                QMessageBox.critical(self, "Navidrome", f"Failed to save track order: {exc}")
        except Exception:
            pass


# -----------------------------
# Library browser dialog (with Filter button; no Blend columns)
# -----------------------------
class NavidromeFetchProgressDialog(QDialog):
    """Modal progress with bar + status text and a Cancel button."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fetching from Navidrome…")
        try:
            self.setModal(True)
            self.setMinimumWidth(420)
        except Exception:
            pass
        self._cancelled = False
        v = QVBoxLayout(self)
        self._label = QLabel("Fetching your library…", self)
        self._bar = QProgressBar(self)
        try:
            self._bar.setRange(0, 0)  # indeterminate until we know the total
        except Exception:
            pass
        self._status = QLabel("Starting…", self)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        try:
            buttons.rejected.connect(self._on_cancel)  # type: ignore[attr-defined]
        except Exception:
            pass
        v.addWidget(self._label)
        v.addWidget(self._bar)
        v.addWidget(self._status)
        v.addWidget(buttons)

    def _on_cancel(self) -> None:
        self._cancelled = True

    def cancelled(self) -> bool:
        return bool(self._cancelled)

    def set_total(self, n: int) -> None:
        try:
            if n and n > 0:
                self._bar.setRange(0, n)
            else:
                self._bar.setRange(0, 0)
        except Exception:
            pass

    def set_value(self, n: int) -> None:
        try:
            self._bar.setValue(int(n))
            # Update window title with percentage if possible
            if self._bar.maximum() > 0:
                percentage = int((n * 100) / self._bar.maximum())
                self.setWindowTitle(f"Fetching from Navidrome… {percentage}%")
            else:
                self.setWindowTitle("Fetching from Navidrome…")
        except Exception:
            pass

    def set_status(self, text: str) -> None:
        try:
            self._status.setText(str(text))
        except Exception:
            pass


class NavidromeLibraryDialog(QDialog):
    # Column indices (checkbox embedded in Filename column)
    COL_FILENAME = 0
    COL_TITLE = 1
    COL_ARTIST = 2
    COL_ALBUM = 3
    COL_YEAR = 4
    COL_GENRE = 5
    COL_DURATION = 6

    def __init__(self, parent: Optional[QWidget], client: SubsonicClient) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Tracks from Navidrome Library")
        self.client = client
        self._loading = False
        # Track last reviewed ids so newly added tracks appear at bottom in Review and are highlighted
        self._last_review_ids: Set[str] = set()
        try:
            self.resize(1200, 800)
        except Exception:
            pass

        # Configure window buttons: enable Minimize/Maximize and ensure no Context Help ("?")
        try:
            self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore
            except Exception:
                pass
        try:
            self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)  # type: ignore
            except Exception:
                pass

        # --- Top row: Filter button (left) + search box (right) ---
        self.filter_btn = QToolButton(self)
        try:
            self.filter_btn.setMinimumWidth(90)
        except Exception:
            pass
        self.filter_btn.setText("Filter ▼")
        self.filter_btn.setToolTip("Hide/show columns")
        try:
            self.filter_btn.setPopupMode(QToolButton.InstantPopup)  # type: ignore[attr-defined]
        except Exception:
            pass
        self.filter_menu = QMenu(self)
        self.filter_btn.setMenu(self.filter_menu)

        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Search in filter list...")

        top_row = QHBoxLayout()
        top_row.addWidget(self.filter_btn, 0)
        top_row.addWidget(self.search_bar, 1)

        # --- Table ---
        self.table = QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Filename", "Songname", "Artist", "Album", "Year", "Genre", "Duration"
        ])
        try:
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)  # type: ignore[attr-defined]
            self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # type: ignore[attr-defined]
            self.table.setSortingEnabled(True)

            # Columns adjustable: resizable + re-orderable
            hh = self.table.horizontalHeader()
            hh.setSectionsMovable(True)
            try:
                hh.setSectionResizeMode(QHeaderView.Interactive)
            except Exception:
                try:
                    hh.setResizeMode(QHeaderView.Interactive)  # very old Qt
                except Exception:
                    pass
            try:
                hh.setStretchLastSection(False)
            except Exception:
                pass
            # Make header font bold
            try:
                font = hh.font()
                font.setBold(True)
                hh.setFont(font)
            except Exception:
                pass
            # Fallback for styles where header font isn't applied
            try:
                hh.setStyleSheet("QHeaderView::section { font-weight: bold; }")
            except Exception:
                pass
            # Pin Filename column at first position and make it not draggable
            try:
                vi = hh.visualIndex(self.COL_FILENAME)
                if vi != 0:
                    hh.moveSection(vi, 0)
            except Exception:
                pass
            try:
                hh.setSectionMovable(self.COL_FILENAME, False)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.table.setColumnWidth(self.COL_FILENAME, max(self.table.columnWidth(self.COL_FILENAME), 240))
            except Exception:
                pass
            try:
                self._suppress_header_move = False
            except Exception:
                pass
            try:
                hh.sectionMoved.connect(self._on_header_moved)  # type: ignore[attr-defined]
            except Exception:
                pass

            # Rows adjustable: resizable height; disable drag-reordering
            vh = self.table.verticalHeader()
            try:
                vh.setSectionResizeMode(QHeaderView.Interactive)
            except Exception:
                try:
                    vh.setResizeMode(QHeaderView.Interactive)
                except Exception:
                    pass

            # Disable Qt drag-and-drop row reordering
            try:
                self.table.setDragEnabled(False)
                self.table.setAcceptDrops(False)
                self.table.setDropIndicatorShown(False)
                self.table.setDragDropOverwriteMode(False)
                self.table.setDragDropMode(QAbstractItemView.NoDragDrop)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception:
            pass

        # --- Right panel actions ---
        right_panel = QVBoxLayout()
        self.actions_label = QLabel("Actions", self)
        try:
            f = self.actions_label.font()
            f.setBold(True)
            self.actions_label.setFont(f)
        except Exception:
            pass
        right_panel.addWidget(self.actions_label)

        self.select_all_button = QPushButton("Select All", self)
        try:
            self.select_all_button.clicked.connect(self._check_all_visible)  # type: ignore[attr-defined]
        except Exception:
            pass
        right_panel.addWidget(self.select_all_button)

        self.clear_button = QPushButton("Clear Selection", self)
        self.clear_button.clicked.connect(self._clear_selection)  # type: ignore[attr-defined]
        right_panel.addWidget(self.clear_button)

        # Deselect Blue (clear highlight selection only; do not change checkboxes)
        self.deselect_blue_button = QPushButton('Remove "Blue Selection"', self)
        try:
            self.deselect_blue_button.setToolTip("Clear the blue row highlight without changing checkboxes")
        except Exception:
            pass
        try:
            self.deselect_blue_button.clicked.connect(self._deselect_blue_selection)  # type: ignore[attr-defined]
        except Exception:
            pass
        right_panel.addWidget(self.deselect_blue_button)
        right_panel.addStretch(1)

        right_container = QWidget(self)
        right_container.setLayout(right_panel)

        lists_layout = QHBoxLayout()
        lists_layout.addWidget(self.table, 3)
        lists_layout.addWidget(right_container, 1)

        # Custom buttons row to control order explicitly
        buttons_row = QHBoxLayout()
        try:
            buttons_row.addStretch(1)
        except Exception:
            pass
        try:
            self.cancel_button = QPushButton("Cancel", self)
            self.cancel_button.clicked.connect(self.reject)  # type: ignore[attr-defined]
            buttons_row.addWidget(self.cancel_button)
        except Exception:
            pass
        try:
            self.continue_button = QPushButton("Continue and Review playlist", self)
            self.continue_button.clicked.connect(self._continue_to_review_selected)  # type: ignore[attr-defined]
            buttons_row.addWidget(self.continue_button)
            try:
                self.continue_button.setDefault(True)
                self.continue_button.setAutoDefault(True)
            except Exception:
                pass
        except Exception:
            pass

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addLayout(lists_layout)
        layout.addLayout(buttons_row)

        # Dynamic counter showing selected tracks
        self.counter_label = QLabel("0 of 0 tracks selected", self)
        try:
            self.counter_label.setAlignment(Qt.AlignCenter)  # type: ignore
            font = self.counter_label.font()
            font.setBold(True)
            self.counter_label.setFont(font)
            self.counter_label.setStyleSheet("color: #1976d2; font-size: 14px; margin: 5px;")
        except Exception:
            pass
        layout.addWidget(self.counter_label)

        self.info_label = QLabel("", self)
        layout.addWidget(self.info_label)

        # Signals
        try:
            self.search_bar.textChanged.connect(self._apply_filters)  # type: ignore[attr-defined]
            self.table.itemSelectionChanged.connect(self._update_counts)  # type: ignore[attr-defined]
            self.table.cellClicked.connect(self._on_cell_clicked)  # type: ignore[attr-defined]
            self.table.itemChanged.connect(self._on_item_changed)  # type: ignore[attr-defined]
        except Exception:
            pass

        self._songs: List[Dict] = []
        self._visible_rows: List[int] = []
        self._checked_ids: Set[str] = set()
        self._updating_checks: bool = False
        # Drag-select state (paint selection by dragging)
        self._drag_select_active: bool = False
        self._drag_select_target_checked: bool = True
        self._drag_last_row: Optional[int] = None
        self._drag_anchor_row: Optional[int] = None
        self._drag_did_move: bool = False
        self._drag_prev_direction: int = 0  # 0 unknown, 1 down, -1 up
        # Track the row where a drag ended to suppress only that release-click
        self._just_finished_drag_release_row: Optional[int] = None

        # Install event filter on the table's viewport to capture mouse drag
        try:
            self.table.viewport().installEventFilter(self)
            self.table.viewport().setMouseTracking(True)
        except Exception:
            pass

        # Build Filter menu now that headers exist
        self._build_filter_menu()

        # Load songs streaming with progress
        self._load_songs_streaming()

    # ---------- Filter button menu ----------
    def _build_filter_menu(self) -> None:
        self._col_actions: List[QAction] = []
        # Build actions for filterable columns only (exclude fixed Filename)
        labels = [
            (self.COL_TITLE, "Songname"),
            (self.COL_ARTIST, "Artist"),
            (self.COL_ALBUM, "Album"),
            (self.COL_YEAR, "Year"),
            (self.COL_GENRE, "Genre"),
            (self.COL_DURATION, "Duration"),
        ]
        for col, label in labels:
            act = QAction(label, self.filter_menu)
            act.setCheckable(True)
            act.setChecked(True)  # columns visible by default

            def _make_toggler(column_index: int, action: QAction):
                def _toggle(checked: bool) -> None:
                    try:
                        self.table.setColumnHidden(column_index, not bool(checked))
                    except Exception:
                        pass
                return _toggle

            act.toggled.connect(_make_toggler(col, act))  # type: ignore[attr-defined]
            self.filter_menu.addAction(act)
            self._col_actions.append(act)

        self.filter_menu.addSeparator()
        reset_act = QAction("Search in filter list...", self.filter_menu)

        def _reset_cols() -> None:
            for col, a in zip([c for c, _ in labels], self._col_actions):
                try:
                    a.setChecked(True)
                    self.table.setColumnHidden(col, False)
                except Exception:
                    pass

        reset_act.triggered.connect(_reset_cols)  # type: ignore[attr-defined]
        self.filter_menu.addAction(reset_act)

    # ---------- Helpers ----------
    @staticmethod
    def _guess_ext_from_content_type(ct: str) -> str:
        ct = (ct or "").lower()
        if "mpeg" in ct:
            return "mp3"
        if "flac" in ct:
            return "flac"
        if "ogg" in ct or "vorbis" in ct:
            return "ogg"
        if "mp4" in ct or "m4a" in ct or "aac" in ct:
            return "m4a"
        if "wav" in ct:
            return "wav"
        return "mp3"

    @staticmethod
    def _strip_two_digit_prefix(name: str) -> str:
        """
        Remove a leading 'NN-NN - ' prefix (e.g., '01-45 - ') from the beginning of the filename.
        Keeps the rest intact. Leading spaces before the numbers are allowed.
        """
        try:
            return re.sub(r"^\s*\d{2}-\d{2}\s*-\s*", "", name)
        except Exception:
            return name

    @classmethod
    def _dataname_for_song(cls, s: Dict) -> str:
        # Prefer a real path/basename if provided
        try:
            path = s.get("path") or s.get("file")
            if isinstance(path, str) and path:
                base = os.path.basename(path)
                if base:
                    return cls._strip_two_digit_prefix(base)
        except Exception:
            pass
        # Else synthesize from title/name + extension
        title = s.get("title") or s.get("name") or "track"
        ext = s.get("suffix")
        if not ext:
            ext = cls._guess_ext_from_content_type(str(s.get("contentType", "")))
        ext = str(ext).lower()
        base = str(title).strip() or "track"
        if not base.lower().endswith("." + ext):
            base = f"{base}.{ext}"
        return cls._strip_two_digit_prefix(base)

    def _apply_filters(self) -> None:
        """Apply search text to visible rows across visible columns."""
        query = (self.search_bar.text() or "").strip().lower()
        tokens = [t for t in re.split(r"\s+", query) if t]

        self._visible_rows = []
        for row in range(self.table.rowCount()):
            # Search across visible columns only
            row_text_parts = []
            for col in range(self.table.columnCount()):
                try:
                    if self.table.isColumnHidden(col):
                        continue
                except Exception:
                    pass
                it = self.table.item(row, col)
                try:
                    if it:
                        row_text_parts.append((it.text() or "").lower())
                except Exception:
                    pass
            row_text = " ".join(row_text_parts)
            matches_text = True
            for tok in tokens:
                if tok not in row_text:
                    matches_text = False
                    break

            try:
                self.table.setRowHidden(row, not matches_text)
            except Exception:
                pass
            if matches_text:
                self._visible_rows.append(row)

        self._update_counts()

    def _update_counts(self) -> None:
        selected = 0
        try:
            selected = sum(
                1
                for r in range(self.table.rowCount())
                if (self.table.item(r, self.COL_FILENAME) is not None and self.table.item(r, self.COL_FILENAME).checkState() == Qt.Checked)  # type: ignore
            )
        except Exception:
            selected = len(self._checked_ids)
        total = len(self._songs)
        self.setWindowTitle(f"Select Tracks from Navidrome Library — {selected} selected / {total} total")
        try:
            self.counter_label.setText(f"{selected} of {total} tracks selected")
        except Exception:
            pass
        try:
            self.info_label.setText(f"Visible: {len(self._visible_rows)} / Total: {total}")
        except Exception:
            pass

    def _clear_selection(self) -> None:
        # Uncheck all checkboxes (clears logical selection)
        self._updating_checks = True
        try:
            self._checked_ids.clear()
            for r in range(self.table.rowCount()):
                it = self.table.item(r, self.COL_FILENAME)
                if it is not None:
                    it.setCheckState(Qt.Unchecked)  # type: ignore
        except Exception:
            pass
        self._updating_checks = False
        self._update_counts()

    def _deselect_blue_selection(self) -> None:
        # Clear visual selection highlight only; do not change any checkbox states
        try:
            self.table.clearSelection()
        except Exception:
            pass
        try:
            # Also clear current focus index to avoid a blue cell remaining focused
            self.table.setCurrentCell(-1, -1)
        except Exception:
            pass
        # Ensure next click is registered normally after using the button
        self._drag_did_move = False
        self._just_finished_drag_release_row = None
        try:
            self.table.setFocus()
        except Exception:
            pass

    # ---------- Loading ----------
    def _load_songs_streaming(self) -> None:
        """Streaming load with progress dialog and live 'Fetched song X of Y' status."""
        progress = NavidromeFetchProgressDialog(self)
        try:
            progress.show()
        except Exception:
            pass
        if QCoreApplication is not None:
            try:
                QCoreApplication.processEvents()
            except Exception:
                pass

        try:
            self.table.setSortingEnabled(False)
        except Exception:
            pass

        self._songs = []
        self.table.setRowCount(0)
        self._loading = True
        fetched = 0

        def _cancelled() -> bool:
            return progress.cancelled()

        def _progress_cb(done: int, total_known: int) -> None:
            progress.set_total(total_known if total_known > 0 else 0)
            progress.set_value(done if total_known > 0 else 0)
            if total_known > 0:
                percentage = int((done * 100) / total_known) if total_known > 0 else 0
                progress.set_status(f"Fetched {done} of {total_known} songs ({percentage}%)")
            else:
                progress.set_status(f"Calculating total songs... ({done} found)")
            if QCoreApplication is not None:
                try:
                    QCoreApplication.processEvents()
                except Exception:
                    pass

        try:
            for s in self.client.iter_all_songs_stream(progress_cb=_progress_cb, cancel_flag=_cancelled):
                if _cancelled():
                    break

                artist = s.get("artist") or ""
                title = s.get("title") or s.get("name") or ""
                album = s.get("album") or ""
                year = str(s.get("year", ""))
                genre = s.get("genre") or ""
                dur = s.get("duration")
                if isinstance(dur, int) and dur >= 0:
                    minutes = dur // 60
                    seconds = dur % 60
                    duration_text = f"{minutes}:{seconds:02d}"
                else:
                    duration_text = str(dur) if dur is not None else ""

                filename = self._dataname_for_song(s)
                sid = str(s.get("id", ""))

                row = self.table.rowCount()
                self.table.insertRow(row)

                # Embed checkbox into Filename cell (no separate checkbox column)
                try:
                    chk = QTableWidgetItem("")
                    try:
                        chk.setFlags((chk.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)  # type: ignore
                    except Exception:
                        pass
                    if sid in self._checked_ids:
                        chk.setCheckState(Qt.Checked)  # type: ignore
                    else:
                        chk.setCheckState(Qt.Unchecked)  # type: ignore
                except Exception:
                    chk = None

                # Fill other cells; store song id on Filename cell
                try:
                    it_filename = QTableWidgetItem(str(filename))
                    try:
                        it_filename.setFlags(it_filename.flags() & ~Qt.ItemIsEditable)  # type: ignore
                    except Exception:
                        pass
                    try:
                        it_filename.setData(Qt.UserRole, sid)  # type: ignore
                    except Exception:
                        pass
                    self.table.setItem(row, self.COL_FILENAME, it_filename)
                    if chk is not None:
                        try:
                            it_filename.setFlags((it_filename.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)  # type: ignore
                        except Exception:
                            pass
                        try:
                            it_filename.setCheckState(chk.checkState())  # type: ignore
                        except Exception:
                            pass
                except Exception:
                    pass

                def _safe_set(col_index: int, value: str) -> None:
                    try:
                        item = QTableWidgetItem(str(value))
                        try:
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # type: ignore
                        except Exception:
                            pass
                        self.table.setItem(row, col_index, item)
                    except Exception:
                        pass

                _safe_set(self.COL_TITLE, title)
                _safe_set(self.COL_ARTIST, artist)
                _safe_set(self.COL_ALBUM, album)
                _safe_set(self.COL_YEAR, year)
                _safe_set(self.COL_GENRE, genre)
                _safe_set(self.COL_DURATION, duration_text)

                self._songs.append(s)
                fetched += 1

                if fetched % 25 == 0 and QCoreApplication is not None:
                    try:
                        QCoreApplication.processEvents()
                    except Exception:
                        pass

        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to load library: {exc}")
        finally:
            self._loading = False
            try:
                progress.close()
            except Exception:
                pass
            try:
                self.table.setSortingEnabled(True)
            except Exception:
                pass
            self._visible_rows = list(range(self.table.rowCount()))
            if progress.cancelled():
                self.info_label.setText(f"Loaded {fetched} song(s) (cancelled)")
            else:
                self.info_label.setText(f"All songs loaded: {fetched}")
            self._apply_filters()

    # ---------- Playlist creation ----------
    def _continue_to_review_selected(self) -> None:
        # Safety: Require a working connection first
        try:
            if not self.client.ping():
                QMessageBox.warning(self, "Navidrome", "Connection check failed. Please open Options > Plugins > Navidrome and click 'Test Connection' first.")
                return
        except Exception as exc:
            QMessageBox.warning(self, "Navidrome", f"Connection check failed: {exc}")
            return

        # Gather selected song ids and filenames in current table order
        selected: List[Tuple[str, str]] = []
        for r in range(self.table.rowCount()):
            try:
                it_chk = self.table.item(r, self.COL_FILENAME)
                if it_chk is None or it_chk.checkState() != Qt.Checked:  # type: ignore
                    continue
            except Exception:
                continue
            sid = self._song_id_for_row(r)
            if not sid:
                continue
            fname = ""
            try:
                it = self.table.item(r, self.COL_FILENAME)
                if it is not None:
                    fname = it.text() or ""
            except Exception:
                pass
            selected.append((sid, fname))

        if not selected:
            QMessageBox.information(self, "Navidrome", "No songs selected. Use the leftmost checkbox column to select tracks.")
            return

        # Open review dialog (draggable ordering with left/right drag handles)
        try:
            dlg = NavidromeSelectionReviewDialog(self, selected, previously_reviewed_ids=set(self._last_review_ids))
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Unable to open review: {exc}")
            return
        try:
            res = dlg.exec()
        except Exception:
            try:
                res = dlg.exec_()
            except Exception:
                dlg.show()
                return
        # If user accepted, proceed to create playlist with chosen order
        try:
            accepted = (res == QDialog.Accepted)
        except Exception:
            accepted = True
        # Update last reviewed ids with whatever was in this dialog attempt (so next time only truly new are green)
        try:
            self._last_review_ids = set(sid for sid, _ in selected)
        except Exception:
            pass
        if not accepted:
            # User clicked Add to List (reject). Just return to library to allow more selection.
            return
        ordered_ids = dlg.get_ordered_ids()
        if not ordered_ids:
            QMessageBox.information(self, "Navidrome", "No tracks to create a playlist from.")
            return

        # Ask for playlist name then create (remove '?' help button)
        try:
            dlg_name = QInputDialog(self)
            try:
                dlg_name.setInputMode(QInputDialog.TextInput)
                dlg_name.setWindowTitle("Create Playlist")
                dlg_name.setLabelText("Playlist name:")
            except Exception:
                pass
            try:
                dlg_name.setWindowFlag(Qt.WindowContextHelpButtonHint, False)  # type: ignore
            except Exception:
                try:
                    dlg_name.setWindowFlags(dlg_name.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore
                except Exception:
                    pass
            try:
                res_name = dlg_name.exec()
            except Exception:
                try:
                    res_name = dlg_name.exec_()
                except Exception:
                    dlg_name.show()
                    return
            try:
                ok = (res_name == QDialog.Accepted)
            except Exception:
                ok = True
            name = dlg_name.textValue() if ok else ""
        except Exception:
            ok = False
            name = ""
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.information(self, "Navidrome", "Playlist name cannot be empty.")
            return

        try:
            pl_id = self.client.create_playlist(name, ordered_ids)
        except Exception as exc:
            QMessageBox.critical(self, "Navidrome", f"Failed to create playlist: {exc}")
            return
        if pl_id:
            QMessageBox.information(self, "Navidrome", f"Playlist '{name}' created.")
        else:
            QMessageBox.information(self, "Navidrome", f"Playlist '{name}' created.")
        # Clear tracking after successful create
        try:
            self._last_review_ids.clear()
        except Exception:
            pass

    # ---------- Checkbox selection helpers ----------
    def _song_id_for_row(self, row: int) -> str:
        try:
            it = self.table.item(row, self.COL_FILENAME)
            if it is not None:
                sid = str(it.data(Qt.UserRole))  # type: ignore
                return sid or ""
        except Exception:
            pass
        try:
            return str(self._songs[row].get("id", ""))
        except Exception:
            return ""

    def _check_row(self, row: int, checked: bool) -> None:
        self._updating_checks = True
        try:
            it = self.table.item(row, self.COL_FILENAME)
            if it is None:
                it = QTableWidgetItem("")
                try:
                    it.setFlags((it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)  # type: ignore
                except Exception:
                    pass
                self.table.setItem(row, self.COL_FILENAME, it)
            it.setCheckState(Qt.Checked if checked else Qt.Unchecked)  # type: ignore
            sid = self._song_id_for_row(row)
            if sid:
                if checked:
                    self._checked_ids.add(sid)
                else:
                    self._checked_ids.discard(sid)
        except Exception:
            pass
        self._updating_checks = False
        self._update_counts()

    def _toggle_row(self, row: int) -> None:
        self._updating_checks = True
        try:
            it = self.table.item(row, self.COL_FILENAME)
            if it is None:
                it = QTableWidgetItem("")
                try:
                    it.setFlags((it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)  # type: ignore
                except Exception:
                    pass
                self.table.setItem(row, self.COL_FILENAME, it)
            current_checked = (it.checkState() == Qt.Checked)  # type: ignore
            new_checked = not current_checked
            it.setCheckState(Qt.Checked if new_checked else Qt.Unchecked)  # type: ignore
            sid = self._song_id_for_row(row)
            if sid:
                if new_checked:
                    self._checked_ids.add(sid)
                else:
                    self._checked_ids.discard(sid)
        except Exception:
            pass
        self._updating_checks = False
        self._update_counts()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        # Clicking anywhere in the row toggles the checkbox; clicking the checkbox also works
        # If multiple rows are selected, toggle all selected rows together.
        try:
            # If a drag just finished, only ignore the click on the release row
            release_row = getattr(self, "_just_finished_drag_release_row", None)
            if release_row is not None:
                self._just_finished_drag_release_row = None
                if row == release_row:
                    return
            # Clear any stale drag-move flag so subsequent clicks are processed normally
            self._drag_did_move = False
            # If the press started on the checkbox of the Filename column, let Qt handle it
            if col == self.COL_FILENAME and getattr(self, "_press_on_filename_checkbox", False):
                self._press_on_filename_checkbox = False
                return
            # Clicking any column (including Filename) toggles the row
            try:
                selected_rows = [mi.row() for mi in self.table.selectionModel().selectedRows()]
            except Exception:
                selected_rows = []

            # Determine rows we will act on
            rows_to_toggle = selected_rows if len(selected_rows) > 1 else [row]

            # Determine target state: use the clicked row's current state as reference (invert it)
            it_clicked_chk = self.table.item(row, self.COL_FILENAME)
            if it_clicked_chk is None:
                # Ensure there is a checkable item in Filename column
                it_clicked_chk = QTableWidgetItem("")
                try:
                    it_clicked_chk.setFlags((it_clicked_chk.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)  # type: ignore
                except Exception:
                    pass
                self.table.setItem(row, self.COL_FILENAME, it_clicked_chk)
            target_checked = not (it_clicked_chk.checkState() == Qt.Checked)  # type: ignore

            for r in rows_to_toggle:
                self._check_row(r, target_checked)
        except Exception:
            pass

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_checks or item is None:
            return
        try:
            if item.column() != self.COL_FILENAME:
                return
        except Exception:
            return
        try:
            # Update internal set for the clicked/edited row
            sid = self._song_id_for_row(item.row())
            if sid:
                if item.checkState() == Qt.Checked:  # type: ignore
                    self._checked_ids.add(sid)
                else:
                    self._checked_ids.discard(sid)

            # Propagate this new state to all other selected rows
            try:
                selected_rows = [mi.row() for mi in self.table.selectionModel().selectedRows()]
            except Exception:
                selected_rows = []
            if len(selected_rows) > 1:
                target_checked = (item.checkState() == Qt.Checked)  # type: ignore
                for r in selected_rows:
                    if r == item.row():
                        continue
                    self._check_row(r, target_checked)
        except Exception:
            pass
        self._update_counts()

    # Event filter to support click-drag selection toggling (invert on pass) without row drag
    def eventFilter(self, obj, event):  # type: ignore[override]
        try:
            if obj is self.table.viewport():
                et = event.type()
                if et == QEvent.MouseButtonPress:
                    # Initiate potential drag-select with left button, but do not toggle yet
                    try:
                        if event.button() != Qt.LeftButton:  # type: ignore
                            return False
                    except Exception:
                        pass
                    pos = event.pos()
                    # Allow drag-select to start in any column, including Filename
                    row = self.table.rowAt(pos.y())
                    if row is None or row < 0:
                        return False
                    # Detect if press is on the checkbox area of the Filename column
                    try:
                        col = self.table.columnAt(pos.x())
                        if col == self.COL_FILENAME:
                            rect = self.table.visualItemRect(self.table.item(row, self.COL_FILENAME))
                            # Heuristic: consider the left ~24px region as checkbox hit-zone
                            if pos.x() - rect.left() <= 24:
                                self._press_on_filename_checkbox = True
                            else:
                                self._press_on_filename_checkbox = False
                        else:
                            self._press_on_filename_checkbox = False
                    except Exception:
                        self._press_on_filename_checkbox = False
                    # Clear any previous blue selection on simple press so a single click
                    # won't act on previously selected rows
                    try:
                        self.table.clearSelection()
                        self.table.setCurrentCell(-1, -1)
                    except Exception:
                        pass
                    # No special press handling per column; unify click behavior across columns
                    self._drag_select_active = True
                    self._drag_anchor_row = row
                    self._drag_last_row = row
                    self._drag_prev_direction = 0
                    return False
                elif et == QEvent.MouseMove:
                    if not self._drag_select_active:
                        return False
                    pos = event.pos()
                    row = self.table.rowAt(pos.y())
                    if row is None or row < 0:
                        return False
                    last = self._drag_last_row
                    if last is None:
                        self._drag_last_row = row
                        return False
                    if row != last:
                        self._drag_did_move = True
                        step = 1 if row > last else -1
                        # Determine direction change to include reversal row immediately
                        current_direction = 1 if row > last else -1
                        if self._drag_prev_direction != 0 and current_direction != self._drag_prev_direction:
                            # Direction changed: toggle the row we are at (boundary) to mirror reversal
                            self._toggle_row(last)
                        # On very first move, also toggle the anchor so the starting row acts like others
                        if self._drag_prev_direction == 0 and self._drag_anchor_row is not None:
                            self._toggle_row(self._drag_anchor_row)
                        # Toggle each row passed through (excluding the previous last, including the current row)
                        for r in range(last + step, row + step, step):
                            self._toggle_row(r)
                        self._drag_prev_direction = current_direction
                        self._drag_last_row = row
                    return False
                elif et == QEvent.MouseButtonRelease:
                    # Capture the row under the mouse at release to suppress only that click
                    try:
                        pos = event.pos()
                        row = self.table.rowAt(pos.y())
                        self._just_finished_drag_release_row = row if (row is not None and row >= 0 and self._drag_did_move) else None
                    except Exception:
                        self._just_finished_drag_release_row = None
                    # End drag-select and reset state
                    self._drag_select_active = False
                    self._drag_last_row = None
                    self._drag_anchor_row = None
                    self._drag_prev_direction = 0
                    # Clear move flag so the next distinct click is processed
                    self._drag_did_move = False
                    return False
        except Exception:
            pass
        return False

    def _check_all_visible(self) -> None:
        # Check all currently visible rows
        for r in range(self.table.rowCount()):
            try:
                if self.table.isRowHidden(r):
                    continue
            except Exception:
                pass
            self._check_row(r, True)
        self._update_counts()

    # Default event handling
    def event(self, e):  # type: ignore[override]
        try:
            return super().event(e)
        except Exception:
            return False

    # --- Header move guard to keep Filename fixed at index 0 ---
    def _on_header_moved(self, logicalIndex: int, oldVisualIndex: int, newVisualIndex: int) -> None:
        try:
            if getattr(self, "_suppress_header_move", False):
                return
            if logicalIndex == self.COL_FILENAME or newVisualIndex == 0 or oldVisualIndex == 0:
                # Reassert Filename at position 0; restore other section to its place
                self._suppress_header_move = True
                hh = self.table.horizontalHeader()
                try:
                    vi = hh.visualIndex(self.COL_FILENAME)
                    if vi != 0:
                        hh.moveSection(vi, 0)
                finally:
                    self._suppress_header_move = False
        except Exception:
            pass


# -----------------------------
# Library dialog for adding songs to existing playlist
# -----------------------------
class NavidromeLibraryDialogForAddingSongs(NavidromeLibraryDialog):
    """Same as NavidromeLibraryDialog but with 'Apply' button instead of 'Continue and Review playlist'."""
    def __init__(self, parent: Optional[QWidget], client: SubsonicClient) -> None:
        super().__init__(parent, client)
        self.setWindowTitle("Select Tracks from Navidrome Library")
        self.selected_track_ids: List[str] = []
        
        # Replace the "Continue and Review playlist" button with "Apply"
        try:
            self.continue_button.setText("Apply")
            self.continue_button.setToolTip("Add selected tracks to playlist")
            # Disconnect old connection and connect new one
            try:
                self.continue_button.clicked.disconnect()  # type: ignore[attr-defined]
            except Exception:
                pass
            self.continue_button.clicked.connect(self._apply_selection)  # type: ignore[attr-defined]
        except Exception:
            pass
    
    def _apply_selection(self) -> None:
        """Collect selected track IDs and close dialog."""
        # Safety: Require a working connection first
        try:
            if not self.client.ping():
                QMessageBox.warning(self, "Navidrome", "Connection check failed. Please open Options > Plugins > Navidrome and click 'Test Connection' first.")
                return
        except Exception as exc:
            QMessageBox.warning(self, "Navidrome", f"Connection check failed: {exc}")
            return
        
        # Gather selected song ids in current table order
        selected_ids: List[str] = []
        for r in range(self.table.rowCount()):
            try:
                it_chk = self.table.item(r, self.COL_FILENAME)
                if it_chk is None or it_chk.checkState() != Qt.Checked:  # type: ignore
                    continue
            except Exception:
                continue
            sid = self._song_id_for_row(r)
            if not sid:
                continue
            selected_ids.append(sid)
        
        if not selected_ids:
            QMessageBox.information(self, "Navidrome", "No tracks selected!")
            return
        
        # Store the selected IDs and accept the dialog
        self.selected_track_ids = selected_ids
        self.accept()


# -----------------------------
# Options wrapper dialog for "Connect..."
# -----------------------------
class NavidromeOptionsDialog(QDialog):
    """Wraps the NavidromeOptionsPage inside a plain dialog."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Navidrome")
        try:
            self.resize(500, 150)
            self.setMinimumWidth(300)
        except Exception:
            pass
        self.page = NavidromeOptionsPage(self)
        self.page.load()
        # Hide extra buttons in this connect dialog
        try:
            if hasattr(self.page, "browse_button") and self.page.browse_button is not None:
                self.page.browse_button.hide()
        except Exception:
            pass
        try:
            if hasattr(self.page, "library_button") and self.page.library_button is not None:
                self.page.library_button.hide()
        except Exception:
            pass
        try:
            if hasattr(self.page, "about_button") and self.page.about_button is not None:
                self.page.about_button.hide()
        except Exception:
            pass

        v = QVBoxLayout(self)
        v.addWidget(self.page)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        try:
            buttons.rejected.connect(self.reject)  # type: ignore[attr-defined]
        except Exception:
            pass
        v.addWidget(buttons)

    def closeEvent(self, event) -> None:
        """Automatically save settings when dialog is closed."""
        try:
            self.page.save()
        except Exception:
            pass
        super().closeEvent(event)


# -----------------------------
# Missing function definitions
# -----------------------------
def _nav_parent_window():
    """Get the main Picard window."""
    try:
        return QApplication.activeWindow()
    except Exception:
        return None

def _open_library_dialog():
    """Open the library dialog."""
    try:
        base_url = config.setting["navidrome_base_url"].strip()
        username = config.setting["navidrome_username"].strip()
        password = config.setting["navidrome_password"]
        verify_ssl = bool(config.setting["navidrome_verify_ssl"])
        
        if not base_url or not username or not password:
            QMessageBox.warning(None, "Navidrome", "Please configure Navidrome settings in Options > Plugins > Navidrome.")
            return
        
        try:
            enable_cache = bool(config.setting["navidrome_enable_cache"])
        except (KeyError, ValueError):
            enable_cache = True
        client = SubsonicClient(
            base_url=base_url, 
            username=username, 
            password=password, 
            verify_ssl=verify_ssl,
            enable_cache=enable_cache
        )
        dlg = NavidromeLibraryDialog(None, client)
        try:
            dlg.exec()
        except Exception:
            try:
                dlg.exec_()
            except Exception:
                dlg.show()
    except Exception as exc:
        QMessageBox.critical(None, "Navidrome", f"Error: {exc}")

def _open_connect_dialog() -> None:
    parent = _nav_parent_window()
    try:
        dlg = NavidromeOptionsDialog(parent)
        try:
            dlg.exec()
        except Exception:
            try:
                dlg.exec_()
            except Exception:
                dlg.show()
    except Exception as exc:
        QMessageBox.critical(parent, "Navidrome", f"Unable to open dialog: {exc}")

def _open_playlists_dialog():
    """Open the playlists dialog."""
    try:
        base_url = config.setting["navidrome_base_url"].strip()
        username = config.setting["navidrome_username"].strip()
        password = config.setting["navidrome_password"]
        verify_ssl = bool(config.setting["navidrome_verify_ssl"])
        
        if not base_url or not username or not password:
            QMessageBox.warning(None, "Navidrome", "Please configure Navidrome settings in Options > Plugins > Navidrome.")
            return
            
        client = SubsonicClient(base_url=base_url, username=username, password=password, verify_ssl=verify_ssl)
        dlg = NavidromeBrowserDialog(None, client)
        try:
            dlg.exec()
        except Exception:
            try:
                dlg.exec_()
            except Exception:
                dlg.show()
    except Exception as exc:
        QMessageBox.critical(None, "Navidrome", f"Error: {exc}")


# -----------------------------
# About dialog
# -----------------------------
class NavidromeAboutDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Picard - Navidrome Integration Plugin")
        try:
            self.resize(520, 360)
        except Exception:
            pass
        try:
            self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore
            except Exception:
                pass

        main = QVBoxLayout(self)

        title = QLabel("Navidrome (Subsonic) Integration for Picard", self)
        try:
            f = title.font()
            f.setPointSize(f.pointSize() + 2)
            f.setBold(True)
            title.setFont(f)
        except Exception:
            pass
        main.addWidget(title)

        info = QLabel(
            "Developed by <b>Viktor Shepotynnyk</b><br>"
            "If you enjoy this plugin, consider buying me a coffee ❤ ☕",
            self,
        )
        try:
            info.setTextFormat(Qt.RichText)  # type: ignore
        except Exception:
            pass
        info.setWordWrap(True)
        main.addWidget(info)

        # Version row (bold)
        version = QLabel(f"<b>Version: {PLUGIN_VERSION}</b>", self)
        try:
            version.setTextFormat(Qt.RichText)  # type: ignore
        except Exception:
            pass
        main.addWidget(version)

        # Compatibility row (rich text)
        compat = QLabel(
            "<b>Compatibility</b><br>"
            "Picard API: 2.0–2.14<br>"
            "Subsonic API: 1.16.1+ (Navidrome compatible)<br>"
            "Docker Picard: supported",
            self,
        )
        try:
            compat.setTextFormat(Qt.RichText)  # type: ignore
        except Exception:
            pass
        compat.setWordWrap(True)
        main.addWidget(compat)

        # Links row
        links_row = QHBoxLayout()
        btn_paypal = QPushButton("☕❤ Donate", self)
        btn_paypal.setToolTip("Open PayPal (paypal.me/vikshepo)")
        btn_github = QPushButton("GitHub Repository", self)
        btn_changelog = QPushButton("Changelog", self)

        # Highlight Donate button
        try:
            btn_paypal.setStyleSheet("font-weight: bold; background-color: #FFE08A;")
        except Exception:
            pass
        try:
            btn_paypal.setDefault(True)
            btn_paypal.setAutoDefault(True)
        except Exception:
            pass

        def open_url(url: str) -> None:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        try:
            btn_paypal.clicked.connect(lambda: open_url("https://paypal.me/vikshepo"))  # type: ignore[attr-defined]
            btn_github.clicked.connect(lambda: open_url("https://github.com/VikShepo/picard-navidrome-intergration"))  # type: ignore[attr-defined]
            # In-app changelog dialog
            btn_changelog.clicked.connect(_open_changelog_dialog)  # type: ignore[attr-defined]
        except Exception:
            pass

        links_row.addWidget(btn_paypal)
        links_row.addWidget(btn_github)
        links_row.addWidget(btn_changelog)
        links_row.addStretch(1)
        main.addLayout(links_row)

        # Ensure Donate is focused when dialog opens
        try:
            btn_paypal.setFocus()
        except Exception:
            pass

        # Cute sentence
        cute = QLabel("<i>Thanks for using this plugin! Your support keeps the music playing.</i>", self)
        try:
            cute.setTextFormat(Qt.RichText)  # type: ignore
        except Exception:
            pass
        cute.setWordWrap(True)
        main.addWidget(cute)

        # Social icon buttons (centered)
        social_row = QHBoxLayout()
        try:
            social_row.setAlignment(Qt.AlignCenter)  # type: ignore
        except Exception:
            pass
        fb_btn = QToolButton(self)
        fb_btn.setText("📘")
        fb_btn.setToolTip("Facebook")
        gh_btn = QToolButton(self)
        gh_btn.setText("🐙")
        gh_btn.setToolTip("GitHub")
        ig_btn = QToolButton(self)
        ig_btn.setText("📸")
        ig_btn.setToolTip("Instagram")
        try:
            fb_btn.clicked.connect(lambda: open_url("https://www.facebook.com/Vikiller94"))  # type: ignore[attr-defined]
            gh_btn.clicked.connect(lambda: open_url("https://github.com/VikShepo/picard-navidrome-intergration"))  # type: ignore[attr-defined]
            ig_btn.clicked.connect(lambda: open_url("https://www.instagram.com/notorious_vik_"))  # type: ignore[attr-defined]
        except Exception:
            pass
        # Add text labels under each icon button
        fb_col = QVBoxLayout()
        try:
            fb_col.setAlignment(Qt.AlignHCenter)  # type: ignore
        except Exception:
            pass
        fb_col.addWidget(fb_btn, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        fb_label = QLabel("Facebook", self)
        try:
            fb_label.setAlignment(Qt.AlignHCenter)  # type: ignore
        except Exception:
            pass
        fb_col.addWidget(fb_label, 0, Qt.AlignHCenter)  # type: ignore[arg-type]

        gh_col = QVBoxLayout()
        try:
            gh_col.setAlignment(Qt.AlignHCenter)  # type: ignore
        except Exception:
            pass
        gh_col.addWidget(gh_btn, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        gh_label = QLabel("GitHub", self)
        try:
            gh_label.setAlignment(Qt.AlignHCenter)  # type: ignore
        except Exception:
            pass
        gh_col.addWidget(gh_label, 0, Qt.AlignHCenter)  # type: ignore[arg-type]

        ig_col = QVBoxLayout()
        try:
            ig_col.setAlignment(Qt.AlignHCenter)  # type: ignore
        except Exception:
            pass
        ig_col.addWidget(ig_btn, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        ig_label = QLabel("Instagram", self)
        try:
            ig_label.setAlignment(Qt.AlignHCenter)  # type: ignore
        except Exception:
            pass
        ig_col.addWidget(ig_label, 0, Qt.AlignHCenter)  # type: ignore[arg-type]

        social_row.addLayout(fb_col)
        social_row.addLayout(gh_col)
        social_row.addLayout(ig_col)
        try:
            social_row.setAlignment(Qt.AlignCenter)  # type: ignore
        except Exception:
            pass
        main.addLayout(social_row)

        # Close
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        try:
            buttons.rejected.connect(self.reject)  # type: ignore[attr-defined]
        except Exception:
            pass
        main.addWidget(buttons)


def _open_about_dialog() -> None:
    parent = _nav_parent_window()
    try:
        dlg = NavidromeAboutDialog(parent)
        try:
            dlg.exec()
        except Exception:
            try:
                dlg.exec_()
            except Exception:
                dlg.show()
    except Exception as exc:
        QMessageBox.critical(parent, "Navidrome", f"Unable to open About: {exc}")


# -----------------------------
# Changelog dialog
# -----------------------------
class NavidromeChangelogDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Changelog")
        try:
            self.resize(700, 500)
        except Exception:
            pass
        try:
            self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore
            except Exception:
                pass

        layout = QVBoxLayout(self)

        header = QLabel("What's new", self)
        try:
            f = header.font()
            f.setBold(True)
            header.setFont(f)
        except Exception:
            pass
        layout.addWidget(header)

        # Use a read-only text area for rich content and easy scrolling
        text = QTextEdit(self)
        try:
            text.setReadOnly(True)
        except Exception:
            pass

        # Build a comprehensive bullet list per version. Update as you release.
        changelog_lines: List[str] = []
        def add_version(ver: str, bullets: List[str]) -> None:
            changelog_lines.append(f"Version {ver}")
            for b in bullets:
                changelog_lines.append(f"  - {b}")
            changelog_lines.append("")

        add_version(
            "0.7.1",
            [
                "➕ NEW: 'Add new Track' button to add songs to existing playlists",
                "🎯 NEW: Dedicated dialog for adding tracks with 'Apply' button (reuses library browser UI)",
                "✨ NEW: Green highlighting for newly added tracks (visible until playlist switch or modification)",
                "👤 NEW: Owner label showing playlist ownership (e.g., 'Owner: username')",
                "🔒 NEW: Ownership-based permission system - non-owners have read-only access to public playlists",
                "🚫 SECURITY: All modification buttons disabled for playlists you don't own",
                "🚫 SECURITY: Rename, Delete, Add Track, Remove Track, Randomize, and Make Public restricted to owners",
                "🔔 UX: Clear tooltips explain why buttons are disabled for non-owned playlists",
                "💾 CACHE: Removed TTL expiration - cache now persists until manually cleared",
                "💾 CACHE: Simplified caching system for better performance and consistency",
                "🎨 UI: Track Actions reorganized - Randomize, Add new Track, Remove Track order",
                "🎨 UI: Owner label displays with bold 'Owner:' and normal username in user-friendly blue",
                "🔧 Technical: Ownership checking on all modification operations",
                "🔧 Technical: Cache simplification removes TTL logic and parameters",
                "Bugfixes and improvements"
            ],
        )
        add_version(
            "0.7.0",
            [
                "🚀 NEW: Smart caching system for dramatically faster subsequent fetches",
                "🔧 Clear Cache button in options for testing and troubleshooting",
                "📈 Performance boost: Second and subsequent library fetches are much faster",
                "💾 In-memory cache for optimal performance",
                "🎯 Cache keys based on request parameters for optimal hit rates",
                "🔧 Enhanced SubsonicClient with cache statistics and management",
                "📊 FIXED: Progress bar now shows accurate 100% completion when all songs are fetched",
                "🎨 UI Polish: Enhanced progress dialog with percentage and window title updates",
                "🎨 UI Polish: Better status text showing current/total counts",
                "🔧 Technical: Two-pass algorithm for accurate progress calculation",
                "🔧 Technical: Global cache sharing across all SubsonicClient instances",
                "Bugfixes and improvements"
            ],
        )
        add_version(
            "0.6.0",
            [
                "New Navidrome menu: Connect…, Create Playlist from Library…, Edit Playlists…",
                "Options page (URL, credentials, SSL verify, save credentials) + status check",
                "Library browser: Filter menu, search across visible columns, adjustable columns/rows",
                "Playlist creation from selected rows; ID order preserved regardless of UI sort",
                "Live progress dialog while fetching songs (\"Fetched X of Y\")",
                "Playlists browser with safe local drag-and-drop reordering and visual cues",
                "Subsonic client with salted token authentication and SSL toggle",
                "Added 'About…' to Navidrome menu and Options page",
                "Bugfixes and improvements"
            ],
        )
        add_version(
            "0.5.x",
            [
                "Initial Subsonic connectivity and basic browsing",
                "Picard options page with credentials and SSL verification",
            ],
        )

        text.setPlainText("\n".join(changelog_lines))
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        try:
            buttons.rejected.connect(self.reject)  # type: ignore[attr-defined]
        except Exception:
            pass
        layout.addWidget(buttons)


def _open_changelog_dialog() -> None:
    parent = _nav_parent_window()
    try:
        dlg = NavidromeChangelogDialog(parent)
        try:
            dlg.exec()
        except Exception:
            try:
                dlg.exec_()
            except Exception:
                dlg.show()
    except Exception as exc:
        QMessageBox.critical(parent, "Navidrome", f"Unable to open Changelog: {exc}")

class NavidromeSelectionReviewDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], selected: List[Tuple[str, str]], previously_reviewed_ids: Optional[Set[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Review Selected Tracks")
        try:
            self.resize(700, 500)
        except Exception:
            pass
        # Configure window buttons: disable Context Help ("?") and enable Minimize/Maximize
        try:
            self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore
            except Exception:
                pass
        try:
            self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)  # type: ignore
        except Exception:
            try:
                self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)  # type: ignore
            except Exception:
                pass

        info = QLabel("Drag tracks to order your playlist. Only track filenames are shown.", self)
        try:
            font = info.font()
            font.setItalic(True)
            info.setFont(font)
        except Exception:
            pass

        self.list = _DraggableListWidget(self)
        try:
            # Enable dragging by allowing selection and internal move
            self.list.setSelectionMode(QAbstractItemView.SingleSelection)  # type: ignore[attr-defined]
            self.list.setDragEnabled(True)
            self.list.setAcceptDrops(True)
            self.list.setDropIndicatorShown(True)
            self.list.setDragDropMode(QAbstractItemView.InternalMove)  # type: ignore[attr-defined]
            try:
                self.list.setDragDropOverwriteMode(False)
            except Exception:
                pass
            try:
                # Prefer move action over copy
                from PyQt5.QtCore import Qt as _Qt  # type: ignore
                self.list.setDefaultDropAction(_Qt.MoveAction)  # type: ignore[attr-defined]
            except Exception:
                try:
                    self.list.setDefaultDropAction(Qt.MoveAction)  # type: ignore[attr-defined]
                except Exception:
                    pass
            try:
                self.list.setAlternatingRowColors(True)
            except Exception:
                pass
        except Exception:
            pass

        # Prepare ordering: previously reviewed first, newly added at the end
        prev_ids = set(previously_reviewed_ids or set())
        prev_items: List[Tuple[str, str]] = []
        new_items: List[Tuple[str, str]] = []
        for sid, fname in selected:
            if sid in prev_ids:
                prev_items.append((sid, fname))
            else:
                new_items.append((sid, fname))

        ordered_items = prev_items + new_items

        # Populate list with custom row widgets including left/right handles
        has_new_items = False
        for sid, fname in ordered_items:
            try:
                item = QListWidgetItem()
                try:
                    item.setData(Qt.UserRole, sid)  # type: ignore
                except Exception:
                    pass
                try:
                    # Ensure item can be dragged
                    item.setFlags(item.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)  # type: ignore
                except Exception:
                    pass
                # Custom row
                row_w = QWidget(self)
                h = QHBoxLayout(row_w)
                try:
                    h.setContentsMargins(8, 4, 8, 4)
                except Exception:
                    pass
                order = QLabel("", row_w)  # dynamic order number
                left = QLabel("≡", row_w)  # left drag handle
                mid = QLabel(str(fname or ""), row_w)
                right = QLabel("≡", row_w)  # right drag handle
                # Highlight newly added tracks with a subtle green tint on the filename only
                try:
                    if prev_ids and (sid not in prev_ids):
                        # Apply tint to the filename label so alternating row colors remain visible
                        mid.setStyleSheet("background-color: rgba(0, 200, 0, 40); border-radius: 3px; padding: 2px 4px;")
                        has_new_items = True
                except Exception:
                    pass
                try:
                    order.setMinimumWidth(28)
                    order.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore
                    left.setToolTip("Drag to reorder")
                    right.setToolTip("Drag to reorder")
                except Exception:
                    pass
                try:
                    # Visual cursor hints
                    left.setCursor(Qt.OpenHandCursor)  # type: ignore
                    right.setCursor(Qt.OpenHandCursor)  # type: ignore
                    mid.setCursor(Qt.OpenHandCursor)  # type: ignore
                    row_w.setCursor(Qt.OpenHandCursor)  # type: ignore
                except Exception:
                    pass
                # Layout: [order][sp][left drag][filename][right drag]
                h.addWidget(order, 0)
                spacer = QLabel("", row_w)
                try:
                    spacer.setMinimumWidth(4)
                except Exception:
                    pass
                h.addWidget(spacer, 0)
                h.addWidget(left, 0)
                h.addWidget(mid, 1)
                h.addWidget(right, 0)
                self.list.addItem(item)
                try:
                    # Make row taller for better drag target
                    item.setSizeHint(row_w.sizeHint())
                except Exception:
                    pass
                self.list.setItemWidget(item, row_w)
                try:
                    # attach for later renumbering
                    row_w._num_label = order  # type: ignore[attr-defined]
                except Exception:
                    pass
                # Ensure drag works when clicking on embedded widgets by letting events pass through
                try:
                    for wgt in (row_w, order, left, mid, right):
                        wgt.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # type: ignore
                except Exception:
                    pass
            except Exception:
                continue

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        try:
            buttons.accepted.connect(self.accept)  # type: ignore[attr-defined]
            buttons.rejected.connect(self.reject)  # type: ignore[attr-defined]
        except Exception:
            pass

        # Left-side actions panel
        left_panel = QVBoxLayout()
        try:
            lbl_actions = QLabel("Actions", self)
            try:
                font = lbl_actions.font()
                font.setBold(True)
                lbl_actions.setFont(font)
            except Exception:
                pass
            lbl_actions.setToolTip("Add more files or remove the selected one from this list")
            left_panel.addWidget(lbl_actions)
        except Exception:
            pass
        try:
            self._btn_add_more_left = QPushButton("+ Add to List", self)
            try:
                self._btn_add_more_left.setToolTip("Return to the previous window to add more items")
            except Exception:
                pass
            try:
                self._btn_add_more_left.setStyleSheet("color: #1b5e20;")
            except Exception:
                pass
            self._btn_add_more_left.clicked.connect(self._return_to_library_for_more)  # type: ignore[attr-defined]
            left_panel.addWidget(self._btn_add_more_left)
        except Exception:
            pass
        try:
            self._btn_delete_left = QPushButton("− Delete from List", self)
            try:
                self._btn_delete_left.setStyleSheet("color: #b00020;")
            except Exception:
                pass
            try:
                self._btn_delete_left.setToolTip("Remove the selected entry from this list (Delete)")
            except Exception:
                pass
            self._btn_delete_left.clicked.connect(self._delete_selected_from_list)  # type: ignore[attr-defined]
            left_panel.addWidget(self._btn_delete_left)
        except Exception:
            pass
        try:
            self._btn_randomize_left = QPushButton("🎲 Randomize", self)
            try:
                self._btn_randomize_left.setToolTip("Shuffle the track order randomly")
            except Exception:
                pass
            try:
                self._btn_randomize_left.setStyleSheet("color: #6200ea;")
            except Exception:
                pass
            self._btn_randomize_left.clicked.connect(self._randomize_tracks)  # type: ignore[attr-defined]
            left_panel.addWidget(self._btn_randomize_left)
        except Exception:
            pass
        try:
            left_panel.addStretch(1)
        except Exception:
            pass

        left_container = QWidget(self)
        left_container.setLayout(left_panel)
        try:
            left_container.setFixedWidth(200)  # Fixed width in pixels
        except Exception:
            pass

        middle = QHBoxLayout()
        middle.addWidget(left_container, 0)  # Fixed width left panel
        middle.addWidget(self.list, 1)       # Flexible track list

        v = QVBoxLayout(self)
        v.addWidget(info)
        v.addLayout(middle, 1)
        v.addWidget(buttons)

        # Keyboard shortcuts and initial focus/scroll
        try:
            from PyQt5.QtWidgets import QShortcut  # type: ignore
        except Exception:
            try:
                from PySide2.QtWidgets import QShortcut  # type: ignore
            except Exception:
                QShortcut = None  # type: ignore
        try:
            from PyQt5.QtGui import QKeySequence  # type: ignore
        except Exception:
            try:
                from PySide2.QtGui import QKeySequence  # type: ignore
            except Exception:
                QKeySequence = None  # type: ignore

        # Delete key removes current item
        try:
            if QShortcut is not None and QKeySequence is not None:
                del_shortcut = QShortcut(QKeySequence.Delete, self)
                del_shortcut.activated.connect(self._delete_selected_from_list)  # type: ignore[attr-defined]
        except Exception:
            pass
        # Ctrl+Enter to accept
        try:
            if QShortcut is not None and QKeySequence is not None:
                ok_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
                ok_shortcut.activated.connect(self.accept)  # type: ignore[attr-defined]
        except Exception:
            pass
        # Focus list and scroll to bottom if new items appended
        try:
            self.list.setFocus()
            if has_new_items:
                self.list.scrollToBottom()
        except Exception:
            pass

        # Initial numbering
        self._renumber_rows()
        # Update numbering after reorders
        try:
            self.list.model().rowsMoved.connect(lambda *args: self._renumber_rows())  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self.list.model().rowsInserted.connect(lambda *args: self._renumber_rows())  # type: ignore[attr-defined]
            self.list.model().rowsRemoved.connect(lambda *args: self._renumber_rows())  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self.list.installEventFilter(self)
            self.list.viewport().installEventFilter(self)
        except Exception:
            pass

    def _delete_selected_from_list(self) -> None:
        try:
            row = self.list.currentRow()
        except Exception:
            row = -1
        if row is None or row < 0:
            QMessageBox.information(self, "Navidrome", "No track selected for deletion. Nothing deleted from playlist.")
            return
        try:
            it = self.list.takeItem(row)
            # Ensure widget is cleaned up
            if it is not None:
                del it
        except Exception:
            pass
        # Renumber after removal
        self._renumber_rows()
        # Keep selection user-friendly: select the next item if available, otherwise the last one
        try:
            count = self.list.count()
            if count > 0:
                next_row = row if row < count else count - 1
                self.list.setCurrentRow(next_row)
        except Exception:
            pass

    def _return_to_library_for_more(self) -> None:
        # Close the review dialog without accepting so user returns to the library window
        try:
            self.reject()
        except Exception:
            pass

    def _randomize_tracks(self) -> None:
        """Shuffle the track order randomly."""
        import random
        try:
            # Get all items and their data
            items_data = []
            for i in range(self.list.count()):
                item = self.list.item(i)
                if item is None:
                    continue
                widget = self.list.itemWidget(item)
                try:
                    song_id = str(item.data(Qt.UserRole))  # type: ignore
                except Exception:
                    song_id = ""
                if widget is not None and song_id:
                    items_data.append((song_id, widget))
            
            if len(items_data) <= 1:
                return  # Nothing to shuffle
            
            # Extract song IDs and shuffle them
            song_ids = [data[0] for data in items_data]
            random.shuffle(song_ids)
            
            # Clear the list
            self.list.clear()
            
            # Re-add items in shuffled order
            # We need to reconstruct the items since we cleared the list
            for i, shuffled_song_id in enumerate(song_ids):
                # Find the original data for this song ID
                original_widget_data = None
                for original_song_id, widget in items_data:
                    if original_song_id == shuffled_song_id:
                        original_widget_data = widget
                        break
                
                if original_widget_data is None:
                    continue
                
                # Create new item
                item = QListWidgetItem()
                try:
                    item.setData(Qt.UserRole, shuffled_song_id)  # type: ignore
                except Exception:
                    pass
                try:
                    item.setFlags(item.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)  # type: ignore
                except Exception:
                    pass
                
                # Create new widget based on the original
                row_w = QWidget(self)
                h = QHBoxLayout(row_w)
                try:
                    h.setContentsMargins(8, 4, 8, 4)
                except Exception:
                    pass
                
                order = QLabel("", row_w)  # Will be updated by _renumber_rows
                left = QLabel("≡", row_w)
                
                # Extract filename from original widget
                filename = ""
                try:
                    # Try to get the filename from the original widget's middle label
                    for child in original_widget_data.findChildren(QLabel):
                        text = child.text()
                        if text and text not in ["≡", ""]:
                            # Skip order numbers (like "1.", "2.", etc.)
                            if not (text.endswith(".") and text[:-1].isdigit()):
                                filename = text
                                break
                except Exception:
                    filename = f"Track {i+1}"
                
                mid = QLabel(str(filename), row_w)
                right = QLabel("≡", row_w)
                
                try:
                    order.setMinimumWidth(28)
                    order.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore
                    left.setToolTip("Drag to reorder")
                    right.setToolTip("Drag to reorder")
                except Exception:
                    pass
                try:
                    left.setCursor(Qt.OpenHandCursor)  # type: ignore
                    right.setCursor(Qt.OpenHandCursor)  # type: ignore
                    mid.setCursor(Qt.OpenHandCursor)  # type: ignore
                    row_w.setCursor(Qt.OpenHandCursor)  # type: ignore
                except Exception:
                    pass
                
                # Layout
                h.addWidget(order, 0)
                spacer = QLabel("", row_w)
                try:
                    spacer.setMinimumWidth(4)
                except Exception:
                    pass
                h.addWidget(spacer, 0)
                h.addWidget(left, 0)
                h.addWidget(mid, 1)
                h.addWidget(right, 0)
                
                self.list.addItem(item)
                try:
                    item.setSizeHint(row_w.sizeHint())
                except Exception:
                    pass
                self.list.setItemWidget(item, row_w)
                try:
                    row_w._num_label = order  # type: ignore[attr-defined]
                except Exception:
                    pass
                
                # Make widgets transparent for mouse events
                try:
                    for wgt in (row_w, order, left, mid, right):
                        wgt.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # type: ignore
                except Exception:
                    pass
            
            # Renumber the tracks
            self._renumber_rows()
            
        except Exception as exc:
            # If randomization fails, show a message but don't crash
            try:
                QMessageBox.warning(self, "Randomize", f"Failed to randomize tracks: {exc}")
            except Exception:
                pass

    def get_ordered_ids(self) -> List[str]:
        ids: List[str] = []
        try:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it is None:
                    continue
                try:
                    sid = str(it.data(Qt.UserRole))  # type: ignore
                except Exception:
                    sid = ""
                if sid:
                    ids.append(sid)
        except Exception:
            pass
        return ids

    def _renumber_rows(self) -> None:
        try:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it is None:
                    continue
                w = self.list.itemWidget(it)
                if w is None:
                    continue
                try:
                    if hasattr(w, "_num_label") and w._num_label is not None:  # type: ignore[attr-defined]
                        w._num_label.setText(f"{i+1}.")
                except Exception:
                    pass
        except Exception:
            pass

    # Ensure numbering updates even if only Drop event fires
    def eventFilter(self, obj, event):  # type: ignore[override]
        try:
            et = event.type()
            if et == QEvent.Drop:
                self._renumber_rows()
        except Exception:
            pass
        return False

def _ensure_menu_installed(_attempt: int = 0) -> None:
    """Insert 'Navidrome' menu near Help/Tools on the main menu bar."""
    parent = _nav_parent_window()
    if not parent:
        if _attempt < 30:
            try:
                QTimer.singleShot(300, lambda: _ensure_menu_installed(_attempt + 1))  # type: ignore[attr-defined]
            except Exception:
                pass
        return
    try:
        menubar = parent.menuBar()
    except Exception:
        menubar = None

    if menubar is None:
        if _attempt < 30:
            try:
                QTimer.singleShot(300, lambda: _ensure_menu_installed(_attempt + 1))  # type: ignore[attr-defined]
            except Exception:
                pass
        return

    # Avoid duplicates
    for act in menubar.actions():
        try:
            m = act.menu()
            if m and m.objectName() == "menuNavidrome":
                return
        except Exception:
            continue

    try:
        nav_menu = menubar.addMenu("Navidrome")
        nav_menu.setObjectName("menuNavidrome")
        _a_connect = nav_menu.addAction("Connect...")
        _a_library = nav_menu.addAction("Create Playlist from Navidrome Library...")
        _a_playlists = nav_menu.addAction("Edit Playlists in Navidrome...")
        _a_about = nav_menu.addAction("About...")
        _a_connect.triggered.connect(_open_connect_dialog)  # type: ignore[attr-defined]
        _a_library.triggered.connect(_open_library_dialog)  # type: ignore[attr-defined]
        _a_playlists.triggered.connect(_open_playlists_dialog)  # type: ignore[attr-defined]
        _a_about.triggered.connect(_open_about_dialog)  # type: ignore[attr-defined]
    except Exception:
        return

    # Try to position menu near Help or after Tools
    try:
        actions = menubar.actions()
        help_act = None
        tools_index = None
        for i, act in enumerate(actions):
            try:
                text = act.text()
            except Exception:
                text = ""
            if text.replace("&", "") == "Help" and help_act is None:
                help_act = act
            if text.replace("&", "") == "Tools" and tools_index is None:
                tools_index = i
        if help_act is not None:
            menubar.removeAction(nav_menu.menuAction())
            menubar.insertMenu(help_act, nav_menu)
        elif tools_index is not None and tools_index + 1 < len(actions):
            after_act = actions[tools_index + 1]
            menubar.removeAction(nav_menu.menuAction())
            menubar.insertMenu(after_act, nav_menu)
    except Exception:
        pass

# Schedule installation
try:
    if QTimer is not None:
        QTimer.singleShot(0, _ensure_menu_installed)  # type: ignore[attr-defined]
except Exception:
    pass

# -----------------------------
# Registration with Picard
# -----------------------------
try:
    register_options_page(NavidromeOptionsPage)
except Exception as exc:
    log.error("Navidrome plugin: Failed to register options page: %r", exc)

# NavidromeFetchPlaylistsAction registration removed per user request

# NavidromeBrowseAction registration removed per user request

try:
    # Create playlist from selection action
    class NavidromeCreatePlaylistFromSelectionAction(BaseAction):
        NAME = "Create playlist and send to Navidrome ..."
        TITLE = "Create playlist and send to Navidrome ..."
        def callback(self, objs) -> None:
            parent = _nav_parent_window()
            # Try to resolve highlighted (selected) items from Picard's left panel
            selected_basenames: List[str] = []
            try:
                seen: Set[str] = set()
                for o in (objs or []):
                    # Album/cluster-like with .files
                    try:
                        files = getattr(o, "files", None)
                        if files:
                            for f in files:
                                try:
                                    p = getattr(f, "filename", None) or getattr(f, "path", None) or getattr(f, "_filename", None)
                                    if p:
                                        bn = os.path.basename(str(p))
                                        if bn not in seen:
                                            selected_basenames.append(bn)
                                            seen.add(bn)
                                except Exception:
                                    continue
                            continue
                    except Exception:
                        pass
                    # Track/file-like directly
                    try:
                        p = getattr(o, "filename", None) or getattr(o, "path", None) or getattr(o, "_filename", None)
                        if p:
                            bn = os.path.basename(str(p))
                            if bn not in seen:
                                selected_basenames.append(bn)
                                seen.add(bn)
                    except Exception:
                        pass
            except Exception:
                selected_basenames = []

            if selected_basenames:
                # Connect using saved settings
                base_url = config.setting["navidrome_base_url"].strip()
                username = config.setting["navidrome_username"].strip()
                password = config.setting["navidrome_password"]
                app_name = "PicardNavidrome"
                verify_ssl = bool(config.setting["navidrome_verify_ssl"])
                if not base_url or not username or not password:
                    QMessageBox.warning(parent, "Navidrome", "Please fill in Server URL, Username and Password in Navidrome settings.")
                    return
                try:
                    try:
                        enable_cache = bool(config.setting["navidrome_enable_cache"])
                    except (KeyError, ValueError):
                        enable_cache = True
                    client = SubsonicClient(
                        base_url=base_url, 
                        username=username, 
                        password=password, 
                        app_name=app_name, 
                        verify_ssl=verify_ssl,
                        enable_cache=enable_cache
                    )
                except Exception as exc:
                    QMessageBox.critical(parent, "Navidrome", f"Unable to connect: {exc}")
                    return

                # Build a cleaned set using same normalization as library
                cleaned_order: List[str] = []
                seen_clean: Set[str] = set()
                for bn in selected_basenames:
                    try:
                        clean = NavidromeLibraryDialog._strip_two_digit_prefix(str(bn))
                    except Exception:
                        clean = str(bn)
                    clean = clean.strip()
                    if clean and clean not in seen_clean:
                        cleaned_order.append(clean)
                        seen_clean.add(clean)

                # Iterate songs and match by normalized dataname
                wanted: Dict[str, Tuple[str, str]] = {}
                try:
                    for s in client.iter_all_songs_stream():
                        try:
                            dn = NavidromeLibraryDialog._dataname_for_song(s)
                        except Exception:
                            dn = str(s.get("title") or s.get("name") or "")
                        dn = dn.strip()
                        if dn in seen_clean and dn not in wanted:
                            sid = str(s.get("id", ""))
                            if sid:
                                wanted[dn] = (sid, dn)
                        # Short-circuit if we matched all
                        try:
                            if len(wanted) >= len(cleaned_order):
                                break
                        except Exception:
                            pass
                except Exception as exc:
                    QMessageBox.critical(parent, "Navidrome", f"Failed to load songs for matching: {exc}")
                    return

                # Assemble in the order of user's selection
                selected_pairs: List[Tuple[str, str]] = []
                for name in cleaned_order:
                    p = wanted.get(name)
                    if p:
                        selected_pairs.append(p)

                if not selected_pairs:
                    QMessageBox.information(parent, "Navidrome", "No Navidrome songs matched the currently highlighted items.")
                    return

                # Open review dialog directly
                try:
                    dlg = NavidromeSelectionReviewDialog(parent, selected_pairs)
                    try:
                        res = dlg.exec()
                    except Exception:
                        try:
                            res = dlg.exec_()
                        except Exception:
                            dlg.show()
                            return
                    try:
                        accepted = (res == QDialog.Accepted)
                    except Exception:
                        accepted = True
                    if not accepted:
                        return
                    ordered_ids = dlg.get_ordered_ids()
                except Exception:
                    ordered_ids = [sid for sid, _ in selected_pairs]

                if not ordered_ids:
                    QMessageBox.information(parent, "Navidrome", "No tracks to create a playlist from.")
                    return

                # Ask for playlist name (remove '?' help button)
                try:
                    dlg_name = QInputDialog(parent)
                    try:
                        dlg_name.setInputMode(QInputDialog.TextInput)
                        dlg_name.setWindowTitle("Create Playlist")
                        dlg_name.setLabelText("Playlist name:")
                    except Exception:
                        pass
                    try:
                        dlg_name.setWindowFlag(Qt.WindowContextHelpButtonHint, False)  # type: ignore
                    except Exception:
                        try:
                            dlg_name.setWindowFlags(dlg_name.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore
                        except Exception:
                            pass
                    try:
                        res_name = dlg_name.exec()
                    except Exception:
                        try:
                            res_name = dlg_name.exec_()
                        except Exception:
                            dlg_name.show()
                            return
                    try:
                        ok = (res_name == QDialog.Accepted)
                    except Exception:
                        ok = True
                    name = dlg_name.textValue() if ok else ""
                except Exception:
                    ok = False
                    name = ""
                if not ok:
                    return
                name = (name or "").strip()
                if not name:
                    QMessageBox.information(parent, "Navidrome", "Playlist name cannot be empty.")
                    return

                try:
                    pl_id = client.create_playlist(name, ordered_ids)
                except Exception as exc:
                    QMessageBox.critical(parent, "Navidrome", f"Failed to create playlist: {exc}")
                    return
                if pl_id:
                    QMessageBox.information(parent, "Navidrome", f"Playlist '{name}' created.")
                else:
                    QMessageBox.information(parent, "Navidrome", f"Playlist '{name}' created.")
                return

            # Fallbacks if nothing selected in Picard: use open Library window if present, else open it
            try:
                for w in QApplication.topLevelWidgets():
                    try:
                        if isinstance(w, NavidromeLibraryDialog):
                            w._continue_to_review_selected()
                            return
                    except Exception:
                        continue
            except Exception:
                pass
            _open_library_dialog()
    if register_file_action is not None:
        register_file_action(NavidromeCreatePlaylistFromSelectionAction())  # type: ignore
    register_track_action(NavidromeCreatePlaylistFromSelectionAction())
    register_album_action(NavidromeCreatePlaylistFromSelectionAction())
except Exception as exc:
    log.error("Navidrome plugin: Failed to register create-playlist action: %r", exc)


# -----------------------------
# Clear sensitive credentials on app exit
# -----------------------------
def _clear_credentials_on_exit() -> None:
    try:
        save = False
        try:
            try:
                save = bool(config.setting["navidrome_save_credentials"])
            except (KeyError, ValueError):
                save = False
        except Exception:
            save = bool(config.setting["navidrome_save_credentials"]) if "navidrome_save_credentials" in config.setting else False
        if not save:
            config.setting["navidrome_username"] = ""
            config.setting["navidrome_password"] = ""
    except Exception:
        pass

def _flush_credentials_if_not_saved() -> None:
    try:
        save = False
        try:
            try:
                save = bool(config.setting["navidrome_save_credentials"])
            except (KeyError, ValueError):
                save = False
        except Exception:
            save = bool(config.setting["navidrome_save_credentials"]) if "navidrome_save_credentials" in config.setting else False
        if not save:
            config.setting["navidrome_username"] = ""
            config.setting["navidrome_password"] = ""
    except Exception:
        pass

try:
    if QTimer is not None:
        QTimer.singleShot(0, _flush_credentials_if_not_saved)  # type: ignore[attr-defined]
except Exception:
    pass

try:
    if QCoreApplication is not None:
        app = QCoreApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.connect(_clear_credentials_on_exit)  # type: ignore[attr-defined]
            except Exception:
                pass
except Exception:
    pass
