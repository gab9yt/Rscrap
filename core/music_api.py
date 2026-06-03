from ytmusicapi import YTMusic
from typing import List, Dict, Any, Optional
from thefuzz import process

class MusicAPI:
    def __init__(self):
        self._api = None

    def _ensure_api(self):
        if self._api is None:
            self._api = YTMusic()
        return self._api

    def search(self, query: str, filter_type: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Recherche de musique sur YouTube Music"""
        try:
            results = self._ensure_api().search(query, filter=filter_type, limit=limit)
            return results
        except Exception as e:
            print(f"Erreur recherche: {e}")
            return []

    def search_all(self, query: str, limit_per_type: int = 15) -> List[Dict[str, Any]]:
        """Recherche multi-catégories pour le mode 'Tout' (fusionne musiques, artistes, albums, playlists)."""
        results = []
        seen = set()
        for ft in ["songs", "artists", "albums", "playlists"]:
            try:
                items = self._ensure_api().search(query, filter=ft, limit=limit_per_type)
                for item in items:
                    uid = item.get("videoId") or item.get("browseId") or item.get("playlistId")
                    if uid and uid not in seen:
                        seen.add(uid)
                        results.append(item)
            except Exception as e:
                print(f"Erreur search {ft}: {e}")
        return results

    def get_artist(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Récupère les informations d'un artiste"""
        try:
            return self._ensure_api().get_artist(channel_id)
        except Exception as e:
            print(f"Erreur get_artist: {e}")
            return None

    def get_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Récupère les informations et pistes d'une playlist"""
        try:
            return self._ensure_api().get_playlist(playlist_id)
        except Exception as e:
            print(f"Erreur get_playlist: {e}")
            return None

    def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Récupère les informations et pistes d'un album"""
        try:
            return self._ensure_api().get_album(album_id)
        except Exception as e:
            print(f"Erreur get_album: {e}")
            return None

    def get_home(self) -> List[Dict[str, Any]]:
        """Récupère le contenu de la page d'accueil"""
        try:
            return self._ensure_api().get_home()
        except Exception as e:
            print(f"Erreur chargement home: {e}")
            return []

    def get_trending(self) -> List[Dict[str, Any]]:
        """Récupère les tendances"""
        try:
            charts = self._ensure_api().get_charts(country="FR")
            return charts.get("tracks", {}).get("items", [])
        except Exception as e:
            print(f"Erreur chargement tendances: {e}")
            return []

    def fuzzy_search(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recherche floue dans une liste de candidats"""
        if not candidates:
            return []
            
        titles = [c.get("title", "") for c in candidates]
        results = process.extract(query, titles, limit=10)
        
        matched = []
        for title, score in results:
            for candidate in candidates:
                if candidate.get("title") == title and score > 60:
                    matched.append(candidate)
                    break
        
        return matched

    def get_track_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Récupère les détails d'une piste"""
        try:
            details = self._ensure_api().get_song(video_id)
            return details
        except Exception as e:
            print(f"Erreur détails piste: {e}")
            return None

    def get_watch_playlist(self, video_id: str, limit: int = 25) -> Optional[Dict[str, Any]]:
        """Récupère les recommandations (watch playlist / radio) basées sur un videoId"""
        try:
            return self._ensure_api().get_watch_playlist(videoId=video_id, limit=limit)
        except Exception as e:
            print(f"Erreur get_watch_playlist: {e}")
            return None
