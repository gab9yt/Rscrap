import os
import time
import threading
from typing import Dict, Optional
from collections import OrderedDict
import yt_dlp
import urllib.request

class CacheManager:
    def __init__(self, cache_dir: str = "cache", limit_gb: float = 5.0):
        self.cache_dir = cache_dir
        self.limit_bytes = int(limit_gb * 1024**3)
        self.lru = OrderedDict()
        self.lock = threading.Lock()
        
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
            
        self._load_existing_cache()

    def _load_existing_cache(self):
        """Charge les fichiers existants du cache dans l'LRU"""
        files = []
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            if os.path.isfile(filepath):
                mtime = os.path.getmtime(filepath)
                files.append((-mtime, filepath))
        
        files.sort()
        for _, filepath in files:
            self.lru[filepath] = os.path.getsize(filepath)

    def _get_cache_size(self) -> int:
        """Retourne la taille totale du cache en octets"""
        total = 0
        for size in self.lru.values():
            total += size
        return total

    def _cleanup_cache(self):
        """Nettoie les fichiers les plus anciens du cache si la limite est dépassée"""
        while self._get_cache_size() > self.limit_bytes and self.lru:
            oldest_file, oldest_size = self.lru.popitem(last=False)
            try:
                if os.path.exists(oldest_file):
                    os.remove(oldest_file)
                print(f"Nettoyage cache: supprimé {os.path.basename(oldest_file)}")
            except Exception as e:
                print(f"Erreur suppression cache: {e}")

    def get_cache_path(self, video_id: str) -> str:
        """Retourne le chemin du fichier cache pour un video_id"""
        return os.path.join(self.cache_dir, f"{video_id}.mp3")

    def is_cached(self, video_id: str) -> bool:
        """Vérifie si une piste est dans le cache"""
        cache_path = self.get_cache_path(video_id)
        exists = os.path.exists(cache_path)
        if exists and cache_path in self.lru:
            with self.lock:
                self.lru.move_to_end(cache_path)
        return exists

    def download_to_cache(self, video_id: str, audio_url: str) -> Optional[str]:
        """Télécharge un flux audio dans le cache"""
        cache_path = self.get_cache_path(video_id)
        
        if self.is_cached(video_id):
            return cache_path

        try:
            print(f"Téléchargement cache: {video_id}")
            urllib.request.urlretrieve(audio_url, cache_path)
            
            file_size = os.path.getsize(cache_path)
            with self.lock:
                self.lru[cache_path] = file_size
                self._cleanup_cache()
                
            return cache_path
        except Exception as e:
            print(f"Erreur téléchargement cache: {e}")
            if os.path.exists(cache_path):
                os.remove(cache_path)
            return None

    def access_track(self, video_id: str):
        """Marque une piste comme accédée récemment"""
        cache_path = self.get_cache_path(video_id)
        if os.path.exists(cache_path):
            with self.lock:
                if cache_path in self.lru:
                    self.lru.move_to_end(cache_path)
                else:
                    self.lru[cache_path] = os.path.getsize(cache_path)
                os.utime(cache_path)

    def get_thumbnail_cache_path(self, url: str) -> str:
        """Retourne le chemin d'une miniature cachée par son URL"""
        import hashlib
        h = hashlib.md5(url.encode('utf-8')).hexdigest()
        thumb_dir = os.path.join(self.cache_dir, "thumbnails")
        if not os.path.exists(thumb_dir):
            try:
                os.makedirs(thumb_dir, exist_ok=True)
            except Exception:
                pass
        return os.path.join(thumb_dir, f"{h}.png")

    def clear_thumbnails(self):
        """Supprime toutes les miniatures du cache (appelé à la fermeture de l'app)."""
        thumb_dir = os.path.join(self.cache_dir, "thumbnails")
        if not os.path.exists(thumb_dir):
            return
        deleted = 0
        for filename in os.listdir(thumb_dir):
            filepath = os.path.join(thumb_dir, filename)
            try:
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    deleted += 1
            except Exception as e:
                print(f"[Cache] Erreur suppression miniature {filename}: {e}")
        print(f"[Cache] {deleted} miniature(s) supprimée(s) à la fermeture.")
