import sqlite3
import os
from typing import Optional, Dict, List, Any

class Database:
    def __init__(self, db_path: str = "spotifree.db"):
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._create_tables()

    def _connect(self):
        """Établit la connexion SQLite avec WAL activé"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.conn.commit()

    def _create_tables(self):
        """Crée les tables nécessaires"""
        cursor = self.conn.cursor()
        
        # Table tracks
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT,
                album TEXT,
                thumbnail_url TEXT,
                cache_path TEXT,
                duration INTEGER,
                video_id TEXT UNIQUE,
                last_played TIMESTAMP,
                play_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table playlists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                thumbnail_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table playlist_tracks (liaison)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlist_tracks (
                playlist_id TEXT,
                track_id TEXT,
                position INTEGER,
                PRIMARY KEY (playlist_id, track_id),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            )
        ''')
        
        # Table liked_tracks
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS liked_tracks (
                track_id TEXT PRIMARY KEY,
                liked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            )
        ''')
        
        # Table history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id TEXT,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            )
        ''')
        
        # Table recent_searches
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recent_searches (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                subtitle TEXT,
                thumbnail_url TEXT,
                type TEXT NOT NULL, -- 'song', 'artist', 'playlist', 'album'
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()

    def add_track(self, track_data: Dict[str, Any]) -> None:
        """Ajoute ou met à jour une piste dans la base de données"""
        cursor = self.conn.cursor()
        # Determine artist name safely
        artist = ""
        if isinstance(track_data.get("artist"), str):
            artist = track_data.get("artist")
        elif isinstance(track_data.get("artists"), list) and track_data.get("artists"):
            first = track_data.get("artists")[0]
            if isinstance(first, dict):
                artist = first.get("name", "")
        # Determine album name safely
        album = ""
        if isinstance(track_data.get("album"), str):
            album = track_data.get("album")
        elif isinstance(track_data.get("album"), dict):
            album = track_data.get("album").get("name", "")
        # Determine thumbnail URL safely
        thumbnail_url = ""
        thumbs = track_data.get("thumbnails")
        if isinstance(thumbs, list) and thumbs:
            thumbnail_url = thumbs[-1].get("url", "")
        elif isinstance(thumbs, dict):
            thumbnail_url = thumbs.get("url", "")
        # Determine video ID safely
        video_id = ""
        if isinstance(track_data.get("videoId"), str):
            video_id = track_data.get("videoId")
        elif isinstance(track_data.get("videoId"), dict):
            video_id = track_data.get("videoId").get("id", "")
        cursor.execute('''
            INSERT INTO tracks
            (id, title, artist, album, thumbnail_url, cache_path, duration, video_id, last_played)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                artist = excluded.artist,
                album = excluded.album,
                thumbnail_url = excluded.thumbnail_url,
                cache_path = excluded.cache_path,
                duration = excluded.duration,
                video_id = excluded.video_id,
                last_played = CURRENT_TIMESTAMP
        ''', (
            track_data.get("id", video_id),
            track_data.get("title"),
            artist,
            album,
            thumbnail_url,
            track_data.get("cache_path"),
            track_data.get("duration"),
            video_id
        ))
        self.conn.commit()

    def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Récupère une piste par son ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM tracks WHERE id = ?', (track_id,))
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

    def get_tracks(self) -> List[Dict[str, Any]]:
        """Récupère toutes les pistes"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM tracks ORDER BY last_played DESC')
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def like_track(self, track_id: str) -> None:
        """Ajoute une piste aux favoris"""
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO liked_tracks (track_id) VALUES (?)', (track_id,))
        self.conn.commit()

    def unlike_track(self, track_id: str) -> None:
        """Retire une piste des favoris"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM liked_tracks WHERE track_id = ?', (track_id,))
        self.conn.commit()

    def is_liked(self, track_id: str) -> bool:
        """Vérifie si une piste est aimée"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM liked_tracks WHERE track_id = ?', (track_id,))
        return cursor.fetchone() is not None

    def add_to_history(self, track_id: str) -> None:
        """Ajoute une piste à l'historique"""
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO history (track_id) VALUES (?)', (track_id,))
        self.conn.commit()

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Récupère l'historique de lecture"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT t.* FROM tracks t
            INNER JOIN history h ON t.id = h.track_id
            ORDER BY h.played_at DESC LIMIT ?
        ''', (limit,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # ── Liked tracks ────────────────────────────────────────────
    def toggle_like(self, track_id: str) -> bool:
        """Bascule like. Retourne True si maintenant liké."""
        if self.is_liked(track_id):
            self.unlike_track(track_id)
            return False
        self.like_track(track_id)
        return True

    def get_liked_tracks(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT t.* FROM tracks t
            JOIN liked_tracks lt ON t.id = lt.track_id
            ORDER BY lt.liked_at DESC
        ''')
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_all_liked_ids(self) -> set:
        cursor = self.conn.cursor()
        cursor.execute('SELECT track_id FROM liked_tracks')
        return {row[0] for row in cursor.fetchall()}

    # ── Playlists utilisateur ─────────────────────────────────
    def create_playlist(self, name: str, description: str = "") -> str:
        import uuid
        pid = str(uuid.uuid4())
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO playlists (id, name, description) VALUES (?, ?, ?)',
            (pid, name, description)
        )
        self.conn.commit()
        return pid

    def get_playlists(self) -> List[Dict[str, Any]]:
        """Retourne les playlists avec la pochette du 1er titre et le nb de pistes."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT p.id, p.name, p.description, p.created_at,
                   (SELECT t.thumbnail_url
                    FROM playlist_tracks pt
                    JOIN tracks t ON pt.track_id = t.id
                    WHERE pt.playlist_id = p.id
                    ORDER BY pt.position ASC LIMIT 1) AS cover_url,
                   (SELECT COUNT(*) FROM playlist_tracks
                    WHERE playlist_id = p.id) AS track_count
            FROM playlists p ORDER BY p.created_at DESC
        ''')
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def add_to_playlist(self, playlist_id: str, track_id: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks WHERE playlist_id = ?',
            (playlist_id,)
        )
        pos = cursor.fetchone()[0]
        cursor.execute(
            'INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)',
            (playlist_id, track_id, pos)
        )
        self.conn.commit()

    def get_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT t.* FROM tracks t
            JOIN playlist_tracks pt ON t.id = pt.track_id
            WHERE pt.playlist_id = ?
            ORDER BY pt.position ASC
        ''', (playlist_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def delete_playlist(self, playlist_id: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))
        self.conn.commit()

    def duplicate_playlist(self, playlist_id: str) -> str:
        """Duplique une playlist avec ses morceaux sous un nouveau nom."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT name, description FROM playlists WHERE id = ?', (playlist_id,))
        row = cursor.fetchone()
        if not row:
            return ""
        name, description = row
        new_name = f"{name} (Copie)"
        
        import uuid
        new_pid = str(uuid.uuid4())
        cursor.execute(
            'INSERT INTO playlists (id, name, description) VALUES (?, ?, ?)',
            (new_pid, new_name, description)
        )
        
        cursor.execute('''
            SELECT track_id, position FROM playlist_tracks 
            WHERE playlist_id = ? 
            ORDER BY position ASC
        ''', (playlist_id,))
        tracks = cursor.fetchall()
        for track_id, pos in tracks:
            cursor.execute(
                'INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)',
                (new_pid, track_id, pos)
            )
        self.conn.commit()
        return new_pid


    def remove_from_playlist(self, playlist_id: str, track_id: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            'DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?',
            (playlist_id, track_id)
        )
        self.conn.commit()

    def close(self):
        """Ferme la connexion à la base de données"""
        if self.conn:
            self.conn.close()

    # ── Recherches récentes ───────────────────────────────────
    def add_recent_search(self, item_id: str, title: str, subtitle: str, thumbnail_url: str, type_str: str) -> None:
        """Ajoute ou met à jour une recherche récente"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO recent_searches (id, title, subtitle, thumbnail_url, type, timestamp)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (item_id, title, subtitle, thumbnail_url, type_str))
        self.conn.commit()

    def get_recent_searches(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Récupère l'historique des recherches récentes"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM recent_searches ORDER BY timestamp DESC LIMIT ?', (limit,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def delete_recent_search(self, item_id: str) -> None:
        """Supprime une recherche récente de l'historique"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM recent_searches WHERE id = ?', (item_id,))
        self.conn.commit()

    def clear_recent_searches(self) -> None:
        """Vide l'historique des recherches récentes"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM recent_searches')
        self.conn.commit()

