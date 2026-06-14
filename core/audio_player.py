import threading
import time
import math
import yt_dlp

try:
    import vlc
    VLC_AVAILABLE = True
except Exception:
    VLC_AVAILABLE = False
    print("[VLC] python-vlc non disponible. Installez VLC + python-vlc.")


class AudioPlayer:
    """
    Lecteur audio streamant directement depuis l'URL YouTube via VLC (mode audio seul,
    aucune fenêtre). La progression est lue via vlc.MediaPlayer.get_time() toutes les 500ms.

    Le compteur _play_gen (génération) garantit qu'un seul monitor est actif à la fois :
    dès qu'un nouveau play_track() est appelé, tous les anciens threads de monitoring
    s'arrêtent silencieusement sans déclencher on_track_end().
    """

    def __init__(self, volume: int = 80, cache_manager=None):
        self.volume = volume
        self.cache_manager = cache_manager
        self.app = None
        self.is_playing = False
        self.current_track = None

        # Callbacks à brancher depuis l'UI
        self.on_progress = None    # fn(elapsed_s, total_s)
        self.on_track_end = None   # fn()
        self.on_track_start = None # fn(track_dict)

        self._running = False
        self._instance = None
        self._player = None
        self._vlc_initialized = False

        # Compteur de génération : incrémenté à chaque play_track().
        # Permet d'invalider proprement les anciens threads de monitoring.
        self._play_gen = 0

    # ------------------------------------------------------------------ helpers
    def _ensure_vlc(self):
        """Initialise VLC au premier usage (lazy)."""
        if self._vlc_initialized:
            return True
        if not VLC_AVAILABLE:
            print("[ERROR] VLC non disponible.")
            return False
        try:
            self._instance = vlc.Instance("--no-video", "--quiet", "--intf=dummy")
            self._player = self._instance.media_player_new()
            self._player.audio_set_volume(self._log_volume(self.volume))
            self._vlc_initialized = True
            return True
        except Exception as e:
            print(f"[ERROR] Init VLC: {e}")
            return False

    def _log_volume(self, linear: int) -> int:
        """Courbe logarithmique : perception humaine plus naturelle."""
        if linear <= 0:
            return 0
        return int(math.log10(linear / 100 * 9 + 1) * 100)

    def _get_stream_url(self, video_id: str):
        """Extrait l'URL directe du flux audio via yt-dlp (pas de téléchargement)."""
        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}",
                    download=False
                )
                return info.get("url"), info.get("duration", 0)
        except Exception as e:
            print(f"[ERROR] Erreur extraction flux: {e}")
            return None, 0

    # ------------------------------------------------------------------ lecture
    def play_track(self, track: dict):
        """Lance la lecture d'une piste (thread non-bloquant)."""
        if not self._ensure_vlc():
            return

        self.current_track = track

        # Incrémenter la génération AVANT stop() pour invalider l'ancien monitor
        self._play_gen += 1
        gen = self._play_gen

        self._stop_internal()   # Arrête VLC sans risque de déclencher on_track_end

        threading.Thread(
            target=self._load_and_play,
            args=(track, gen),
            daemon=True
        ).start()

    def _stop_internal(self):
        """Arrête VLC proprement SANS déclencher on_track_end (usage interne)."""
        self._running = False
        if self._player:
            try:
                self._player.stop()
            except Exception:
                pass
        self.is_playing = False

    def _load_and_play(self, track: dict, gen: int):
        """Charge et joue une piste. S'arrête silencieusement si gen est périmé."""
        video_id = track.get("videoId")
        if not video_id:
            print("[ERROR] Pas de videoId dans la piste.")
            return

        # Déjà remplacé par un appel plus récent ?
        if gen != self._play_gen:
            return

        # 1. Vérifier le cache disque local
        if self.cache_manager and self.cache_manager.is_cached(video_id):
            local_path = self.cache_manager.get_cache_path(video_id)
            print(f"[PLAY] Lecture depuis le cache disque local : {local_path}")
            media = self._instance.media_new(local_path)
            duration = track.get("duration", 0) or 0
        else:
            # 2. Vérifier le cache de prefetch de l'application
            url = None
            duration = 0
            if self.app and hasattr(self.app, "stream_url_cache"):
                if video_id in self.app.stream_url_cache:
                    url, duration = self.app.stream_url_cache[video_id]
                    print(f"[PLAY] Utilisation de l'URL pré-extraite de la mémoire")

            if not url:
                print("[SEARCH] Extraction du flux audio YouTube...")
                url, duration = self._get_stream_url(video_id)

            if not url:
                print("[ERROR] Impossible d'extraire le flux.")
                return

            media = self._instance.media_new(url)

            # 3. Lancer la mise en cache en arrière-plan pour les écoutes futures
            if self.cache_manager:
                def _cache_worker():
                    self.cache_manager.download_to_cache(video_id, url)
                threading.Thread(target=_cache_worker, daemon=True).start()

        # Vérifier encore une fois avant de charger le média
        if gen != self._play_gen:
            return

        self._player.set_media(media)
        self._player.play()
        self.is_playing = True

        print(f"[PLAY] Lecture : {track.get('title', '?')}")

        if self.on_track_start and gen == self._play_gen:
            self.on_track_start(track)

        # Attendre que VLC initialise vraiment le média
        time.sleep(1.2)

        # Si entre-temps une nouvelle piste a été demandée, abandonner
        if gen != self._play_gen:
            return

        self._running = True
        self._monitor(gen)

    def _monitor(self, gen: int):
        """
        Boucle de progression — vérifie l'état VLC toutes les 500ms.
        S'arrête silencieusement si la génération est périmée (nouvelle piste lancée).
        Ne déclenche on_track_end() QUE si on est encore la génération courante.
        """
        while self._running and gen == self._play_gen:
            if not self._player:
                break

            state = self._player.get_state()

            if state in (vlc.State.Ended, vlc.State.Error, vlc.State.Stopped):
                self.is_playing = False
                self._running = False
                print("[STOP] Fin de piste.")
                # Déclencher on_track_end seulement si on est encore la bonne génération
                if gen == self._play_gen and self.on_track_end:
                    self.on_track_end()
                break

            length_ms = self._player.get_length()   # durée totale en ms
            pos_ms    = self._player.get_time()     # position actuelle en ms

            if length_ms > 0 and self.on_progress and gen == self._play_gen:
                self.on_progress(pos_ms / 1000, length_ms / 1000)

            time.sleep(0.5)

    # ------------------------------------------------------------------ contrôles
    def toggle_play(self):
        """Pause / Reprise."""
        if not self._player:
            return
        if self._player.is_playing():
            self._player.pause()
            self.is_playing = False
        else:
            self._player.play()
            self.is_playing = True

    def stop(self):
        """Arrête la lecture proprement (depuis l'UI)."""
        # Invalider la génération courante pour stopper le monitor
        self._play_gen += 1
        self._stop_internal()

    def seek(self, seconds: float):
        """Déplace la tête de lecture à `seconds` secondes."""
        if not self._player:
            return
        length_ms = self._player.get_length()
        if length_ms > 0:
            ratio = max(0.0, min(1.0, (seconds * 1000) / length_ms))
            self._player.set_position(ratio)

    def set_volume(self, volume: int):
        """Volume linéaire 0-100 converti en log pour VLC."""
        self.volume = max(0, min(100, int(volume)))
        if self._player:
            self._player.audio_set_volume(self._log_volume(self.volume))

    def cleanup(self):
        self.stop()
