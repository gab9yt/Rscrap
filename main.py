import sys
import os
import tkinter as tk

# Configuration des logs pour déboguer l'exécutable (écrit dans rscrap_debug.log)
_base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_log_file = open(os.path.join(_base_dir, "rscrap_debug.log"), 'w', encoding='utf-8', buffering=1)
sys.stdout = _log_file
sys.stderr = _log_file

import certifi
# Assure que SSL / les requêtes HTTPS utilisent les certificats corrects dans l'exécutable
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

import customtkinter as ctk
from PIL import Image, ImageTk
import threading
import requests
import io
import time as _time
import traceback
import cv2
from itertools import islice
from collections import OrderedDict
from core import Database, MusicAPI, AudioPlayer, VirtualTrackList, CacheManager
import queue

class VideoLoaderThread(threading.Thread):
    def __init__(self, cap, q, app_inst):
        super().__init__(daemon=True)
        self.cap = cap
        self.queue = q
        self.app = app_inst
        self.running = True

    def run(self):
        while self.running:
            try:
                w, h = getattr(self.app, 'bg_target_size', (100, 100))
                if w < 50 or h < 50:
                    _time.sleep(0.1)
                    continue

                ret, frame = self.cap.read()
                if not ret:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self.cap.read()

                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frame_resized = cv2.resize(frame_rgb, (w, h), interpolation=cv2.INTER_LINEAR)
                    img = Image.fromarray(frame_resized)
                    
                    try:
                        self.queue.put_nowait(img)
                    except queue.Full:
                        try:
                            self.queue.get_nowait()
                            self.queue.put_nowait(img)
                        except Exception:
                            pass
                
                # ~25-30 fps
                _time.sleep(0.033)
            except Exception as e:
                # Éviter de spammer la console si l'app ferme
                if not self.running:
                    break
                _time.sleep(0.1)


# Chemin absolu de l'icône "Titres likés"
_LIKES_IMG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Likes.jpg")

def _load_likes_ctk_image(size: int) -> "ctk.CTkImage | None":
    """Charge Likes.jpg en CTkImage à la taille demandée."""
    try:
        img = Image.open(_LIKES_IMG_PATH).resize((size, size), Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:
        return None

_ICON_IMG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")

def _load_icon_ctk_image(size: int) -> "ctk.CTkImage | None":
    """Charge icon.png en CTkImage à la taille demandée."""
    try:
        img = Image.open(_ICON_IMG_PATH).resize((size, size), Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:
        return None

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class ResponsiveCardGrid(ctk.CTkFrame):
    """
    Grille de cartes responsive. S'adapte à la largeur disponible de son conteneur
    en recalculant dynamiquement le nombre de colonnes.
    """
    def __init__(self, parent, items, app, card_width=180, pad=20):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.items = items
        self.card_width = card_width
        self.pad = pad
        self.cards = []
        self.card_images = []

        # Construction immédiate des cartes fournies
        for item in self.items:
            card = self._build_card(item)
            self.cards.append((card, item))

        self.bind("<Configure>", self.on_configure)

    def add_items(self, new_items):
        """Ajoute des cartes supplémentaires et re-calcule la grille."""
        for item in new_items:
            card = self._build_card(item)
            self.items.append(item)
            self.cards.append((card, item))
        # Simuler un événement Configure pour re-layout
        self.on_configure(type("ev", (), {"width": self.winfo_width()})())

    def set_items(self, items):
        """Remplace toutes les cartes (pour rafraîchissement complet)."""
        for card, _ in self.cards:
            try:
                card.destroy()
            except Exception:
                pass
        self.items = list(items)
        self.cards = []
        for item in self.items:
            card = self._build_card(item)
            self.cards.append((card, item))
        self.on_configure(type("ev", (), {"width": self.winfo_width()})())

    def _build_card(self, item):
        card = ctk.CTkFrame(self, fg_color="#181818", corner_radius=10)
        
        # Clic sur la carte
        card.bind("<Button-1>", lambda e, i=item: self.app._on_card_click(i, self.items))

        # Zone miniature
        thumb_frame = ctk.CTkFrame(card, width=160, height=160, corner_radius=8, fg_color="#272727")
        thumb_frame.pack(pady=12, padx=12)
        img_label = ctk.CTkLabel(thumb_frame, text="", width=160, height=160)
        img_label.pack()
        img_label.bind("<Button-1>", lambda e, i=item: self.app._on_card_click(i, self.items))

        # Titre et Artiste/Description
        title = item.get("title") or item.get("artist") or "Nom inconnu"
        
        r_type = item.get("resultType", "")
        if r_type == "artist":
            subtitle = "Artiste"
        elif r_type == "playlist":
            subtitle = "Playlist"
        elif r_type == "album":
            subtitle = "Album"
        elif r_type in ("song", "video"):
            artists_list = item.get("artists", [])
            if artists_list:
                subtitle = artists_list[0].get("name", "")
            else:
                subtitle = item.get("artist") or "Morceau"
        else:
            subtitle = item.get("subtitle") or ""
        
        title_label = ctk.CTkLabel(card, text=title[:25] + ("..." if len(title) > 25 else ""), font=("Arial", 13, "bold"))
        title_label.pack(pady=(0, 5), padx=12)
        title_label.bind("<Button-1>", lambda e, i=item: self.app._on_card_click(i, self.items))
        
        sub_label = ctk.CTkLabel(card, text=subtitle[:25] + ("..." if len(subtitle) > 25 else ""), text_color="gray")
        sub_label.pack(pady=(0, 15), padx=12)
        sub_label.bind("<Button-1>", lambda e, i=item: self.app._on_card_click(i, self.items))

        # Cas spéciaux pour les icônes locales
        if item.get("id") == "liked_songs":
            likes_img = _load_likes_ctk_image(160)
            if likes_img:
                img_label.configure(image=likes_img, text="", fg_color="transparent")
                self.card_images.append(likes_img)
                self.app._perm_images.append(likes_img)
            else:
                img_label.configure(text="❤️", font=("Arial", 64), fg_color="#15803d")
        elif item.get("is_custom_playlist", False):
            cover_url = item.get("cover_url")
            if cover_url:
                threading.Thread(
                    target=self._load_card_thumb,
                    args=(cover_url, img_label),
                    daemon=True
                ).start()
            else:
                icon_img = _load_icon_ctk_image(160)
                if icon_img:
                    img_label.configure(image=icon_img, text="", fg_color="transparent")
                    self.card_images.append(icon_img)
                    self.app._perm_images.append(icon_img)
                else:
                    img_label.configure(text="🎵", font=("Arial", 64), fg_color="#272727")
        else:
            # Piste/Playlist API standard
            thumbs = item.get("thumbnails", [])
            if thumbs:
                best_url = self.app._get_best_thumbnail_url(thumbs, 160)
                threading.Thread(
                    target=self._load_card_thumb,
                    args=(best_url, img_label),
                    daemon=True
                ).start()
            else:
                icon_img = _load_icon_ctk_image(160)
                if icon_img:
                    img_label.configure(image=icon_img, text="", fg_color="transparent")
                    self.card_images.append(icon_img)
                    self.app._perm_images.append(icon_img)
                else:
                    img_label.configure(text="🎵", font=("Arial", 64), fg_color="#272727")

        # Bouton lecture si c'est un morceau
        if item.get("videoId"):
            play_btn = ctk.CTkButton(
                card, text="▶", width=40, height=40, corner_radius=20,
                fg_color="#1db954", hover_color="#1ed760", text_color="black",
                font=("Arial", 14, "bold"),
                command=lambda t=item: self.app._play_track(t, self.items)
            )
            play_btn.pack(pady=(0, 12))

        # Clic droit pour les playlists personnalisées
        if item.get("is_custom_playlist", False):
            for w in (card, img_label, title_label, sub_label):
                w.bind("<Button-3>", lambda e, i=item: self.app._show_playlist_context_menu(e, i))

        return card

    def _load_card_thumb(self, url, label):
        if not url:
            return
        try:
            cache_path = self.app.cache_manager.get_thumbnail_cache_path(url)
            if os.path.exists(cache_path):
                img = Image.open(cache_path).resize((160, 160), Image.Resampling.LANCZOS)
            else:
                r = requests.get(url, timeout=10)
                img = Image.open(io.BytesIO(r.content)).resize((160, 160), Image.Resampling.LANCZOS)
                try:
                    img.save(cache_path, "PNG")
                except Exception:
                    pass

            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 160))
            self.card_images.append(ctk_img)
            self.app._perm_images.append(ctk_img)
            
            def _update():
                try:
                    if label.winfo_exists():
                        label.configure(image=ctk_img, text="")
                except Exception:
                    pass
            self.after(0, _update)
        except Exception:
            pass

    def on_configure(self, event):
        now = _time.time()
        if hasattr(self, '_last_layout') and now - self._last_layout < 0.08:
            return
        self._last_layout = now

        width = event.width
        if width < 100:
            return
        
        col_width = self.card_width + self.pad
        cols = max(1, width // col_width)
        
        for i, (card, _) in enumerate(self.cards):
            r = i // cols
            c = i % cols
            card.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            
        for c in range(cols):
            self.grid_columnconfigure(c, weight=1, uniform="card_col")
        for c in range(cols, len(self.cards) + 2):
            self.grid_columnconfigure(c, weight=0, uniform="")


class RscrapApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Définir l'icône de l'application dans la barre des tâches et la fenêtre
        if sys.platform == "win32":
            import ctypes
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Rscrap.App")
            except Exception:
                pass
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
                photo = ImageTk.PhotoImage(img)
                self.iconphoto(True, photo)
                self._app_icon = photo
        except Exception as e:
            print(f"[ICON] Erreur configuration icône: {e}")

        self.title("Rscrap")
        self.geometry("1400x900")
        self.minsize(900, 600)

        self.current_playing_track_id = None

        self.configure(fg_color="#0a0a0a")

        self.db = Database()
        self.api = MusicAPI()
        self.cache_manager = CacheManager()
        self.audio_player = AudioPlayer(cache_manager=self.cache_manager)
        self.audio_player.app = self
        self.stream_url_cache = {}
        
        # Playback queue states
        self.playback_queue = []
        self.original_queue = []
        self.queue_index = -1
        self.repeat_mode = "none"   # "none", "all", "one"
        self.shuffle_mode = "none"  # "none", "shuffle", "intelligent"
        self.recent_played_ids = []

        self.card_images = []
        self._perm_images = []  # jamais vidé → évite "Cannot read image.png"
        self._cached_liked_ids = self.db.get_all_liked_ids()
        self.view_stack = []
        self.current_view = "home"
        self.current_data = None
        self.current_search_filter = "Tout"
        self._current_search_query = ""
        self._current_search_results = []

        # Variables overlay recherche
        self.search_dropdown = None
        self._dropdown_visible = False

        # Dict track_id → [boutons like] pour synchronisation en temps réel
        self._row_like_buttons = {}

        # État player bar
        self._bar_thumb_img = None
        self._slider_dragging = False
        self._current_duration = 0.0

        # Brancher les callbacks audio → UI
        self.audio_player.on_progress   = self._on_progress
        self.audio_player.on_track_end  = self._on_track_end
        self.audio_player.on_track_start = self._on_track_start



        # Clic global pour fermer le dropdown de recherche lors d'un clic en dehors
        self.bind_all("<Button-1>", self._on_global_click)

        # Registre des after() pour pouvoir les annuler proprement
        self._after_ids = {}

        self._setup_bg_video()
        self._setup_ui()
        # Masquer la fenêtre pendant le pré-chargement
        self.withdraw()
        # Lancer le pré-chargement en arrière-plan
        threading.Thread(target=self._preload_and_show, daemon=True).start()
        # Configurer bg_window comme splash centré juste après son initialisation
        self._app_revealed = False
        self._splash_after_id = self.after(150, self._init_splash)

    # ─────────────────────────────────────────────── Vidéo de fond
    def _setup_bg_video(self):
        # 1. Rendre le fond principal transparent via l'OS
        if sys.platform == "win32":
            self.wm_attributes("-transparentcolor", "#080808")
            self.configure(fg_color="#080808")

        # 2. Fenêtre séparée en arrière-plan pour la vidéo (utilisation de tk.Toplevel pour un overrideredirect fiable sans bordures)
        self.bg_window = tk.Toplevel(self)
        self.bg_window.overrideredirect(True)
        self.bg_window.configure(bg="#080808")
        # self.bg_window.attributes("-disabled", True)  # We need it enabled to catch fall-through events
        self.bg_window.lower(self)

        def forward_event(event, event_type):
            target = self.winfo_containing(event.x_root, event.y_root)
            
            # Prevent infinite recursion by not forwarding to bg_window
            if target and target.winfo_toplevel() == self.bg_window:
                # Find the widget within main_window
                def find_widget(w, rx, ry):
                    if not w.winfo_ismapped(): return None
                    x, y = w.winfo_rootx(), w.winfo_rooty()
                    w_width, w_height = w.winfo_width(), w.winfo_height()
                    if x <= rx < x + w_width and y <= ry < y + w_height:
                        for child in reversed(w.winfo_children()):
                            if child.winfo_toplevel() == self.bg_window: continue
                            found = find_widget(child, rx, ry)
                            if found: return found
                        return w
                    return None
                target = find_widget(self, event.x_root, event.y_root)

            if target and target.winfo_toplevel() != self.bg_window:
                kwargs = {
                    "x": event.x_root - target.winfo_rootx(), 
                    "y": event.y_root - target.winfo_rooty(), 
                    "rootx": event.x_root, "rooty": event.y_root
                }
                if event_type == "<MouseWheel>":
                    kwargs["delta"] = getattr(event, 'delta', 0)
                elif event_type in ("<Button-4>", "<Button-5>"):
                    kwargs["num"] = int(event_type[-2])
                try:
                    target.event_generate(event_type, **kwargs)
                except Exception:
                    pass

        self.bg_window.bind("<MouseWheel>", lambda e: forward_event(e, "<MouseWheel>"))
        self.bg_window.bind("<Button-4>", lambda e: forward_event(e, "<Button-4>"))
        self.bg_window.bind("<Button-5>", lambda e: forward_event(e, "<Button-5>"))
        self.bg_window.bind("<Button-1>", lambda e: (self.lift(), forward_event(e, "<Button-1>")))

        self.bg_label = ctk.CTkLabel(self.bg_window, text="")
        self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.bg_video_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "font.mp4")
        self.cap = cv2.VideoCapture(self.bg_video_path)

        self.bg_target_size = (100, 100)
        self.video_queue = queue.Queue(maxsize=2)

        def sync_bg(event=None):
            if not self.bg_window.winfo_exists(): return
            w = self.winfo_width()
            h = self.winfo_height()
            rx = self.winfo_rootx()
            ry = self.winfo_rooty()
            if w > 10 and h > 10:
                self.bg_window.geometry(f"{w}x{h}+{rx}+{ry}")
                self.bg_target_size = (w, h)
                self.bg_window.lower(self)  # En arrière-plan seulement quand la fenêtre principale est visible

        def on_main_minimize(event=None):
            """Cache bg_window quand la fenêtre principale est minimisée."""
            try:
                state = self.wm_state()
                if state == "iconic":
                    if self.bg_window.winfo_exists():
                        self.bg_window.withdraw()
                else:
                    if self.bg_window.winfo_exists():
                        self.bg_window.deiconify()
                        self.bg_window.lower(self)
                        sync_bg()
            except Exception:
                pass

        self.bind("<Configure>", sync_bg)
        self.bind("<Unmap>", on_main_minimize)
        self.bind("<Map>", on_main_minimize)
        self.after(100, sync_bg)

        # Démarrer le thread démon de traitement vidéo
        self.video_loader = VideoLoaderThread(self.cap, self.video_queue, self)
        self.video_loader.start()
        
        self._update_bg_frame()

    def _update_bg_frame(self):
        if not hasattr(self, 'video_queue'): return
        try:
            # Récupérer l'image pré-calculée en arrière-plan
            img = self.video_queue.get_nowait()
            w, h = img.size
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
            self.bg_label.configure(image=ctk_img)
            self._perm_images.append(ctk_img)
            # Éviter que self._perm_images ne grandisse indéfiniment
            if len(self._perm_images) > 300:
                self._perm_images = self._perm_images[-100:]
        except queue.Empty:
            pass
        
        # ~25 fps pour le rendu UI (toutes les 40ms)
        self.after(40, self._update_bg_frame)

    # ═══════════════════════════════════════════════════════════════ SETUP UI
    def _setup_ui(self):
        # 2 lignes : contenu (row 0) + player bar (row 1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)

        self._build_sidebar()
        self._build_topbar()
        self._build_main_content()
        self._build_player_bar()

    # ─────────────────────────────────────────────── Sidebar
    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=240, corner_radius=0, fg_color="transparent")
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_propagate(False)

        logo_lbl = ctk.CTkLabel(self.sidebar, text="Rscrap", font=("Arial", 22, "bold"), anchor="w")
        logo_lbl.pack(padx=20, pady=(20, 20), fill="x")

        # Bouton Accueil
        self.home_btn = ctk.CTkButton(
            self.sidebar, text="🏠   Accueil", width=220, height=45,
            fg_color="transparent", hover_color="#282828",
            corner_radius=8, font=("Arial", 14, "bold"), anchor="w",
            command=self.show_home
        )
        self.home_btn.pack(pady=5, padx=10)

        # Panneau Bibliothèque
        lib_panel = ctk.CTkFrame(self.sidebar, fg_color="transparent", corner_radius=10)
        lib_panel.pack(fill="both", expand=True, padx=10, pady=(10, 15))

        # En-tête de Bibliothèque
        lib_header = ctk.CTkFrame(lib_panel, fg_color="transparent")
        lib_header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(lib_header, text="📚   Bibliothèque", font=("Arial", 14, "bold"), text_color="gray", anchor="w").pack(side="left")
        
        # Bouton Plus
        create_btn = ctk.CTkButton(
            lib_header, text="＋", width=24, height=24, corner_radius=12,
            fg_color="transparent", hover_color="#282828", text_color="gray",
            font=("Arial", 16, "bold"), command=lambda: self._prompt_create_playlist(None)
        )
        create_btn.pack(side="right")

        # Conteneur défilant des playlists
        self.sidebar_scroll = ctk.CTkScrollableFrame(lib_panel, fg_color="transparent", corner_radius=0)
        self.sidebar_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        self._refresh_sidebar_playlists()

    def _refresh_sidebar_playlists(self):
        """Met à jour la sidebar sans tout détruire (cache dans _sidebar_rows)."""
        if not hasattr(self, '_sidebar_rows'):
            self._sidebar_rows = {}
        seen = set()

        # 1. Favoris (toujours mis à jour car le compteur change)
        liked_tracks = self.db.get_liked_tracks()
        sub = f"Playlist • {len(liked_tracks)} titres"
        row = self._sidebar_rows.get("liked_songs")
        if row is not None:
            for w in row.winfo_children():
                if isinstance(w, ctk.CTkLabel) and w.cget("text").startswith("Playlist"):
                    w.configure(text=sub); break
        else:
            liked_item = {
                "id": "liked_songs",
                "title": "Titres likés",
                "subtitle": sub,
                "is_local": True
            }
            self._add_sidebar_playlist_item(liked_item)
        seen.add("liked_songs")

        # 2. Playlists utilisateur
        custom_playlists = self.db.get_playlists()
        for pl in custom_playlists:
            pid = pl["id"]
            seen.add(pid)
            sub = f"Playlist • {pl.get('track_count', 0)} titres"
            row = self._sidebar_rows.get(pid)
            if row is not None:
                # Màj sous-titre (chercher récursivement dans les enfants)
                self._set_subtitle(row, sub)
                # Màj vignette si cover_url dispo
                cover_url = pl.get("cover_url")
                if cover_url:
                    children = row.winfo_children()
                    if children:
                        img_lbl = children[0]
                        threading.Thread(
                            target=self._load_sidebar_thumb,
                            args=(cover_url, img_lbl),
                            daemon=True
                        ).start()
            else:
                pl_item = {
                    "id": pid,
                    "title": pl["name"],
                    "subtitle": sub,
                    "is_local": True,
                    "is_custom_playlist": True,
                    "cover_url": pl.get("cover_url")
                }
                self._add_sidebar_playlist_item(pl_item)

        # 3. Nettoyer les lignes supprimées
        for pid in list(self._sidebar_rows.keys()):
            if pid not in seen:
                try:
                    self._sidebar_rows[pid].destroy()
                except Exception:
                    pass
                del self._sidebar_rows[pid]

    @staticmethod
    def _set_subtitle(widget, text):
        """Cherche récursivement un CTkLabel dont le texte commence par 'Playlist' et met à jour."""
        for c in widget.winfo_children():
            if isinstance(c, ctk.CTkLabel) and c.cget("text").startswith("Playlist"):
                c.configure(text=text)
                return True
            if RscrapApp._set_subtitle(c, text):
                return True
        return False

    def _add_sidebar_playlist_item(self, item):
        row_frame = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent", height=50, corner_radius=5)
        row_frame.pack(fill="x", pady=2, padx=5)
        row_frame.pack_propagate(False)
        self._sidebar_rows[item["id"]] = row_frame
        
        img_lbl = ctk.CTkLabel(row_frame, text="", width=40, height=40, corner_radius=5)
        img_lbl.pack(side="left", padx=5, pady=5)
        
        if item.get("id") == "liked_songs":
            likes_img = _load_likes_ctk_image(40)
            if likes_img:
                img_lbl.configure(image=likes_img, text="", fg_color="transparent")
                self.card_images.append(likes_img)
                self._perm_images.append(likes_img)
            else:
                img_lbl.configure(text="❤️", font=("Arial", 18), fg_color="#15803d")
        else:
            cover_url = item.get("cover_url")
            if not cover_url and item.get("thumbnails"):
                cover_url = self._get_best_thumbnail_url(item.get("thumbnails"), 40)
                
            if cover_url:
                threading.Thread(
                    target=self._load_sidebar_thumb,
                    args=(cover_url, img_lbl),
                    daemon=True
                ).start()
            else:
                icon_img = _load_icon_ctk_image(40)
                if icon_img:
                    img_lbl.configure(image=icon_img, text="", fg_color="transparent")
                    self.card_images.append(icon_img)
                    self._perm_images.append(icon_img)
                else:
                    img_lbl.configure(text="🎵", font=("Arial", 18), fg_color="#272727")
                 
        text_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True, padx=5)
        
        title_lbl = ctk.CTkLabel(text_frame, text=item["title"][:20], font=("Arial", 12, "bold"), anchor="w", height=20)
        title_lbl.pack(fill="x", pady=(2, 0))
        
        sub_lbl = ctk.CTkLabel(text_frame, text=item["subtitle"], font=("Arial", 10), text_color="gray", anchor="w", height=15)
        sub_lbl.pack(fill="x")
        
        for w in (row_frame, img_lbl, text_frame, title_lbl, sub_lbl):
            w.bind("<Button-1>", lambda e, i=item: self._on_sidebar_playlist_click(i))
            if item.get("is_custom_playlist", False):
                w.bind("<Button-3>", lambda e, i=item: self._show_playlist_context_menu(e, i))

        self._setup_hover_highlight(row_frame, hover_color="#1a1a1a")

    def _load_sidebar_thumb(self, url, label):
        if not url:
            return
        try:
            r = requests.get(url, timeout=5)
            img = Image.open(io.BytesIO(r.content)).resize((40, 40), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(40, 40))
            self.card_images.append(ctk_img)
            self._perm_images.append(ctk_img)
            
            def _update():
                try:
                    if label.winfo_exists():
                        label.configure(image=ctk_img, text="")
                except Exception:
                    pass
            self.after(0, _update)
        except Exception:
            pass

    def _on_sidebar_playlist_click(self, item):
        self._save_view()
        self.show_playlist(item)

    # ─────────────────────────────────────────────── Top bar
    def _build_topbar(self):
        self.top_bar = ctk.CTkFrame(self, height=70, fg_color="transparent", corner_radius=0)
        self.top_bar.grid(row=0, column=1, sticky="new")

        self.back_btn = ctk.CTkButton(
            self.top_bar, text="←", width=40, height=40,
            fg_color="transparent", hover_color="#272727",
            corner_radius=20, command=self.go_back
        )
        self.back_btn.pack(side="left", padx=(20, 10), pady=15)
        self.back_btn.pack_forget()

        search_container = ctk.CTkFrame(self.top_bar, fg_color="#272727", corner_radius=25)
        search_container.pack(side="left", pady=15, padx=10, fill="x", expand=True)

        ctk.CTkLabel(search_container, text="🔍", font=("Arial", 16)).pack(side="left", padx=(15, 10))

        self.search_entry = ctk.CTkEntry(
            search_container, placeholder_text="Rechercher une musique...",
            fg_color="transparent", border_width=0, font=("Arial", 14)
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 15))
        self.search_entry.bind("<Return>", self._on_search)
        self.search_entry.bind("<FocusIn>", self._show_search_dropdown)
        # Supprimé : FocusOut fermait le dropdown avant que le clic sur un item se déclenche
        # La fermeture est gérée uniquement par _on_global_click
        self.search_entry.bind("<Button-1>", lambda e: self.after(10, self._show_search_dropdown))

        # Bouton dossier / tiroir à droite dans la capsule de recherche
        self.drawer_btn = ctk.CTkButton(
            search_container, text="🗄️", width=36, height=36, corner_radius=18,
            fg_color="transparent", hover_color="#3e3e3e", text_color="gray",
            font=("Arial", 16), command=self.show_search
        )
        self.drawer_btn.pack(side="right", padx=(5, 5))

    # ─────────────────────────────────────────────── Search Dropdown
    def _show_search_dropdown(self, event=None):
        """Affiche le panneau des recherches récentes (CTkFrame interne, sans vol de focus)."""
        if self._dropdown_visible:
            return
        recent = self.db.get_recent_searches(limit=8)
        if not recent:
            return

        self._dropdown_visible = True

        # Calculer la position relative à la fenêtre racine (pas en coords écran)
        self.update_idletasks()
        root_x   = self.winfo_rootx()
        root_y   = self.winfo_rooty()
        entry_rx = self.search_entry.winfo_rootx()
        entry_ry = self.search_entry.winfo_rooty()
        entry_h  = self.search_entry.winfo_height()
        entry_w  = self.search_entry.winfo_width() + 100

        dx = entry_rx - root_x - 50
        dy = entry_ry - root_y + entry_h + 8
        dropdown_h = min(len(recent) * 62 + 55, 420)

        # CTkFrame placé dans la même fenêtre → aucun vol de focus clavier
        self.search_dropdown = ctk.CTkFrame(
            self, fg_color="#282828", corner_radius=10,
            border_width=1, border_color="#3a3a3a",
            width=entry_w, height=dropdown_h
        )
        self.search_dropdown.place(x=dx, y=dy)
        self.search_dropdown.lift()

        # En-tête
        header_frame = ctk.CTkFrame(self.search_dropdown, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(12, 5))
        ctk.CTkLabel(header_frame, text="Recherches récentes",
                     font=("Arial", 13, "bold"), text_color="white").pack(side="left")
        ctk.CTkButton(header_frame, text="Tout effacer", fg_color="transparent",
                      text_color="#1db954", hover_color="#282828", font=("Arial", 11),
                      command=self._clear_recent_searches).pack(side="right")

        # Séparateur
        sep = ctk.CTkFrame(self.search_dropdown, height=1, fg_color="#3a3a3a")
        sep.pack(fill="x", padx=10)

        for item in recent:
            self._add_dropdown_item(item)

    def _add_dropdown_item(self, item):
        row = ctk.CTkFrame(self.search_dropdown, fg_color="transparent", corner_radius=5)
        row.pack(fill="x", padx=8, pady=2)

        type_icons = {"song": "🎵", "artist": "👤", "playlist": "📋", "album": "💿"}
        icon = type_icons.get(item.get("type", ""), "🔍")

        img_lbl = ctk.CTkLabel(row, text=icon, font=("Arial", 16), width=36, height=36, corner_radius=4)
        img_lbl.pack(side="left", padx=(5, 8), pady=8)
        
        thumb_url = item.get("thumbnail_url")
        if thumb_url:
            threading.Thread(
                target=self._load_dropdown_thumb,
                args=(thumb_url, img_lbl),
                daemon=True
            ).start()

        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(text_frame, text=item.get("title", "")[:40],
                     font=("Arial", 12, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(text_frame, text=item.get("subtitle", "")[:40],
                     font=("Arial", 10), text_color="gray", anchor="w").pack(fill="x")

        # Bouton supprimer l'entrée
        del_btn = ctk.CTkButton(row, text="✕", width=24, height=24, corner_radius=12,
                                fg_color="transparent", hover_color="#3a3a3a",
                                text_color="gray", font=("Arial", 11),
                                command=lambda i=item: self._delete_recent_item(i))
        del_btn.pack(side="right", padx=5)

        # Clic sur la ligne → chercher
        def on_click(e, t=item.get("title", "")):
            self._close_dropdown()
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, t)
            self._on_search(None)

        for w in (row, text_frame, img_lbl):
            w.bind("<Button-1>", on_click)

        self._setup_hover_highlight(row, hover_color="#3a3a3a")

    def _hide_search_dropdown_delayed(self, event=None):
        """Délai pour laisser les clics sur le dropdown se déclencher d'abord."""
        self.after(250, self._close_dropdown)

    def _close_dropdown(self):
        if self.search_dropdown and self._dropdown_visible:
            try:
                self.search_dropdown.place_forget()
                self.search_dropdown.destroy()
            except Exception:
                pass
        self.search_dropdown = None
        self._dropdown_visible = False

    def _clear_recent_searches(self):
        self.db.clear_recent_searches()
        self._close_dropdown()

    def _delete_recent_item(self, item):
        self.db.delete_recent_search(item.get("id", ""))
        self._close_dropdown()
        # Ré-ouvrir si des éléments restent
        self.after(100, lambda: self._show_search_dropdown())

    def _on_global_click(self, event):
        # Si le dropdown de recherche est visible, fermer si le clic est en dehors
        if self._dropdown_visible and self.search_dropdown:
            try:
                widget = event.widget
                in_search = False
                curr = widget
                while curr:
                    if curr == self.search_entry or curr == self.search_dropdown or curr == self.drawer_btn:
                        in_search = True
                        break
                    curr = curr.master
                if not in_search:
                    self._close_dropdown()
            except Exception:
                pass

    def _load_dropdown_thumb(self, url, label):
        if not url:
            return
        try:
            r = requests.get(url, timeout=3)
            img = Image.open(io.BytesIO(r.content)).resize((36, 36), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(36, 36))
            self.card_images.append(ctk_img)
            self._perm_images.append(ctk_img)
            
            def _update():
                try:
                    if label.winfo_exists():
                        label.configure(image=ctk_img, text="")
                except Exception:
                    pass
            self.after(0, _update)
        except Exception:
            pass

    # ─────────────────────────────────────────────── Main scrollable content
    def _build_main_content(self):
        self.main_content = ctk.CTkFrame(
            self, corner_radius=0, fg_color="transparent"
        )
        self.main_content.grid(row=0, column=1, sticky="nsew", pady=(70, 0))
        self.main_content.grid_rowconfigure(0, weight=1)
        self.main_content.grid_columnconfigure(0, weight=1)
        self._real_main_content = self.main_content

    def _get_scrollable(self):
        """Remplace self.main_content par un CTkScrollableFrame."""
        self._cleanup_virtual_list()
        if self.main_content is not self._real_main_content:
            try:
                self.main_content.destroy()
            except Exception:
                pass
        self._real_main_content.grid_rowconfigure(0, weight=1)
        self._real_main_content.grid_columnconfigure(0, weight=1)
        sf = ctk.CTkScrollableFrame(self._real_main_content, corner_radius=0, fg_color="transparent")
        sf.grid(row=0, column=0, sticky="nsew")
        sf.grid_columnconfigure(0, weight=1)
        self.main_content = sf
        return sf

    # ─────────────────────────────────────────────── Player bar (row 1)
    def _build_player_bar(self):
        bar = ctk.CTkFrame(self, height=85, fg_color="transparent", corner_radius=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)

        # ── Zone gauche : pochette + titre/artiste + Like
        left = ctk.CTkFrame(bar, fg_color="transparent", width=280)
        left.pack(side="left", padx=(12, 0), fill="y")
        left.pack_propagate(False)

        self.bar_thumb = ctk.CTkLabel(left, text="", width=55, height=55,
                                      corner_radius=6, fg_color="#272727",
                                      font=("Arial", 24))
        self.bar_thumb.pack(side="left", padx=(0, 10), pady=15)
        icon_img = _load_icon_ctk_image(55)
        if icon_img:
            self.bar_thumb.configure(image=icon_img, text="")
            self._perm_images.append(icon_img)

        # Bouton Like circular (Plus / Coche)
        self.like_btn = ctk.CTkButton(
            left, text="+", width=24, height=24, corner_radius=12,
            fg_color="transparent", hover_color="#272727",
            text_color="gray", font=("Arial", 12, "bold"),
            border_width=1, border_color="gray",
            command=self._toggle_like_current
        )
        self.like_btn.pack(side="right", padx=(5, 10), pady=30)

        info = ctk.CTkFrame(left, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        self.bar_title = ctk.CTkLabel(info, text="Aucune piste", font=("Arial", 13, "bold"),
                                      anchor="w", wraplength=150)
        self.bar_title.pack(fill="x", pady=(18, 2))

        self.bar_artist = ctk.CTkLabel(info, text="—", font=("Arial", 11),
                                       text_color="gray", anchor="w")
        self.bar_artist.pack(fill="x")
        self.bar_artist.bind("<Button-1>", lambda e: self._on_bar_artist_click())
        self.bar_artist.configure(cursor="hand2")

        # ── Zone centre : boutons + slider
        center = ctk.CTkFrame(bar, fg_color="transparent")
        center.pack(side="left", fill="both", expand=True, padx=20)

        btn_row = ctk.CTkFrame(center, fg_color="transparent")
        btn_row.pack(pady=(10, 4))

        self.shuffle_btn = ctk.CTkButton(btn_row, text="🔀", width=36, height=36,
                                         fg_color="transparent", hover_color="#2a2a2a",
                                         corner_radius=18, font=("Arial", 16),
                                         text_color="gray",
                                         command=self._toggle_shuffle)
        self.shuffle_btn.pack(side="left", padx=4)

        self.prev_btn = ctk.CTkButton(btn_row, text="⏮", width=36, height=36,
                                       fg_color="transparent", hover_color="#2a2a2a",
                                       corner_radius=18, font=("Arial", 18),
                                       command=self._play_prev)
        self.prev_btn.pack(side="left", padx=4)

        self.play_btn = ctk.CTkButton(btn_row, text="▶", width=44, height=44,
                                       fg_color="#1db954", hover_color="#1ed760",
                                       corner_radius=22, font=("Arial", 18),
                                       text_color="black",
                                       command=self._toggle_play)
        self.play_btn.pack(side="left", padx=4)

        self.next_btn = ctk.CTkButton(btn_row, text="⏭", width=36, height=36,
                                       fg_color="transparent", hover_color="#2a2a2a",
                                       corner_radius=18, font=("Arial", 18),
                                       command=lambda: self._play_next(auto_transition=False))
        self.next_btn.pack(side="left", padx=4)

        self.repeat_btn = ctk.CTkButton(btn_row, text="🔁", width=36, height=36,
                                        fg_color="transparent", hover_color="#2a2a2a",
                                        corner_radius=18, font=("Arial", 16),
                                        text_color="gray",
                                        command=self._toggle_repeat)
        self.repeat_btn.pack(side="left", padx=4)

        # Slider + temps
        progress_row = ctk.CTkFrame(center, fg_color="transparent")
        progress_row.pack(fill="x", pady=(0, 8))

        self.bar_time_cur = ctk.CTkLabel(progress_row, text="0:00",
                                          font=("Arial", 11), text_color="gray", width=40)
        self.bar_time_cur.pack(side="left")

        self.bar_slider = ctk.CTkSlider(progress_row, from_=0, to=100,
                                         height=4, button_length=10,
                                         progress_color="#1db954",
                                         fg_color="#444", button_color="#fff",
                                         button_hover_color="#1db954",
                                         command=self._on_slider_move)
        self.vol_slider = None # Sera configuré plus bas
        self.bar_slider.pack(side="left", fill="x", expand=True, padx=8)
        self.bar_slider.set(0)
        self.bar_slider.bind("<ButtonPress-1>",   lambda e: setattr(self, "_slider_dragging", True))
        self.bar_slider.bind("<ButtonRelease-1>", self._on_slider_release)

        self.bar_time_tot = ctk.CTkLabel(progress_row, text="0:00",
                                          font=("Arial", 11), text_color="gray", width=40)
        self.bar_time_tot.pack(side="left")

        # ── Zone droite : volume
        right = ctk.CTkFrame(bar, fg_color="transparent", width=160)
        right.pack(side="right", padx=20, fill="y")
        right.pack_propagate(False)

        vol_row = ctk.CTkFrame(right, fg_color="transparent")
        vol_row.pack(side="right", pady=30)

        ctk.CTkLabel(vol_row, text="🔊", font=("Arial", 14)).pack(side="left", padx=(0, 6))

        self.vol_slider = ctk.CTkSlider(vol_row, from_=0, to=100, width=100,
                                         height=4, button_length=10,
                                         progress_color="#1db954",
                                         fg_color="#444", button_color="#fff",
                                         button_hover_color="#1db954",
                                         command=self._on_volume_change)
        self.vol_slider.set(80)
        self.vol_slider.pack(side="left")

    # ═══════════════════════════════════════════════════════ CALLBACKS AUDIO
    def _on_track_start(self, track: dict):
        """Appelé depuis le thread audio dès que la lecture commence."""
        self.after(0, lambda: self._update_bar_info(track))

    def _update_bar_info(self, track: dict):
        track = self._normalize_track(track)
        title  = track.get("title", "Titre inconnu")
        artist = track.get("artist", "")
        self.current_playing_artist_id = track.get("artist_id")

        self.bar_title.configure(text=title[:40])
        self.bar_artist.configure(text=artist[:40])
        self.play_btn.configure(text="⏸")

        # Pochette
        thumbs = track.get("thumbnails", [])
        url = self._get_best_thumbnail_url(thumbs, 55)
        if url:
            threading.Thread(target=self._load_bar_thumb, args=(url,), daemon=True).start()
        else:
            icon_img = _load_icon_ctk_image(55)
            if icon_img:
                self.bar_thumb.configure(image=icon_img, text="")
                self._perm_images.append(icon_img)
            else:
                self.bar_thumb.configure(image=None, text="🎵")

        # Mise à jour de l'icône de Like
        track_id = track.get("videoId")
        self.current_playing_track_id = track_id
        self._refresh_track_playing_indicators()
        
        is_liked = self.db.is_liked(track_id) if track_id else False
        self._update_like_button(self.like_btn, is_liked)

    def _update_like_button(self, btn, is_liked):
        if is_liked:
            btn.configure(
                text="✓",
                fg_color="#1ed760",
                text_color="black",
                hover_color="#1db954",
                border_width=0
            )
        else:
            btn.configure(
                text="+",
                fg_color="transparent",
                text_color="gray",
                hover_color="#272727",
                border_width=1,
                border_color="gray"
            )

    def _load_bar_thumb(self, url: str):
        try:
            r = requests.get(url, timeout=8)
            img = Image.open(io.BytesIO(r.content)).resize((55, 55), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(55, 55))
            self._bar_thumb_img = ctk_img
            self._perm_images.append(ctk_img)
            
            def _update():
                try:
                    if self.bar_thumb.winfo_exists():
                        self.bar_thumb.configure(image=ctk_img, text="")
                except Exception:
                    pass
            self.after(0, _update)
        except Exception:
            pass

    def _on_progress(self, elapsed: float, total: float):
        """Appelé toutes les 500ms depuis le thread de monitoring VLC."""
        if self._slider_dragging:
            return
        self._current_duration = total

        def update():
            pct = (elapsed / total * 100) if total > 0 else 0
            self.bar_slider.set(pct)
            self.bar_time_cur.configure(text=fmt_time(elapsed))
            self.bar_time_tot.configure(text=fmt_time(total))

        self.after(0, update)

    def _on_track_end(self):
        self.after(0, lambda: self._play_next(auto_transition=True))

    def _play_next(self, auto_transition=False):
        if not self.playback_queue:
            self._reset_player_ui()
            return

        if self.repeat_mode == "one" and auto_transition:
            self._play_track(self.playback_queue[self.queue_index], self.playback_queue)
            return

        next_idx = self.queue_index + 1
        if next_idx < len(self.playback_queue):
            self.queue_index = next_idx
            self._play_track(self.playback_queue[self.queue_index], self.playback_queue)
        else:
            if self.repeat_mode == "all":
                self.queue_index = 0
                self._play_track(self.playback_queue[self.queue_index], self.playback_queue)
            elif self.shuffle_mode == "intelligent":
                current_track = self.playback_queue[self.queue_index]
                threading.Thread(target=self._load_intelligent_shuffle_suggestions, args=(current_track, True), daemon=True).start()
            else:
                self._reset_player_ui()

    def _play_prev(self):
        if not self.playback_queue:
            return
            
        try:
            # get_time() est en ms
            elapsed = self.audio_player._player.get_time() / 1000.0 if self.audio_player._player else 0
        except Exception:
            elapsed = 0
            
        if elapsed > 3.0:
            self.audio_player.seek(0)
            return

        prev_idx = self.queue_index - 1
        if prev_idx >= 0:
            self.queue_index = prev_idx
            self._play_track(self.playback_queue[self.queue_index], self.playback_queue)
        else:
            if self.repeat_mode == "all":
                self.queue_index = len(self.playback_queue) - 1
                self._play_track(self.playback_queue[self.queue_index], self.playback_queue)
            else:
                self.audio_player.seek(0)

    def _reset_player_ui(self):
        def reset():
            self.play_btn.configure(text="▶")
            self.bar_slider.set(0)
            self.bar_time_cur.configure(text="0:00")
            self.bar_title.configure(text="Aucune piste")
            self.bar_artist.configure(text="—")
        self.after(0, reset)

    # ─────────────────────────────────────────────── Contrôles player bar
    def _toggle_play(self):
        self.audio_player.toggle_play()
        is_now_playing = self.audio_player.is_playing
        self.play_btn.configure(text="⏸" if is_now_playing else "▶")

    def _on_slider_move(self, value):
        if self._current_duration > 0:
            t = value / 100 * self._current_duration
            self.bar_time_cur.configure(text=fmt_time(t))

    def _on_slider_release(self, event):
        self._slider_dragging = False
        if self._current_duration > 0:
            t = self.bar_slider.get() / 100 * self._current_duration
            self.audio_player.seek(t)

    def _on_volume_change(self, value):
        self.audio_player.set_volume(int(value))

    def _toggle_shuffle(self):
        if self.shuffle_mode == "none":
            self.shuffle_mode = "shuffle"
            self.shuffle_btn.configure(text_color="#1db954", text="🔀")
            if self.playback_queue and self.queue_index >= 0:
                import random
                current = self.playback_queue[self.queue_index]
                others = [t for i, t in enumerate(self.playback_queue) if i != self.queue_index]
                random.shuffle(others)
                self.playback_queue = [current] + others
                self.queue_index = 0
            print("[Shuffle] Mode aléatoire standard activé.")
        elif self.shuffle_mode == "shuffle":
            self.shuffle_mode = "intelligent"
            self.shuffle_btn.configure(text_color="#8b5cf6", text="🔀🧠")
            if self.playback_queue and self.queue_index >= 0:
                current = self.playback_queue[self.queue_index]
                threading.Thread(target=self._load_intelligent_shuffle_suggestions, args=(current,), daemon=True).start()
            print("[Shuffle] Mode aléatoire intelligent activé.")
        else:
            self.shuffle_mode = "none"
            self.shuffle_btn.configure(text_color="gray", text="🔀")
            if self.playback_queue and self.queue_index >= 0 and self.original_queue:
                current = self.playback_queue[self.queue_index]
                self.playback_queue = list(self.original_queue)
                self.queue_index = 0
                for i, t in enumerate(self.playback_queue):
                    if t.get("videoId") == current.get("videoId"):
                        self.queue_index = i
                        break
            print("[Shuffle] Mode aléatoire désactivé.")

    def _toggle_repeat(self):
        if self.repeat_mode == "none":
            self.repeat_mode = "all"
            self.repeat_btn.configure(text_color="#1db954", text="🔁")
            print("[Repeat] Répéter toute la file activé.")
        elif self.repeat_mode == "all":
            self.repeat_mode = "one"
            self.repeat_btn.configure(text_color="#1db954", text="🔂")
            print("[Repeat] Répéter le titre en cours activé.")
        else:
            self.repeat_mode = "none"
            self.repeat_btn.configure(text_color="gray", text="🔁")
            print("[Repeat] Répétition désactivée.")

    # ═══════════════════════════════════════════════════════ NAVIGATION
    def _safe_after(self, key, ms, callback):
        """Planifie un after() avec annulable via _cancel_after(key)."""
        self._cancel_after(key)
        aid = self.after(ms, lambda: self._run_after(key, callback))
        self._after_ids[key] = aid

    def _cancel_after(self, key):
        aid = self._after_ids.pop(key, None)
        if aid:
            try:
                self.after_cancel(aid)
            except Exception:
                pass

    def _run_after(self, key, callback):
        self._after_ids.pop(key, None)
        try:
            callback()
        except Exception as e:
            print(f"[ERROR] after({key}): {e}")

    def _cancel_all_after(self):
        for key in list(self._after_ids.keys()):
            self._cancel_after(key)

    def _clear_main(self):
        try:
            self._stop_lazy_render()
            self._stop_lazy_cards()
            self._cleanup_virtual_list()
            self._cancel_all_after()
            self._close_dropdown()
            # Détruire les enfants de _real_main_content, puis le scrollable lui-même
            for w in self._real_main_content.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
            if self.main_content is not self._real_main_content:
                try:
                    self.main_content.destroy()
                except Exception:
                    pass
                self.main_content = self._real_main_content
            # Reset toutes les configs de grid du frame overlay
            for i in range(self._real_main_content.grid_size()[1]):
                self._real_main_content.grid_rowconfigure(i, weight=0)
            self._real_main_content.grid_columnconfigure(0, weight=0)
            self.card_images = []
            self._row_like_buttons = {}
        except Exception as e:
            traceback.print_exc()
    
    def _display_virtual_tracks(self, tracks, start_row=1):
        """Affiche une liste de pistes avec défilement virtuel (pool fixe de slots)."""
        self._cleanup_virtual_list()
        valid = [t for t in tracks if t.get("videoId") or t.get("id") or t.get("video_id")]
        if not valid:
            ctk.CTkLabel(self.main_content, text="Aucune piste trouvée.",
                         font=("Arial", 14), text_color="gray").grid(row=start_row, column=0, pady=50)
            return
        vl = VirtualTrackList(self.main_content, valid, self)
        vl.grid(row=start_row, column=0, padx=0, pady=0, sticky="nsew")
        self.main_content.grid_rowconfigure(start_row, weight=1)
        self.main_content.grid_columnconfigure(0, weight=1)
        self._current_virtual_list = vl

    def _cleanup_virtual_list(self):
        if hasattr(self, '_current_virtual_list') and self._current_virtual_list is not None:
            try:
                self._current_virtual_list.cleanup()
                self._current_virtual_list.destroy()
            except Exception:
                pass
        self._current_virtual_list = None

    def _save_view(self):
        self.view_stack.append((self.current_view, self.current_data))

    def go_back(self):
        if self.view_stack:
            view, data = self.view_stack.pop()
            self.current_view = view
            self.current_data = data
            if view == "home":
                self.show_home(False)
            elif view == "playlist":
                self.show_playlist(data, False)
            elif view == "library":
                self.show_library()
            elif view == "search":
                self.show_search()
            elif view == "artist":
                self.show_artist(data, False)
        if not self.view_stack:
            self.back_btn.pack_forget()

    def _init_splash(self):
        """Configure bg_window comme splash screen centré pendant le chargement."""
        if getattr(self, '_app_revealed', False):
            return
        try:
            splash_w, splash_h = 480, 480
            self.update_idletasks()
            # Utiliser GetSystemMetrics pour le moniteur principal (fiable en multi-écrans)
            try:
                import ctypes
                user32 = ctypes.windll.user32
                screen_w = user32.GetSystemMetrics(0)  # Largeur moniteur principal
                screen_h = user32.GetSystemMetrics(1)  # Hauteur moniteur principal
            except Exception:
                screen_w = self.winfo_screenwidth()
                screen_h = self.winfo_screenheight()
            x = (screen_w - splash_w) // 2
            y = (screen_h - splash_h) // 2

            self.bg_window.geometry(f"{splash_w}x{splash_h}+{x}+{y}")
            self.bg_window.lift()  # Premier plan pendant le chargement
            self.bg_target_size = (splash_w, splash_h)

            # Titre de l'app en bas du splash
            self._splash_title_lbl = ctk.CTkLabel(
                self.bg_window, text="Rscrap",
                font=("Arial", 36, "bold"), text_color="white",
                fg_color="transparent"
            )
            self._splash_title_lbl.place(relx=0.5, rely=0.80, anchor="center")

            # Barre de séparation décorative
            sep = ctk.CTkFrame(self.bg_window, fg_color="#1db954", height=2, width=160, corner_radius=1)
            sep.place(relx=0.5, rely=0.87, anchor="center")
            self._splash_sep = sep

            # Texte de chargement
            self._splash_loading_lbl = ctk.CTkLabel(
                self.bg_window, text="Chargement en cours...",
                font=("Arial", 13), text_color="#888888",
                fg_color="transparent"
            )
            self._splash_loading_lbl.place(relx=0.5, rely=0.93, anchor="center")

            print("[Splash] Splash centré affiché.")
        except Exception as e:
            print(f"[Splash] Erreur init splash: {e}")

    # ─────────────────────────────────────────────── Pré-chargement au démarrage
    def _preload_and_show(self):
        """
        Thread de démarrage : télécharge les miniatures nécessaires pour la
        page Home et la page Liked en arrière-plan, puis révèle la fenêtre.
        """
        print("[Preload] Démarrage du pré-chargement...")

        # ── 1. Charger les données de la Home ──────────────────
        home_data = []
        try:
            home_data = self.api.get_home()
            self._preloaded_home = home_data
            print(f"[Preload] Home chargée ({len(home_data)} sections).")
        except Exception as e:
            print(f"[Preload] Erreur Home: {e}")
            self._preloaded_home = []

        # ── 2. Télécharger les miniatures de la Home (cartes) ──
        home_urls = set()
        for section in home_data:
            for item in section.get("contents", [])[:12]:
                thumbs = item.get("thumbnails", [])
                if thumbs:
                    url = self._get_best_thumbnail_url(thumbs, 160)
                    if url:
                        home_urls.add(url)
        print(f"[Preload] {len(home_urls)} miniatures Home à télécharger.")
        for url in home_urls:
            self._preload_download_thumb(url)

        # ── 3. Télécharger les miniatures des Titres Likés ─────
        liked_tracks = self.db.get_liked_tracks()
        liked_urls = set()
        for t in liked_tracks:
            thumb_url = t.get("thumbnail_url", "")
            if thumb_url:
                liked_urls.add(thumb_url)
        print(f"[Preload] {len(liked_urls)} miniatures Liked à télécharger.")
        for url in liked_urls:
            self._preload_download_thumb(url)

        print("[Preload] Pré-chargement terminé. Affichage de l'application.")
        # ── 4. Révéler l'application sur le thread principal ───
        self.after(0, self._reveal_app)

    def _preload_download_thumb(self, url: str):
        """Télécharge et sauvegarde une miniature dans le cache (silencieux)."""
        if not url:
            return
        try:
            cache_path = self.cache_manager.get_thumbnail_cache_path(url)
            if os.path.exists(cache_path):
                return  # Déjà en cache (ex: même session)
            r = requests.get(url, timeout=8)
            img = Image.open(io.BytesIO(r.content))
            img.save(cache_path, "PNG")
        except Exception:
            pass

    def _reveal_app(self):
        """Affiche la fenêtre principale une fois le pré-chargement terminé."""
        self._app_revealed = True
        if hasattr(self, '_splash_after_id') and self._splash_after_id:
            try:
                self.after_cancel(self._splash_after_id)
            except Exception:
                pass
            self._splash_after_id = None

        # Supprimer les éléments splash du bg_window
        for attr in ('_splash_title_lbl', '_splash_loading_lbl', '_splash_sep'):
            w = getattr(self, attr, None)
            if w:
                try:
                    w.place_forget()
                    w.destroy()
                except Exception:
                    pass
                setattr(self, attr, None)
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.show_home()
        except Exception as e:
            print(f"[Preload] Erreur révélation: {e}")
            try:
                self.deiconify()
                self.show_home()
            except Exception:
                pass

    # ─────────────────────────────────────────────── Accueil
    def show_home(self, save=True):
        try:
            if save:
                self.view_stack = []
                self.back_btn.pack_forget()
            self.current_view = "home"
            self.current_data = None
            self.home_btn.configure(fg_color="#272727")
            self._clear_main()

            sf = self._get_scrollable()
            ctk.CTkLabel(sf, text="Accueil", font=("Arial", 28, "bold")).grid(
                row=0, column=0, padx=20, pady=(20, 30), sticky="w")
            sf.grid_columnconfigure(0, weight=1)

            # Si les données ont été pré-chargées, affichage instantané
            preloaded = getattr(self, '_preloaded_home', None)
            if preloaded is not None:
                self._display_home(preloaded)
                # Consommer les données pré-chargées (suivantes rechargées normalement)
                self._preloaded_home = None
            else:
                # Affichage du spinner de chargement
                self._home_loading = ctk.CTkLabel(
                    sf, text="Chargement de l'accueil...",
                    font=("Arial", 15), text_color="gray")
                self._home_loading.grid(row=1, column=0, pady=60)
                threading.Thread(target=self._load_home, daemon=True).start()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[FATAL] show_home error: {e}")

    def _load_home(self):
        try:
            home = self.api.get_home()
            self.after(0, lambda: self._display_home(home))
        except Exception as e:
            print(f"[ERROR] Home loading error: {e}")

    def _display_home(self, home_data):
        if hasattr(self, '_home_loading') and self._home_loading:
            try:
                self._home_loading.destroy()
            except Exception:
                pass
        self._home_loading = None
        row = 1
        for section in home_data:
            title   = section.get("title")
            content = section.get("contents", [])
            valid_contents = [c for c in content if c.get("videoId") or c.get("playlistId") or c.get("browseId")]
            if title and valid_contents:
                ctk.CTkLabel(self.main_content, text=title,
                             font=("Arial", 20, "bold")).grid(
                    row=row, column=0,
                    padx=20, pady=(30, 15), sticky="w")
                row += 1
                
                grid = ResponsiveCardGrid(self.main_content, valid_contents[:12], self)
                grid.grid(row=row, column=0, padx=15, pady=5, sticky="ew")
                row += 1

    # ─────────────────────────────────────────────── Playlist / Album
    def _on_card_click(self, item, track_list=None):
        if item.get("videoId"):
            self._play_track(item, track_list)
        else:
            browse_id = item.get("browseId") or item.get("playlistId") or item.get("id")
            is_art = item.get("resultType") == "artist" or "artist" in item.get("subtitle", "").lower() or "artiste" in item.get("subtitle", "").lower()
            if browse_id:
                type_str = "artist" if is_art else "playlist"
                thumbs = item.get("thumbnails", [])
                thumb_url = thumbs[0].get("url") if thumbs else ""
                self.db.add_recent_search(
                    item_id=browse_id,
                    title=item.get("title") or item.get("artist") or "Playlist",
                    subtitle=item.get("subtitle") or ("Artiste" if is_art else "Playlist"),
                    thumbnail_url=thumb_url,
                    type_str=type_str
                )
            self._save_view()
            if is_art:
                self.show_artist(item)
            else:
                self.show_playlist(item)

    def show_playlist(self, item, save=True):
        self.current_view = "playlist"
        self.current_data = item
        self.back_btn.pack(side="left", padx=(20, 10), pady=15)
        self._clear_main()
        self._playlist_sf = self._get_scrollable()
        sf = self._playlist_sf

        header = ctk.CTkFrame(sf, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=30, sticky="ew")
        sf.grid_columnconfigure(0, weight=1)
        sf.grid_rowconfigure(1, weight=0)

        thumb_frame = ctk.CTkFrame(header, width=200, height=200,
                                    corner_radius=10, fg_color="#272727")
        thumb_frame.pack(side="left", padx=(0, 30))
        img_label = ctk.CTkLabel(thumb_frame, text="", width=200, height=200)
        img_label.pack()

        text_frame = ctk.CTkFrame(header, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(text_frame, text=item.get("title", "Playlist"),
                     font=("Arial", 32, "bold"), anchor="w").pack(fill="x")
        self.playlist_subtitle_label = ctk.CTkLabel(text_frame, text=item.get("subtitle", ""),
                     text_color="gray", anchor="w")
        self.playlist_subtitle_label.pack(fill="x", pady=5)

        playlist_id = item.get("id")
        is_local = item.get("is_local", False)

        # Chargement de la pochette & pistes
        if playlist_id == "liked_songs":
            likes_img = _load_likes_ctk_image(200)
            if likes_img:
                img_label.configure(image=likes_img, text="", fg_color="transparent")
                self.card_images.append(likes_img)
                self._perm_images.append(likes_img)
            else:
                img_label.configure(text="❤️", font=("Arial", 70), fg_color="#15803d")
            tracks = self.db.get_liked_tracks()
            self._display_playlist_tracks(tracks, self._playlist_sf)
        elif item.get("is_custom_playlist", False):
            cover_url = item.get("cover_url")
            if cover_url:
                threading.Thread(
                    target=self._load_thumb,
                    args=(cover_url, img_label, 200),
                    daemon=True
                ).start()
            else:
                icon_img = _load_icon_ctk_image(200)
                if icon_img:
                    img_label.configure(image=icon_img, text="", fg_color="transparent")
                    self.card_images.append(icon_img)
                    self._perm_images.append(icon_img)
                else:
                    img_label.configure(text="🎵", font=("Arial", 70), fg_color="#272727")
            
            # Bouton 3 petits points (options)
            options_btn = ctk.CTkButton(
                text_frame, text="⋯", font=("Arial", 22, "bold"),
                width=45, height=30, fg_color="transparent", hover_color="#272727",
                text_color="white",
                command=lambda pid=playlist_id: self._show_playlist_options_menu(options_btn, pid)
            )
            options_btn.pack(side="bottom", anchor="w", pady=10)

            tracks = self.db.get_playlist_tracks(playlist_id)
            self._display_playlist_tracks(tracks, self._playlist_sf)
        else:
            # Playlist / Album YT Music standard → chargement par ID réel
            thumbs = item.get("thumbnails", [])
            if thumbs:
                threading.Thread(
                    target=self._load_thumb,
                    args=(thumbs[-1].get("url"), img_label, 200),
                    daemon=True
                ).start()
            else:
                icon_img = _load_icon_ctk_image(200)
                if icon_img:
                    img_label.configure(image=icon_img, text="", fg_color="transparent")
                    self.card_images.append(icon_img)
                    self._perm_images.append(icon_img)

            browse_id = item.get("playlistId") or item.get("browseId") or item.get("id", "")
            threading.Thread(
                target=lambda bid=browse_id, it=item: self._load_standard_tracks(bid, it),
                daemon=True
            ).start()

    def _load_standard_tracks(self, browse_id, item):
        """Charge les pistes d'une playlist ou album YT Music par son ID réel."""
        tracks = []

        if browse_id:
            # Tentative en tant que playlist (PL..., RDCLAK5uy_...)
            try:
                data = self.api.get_playlist(browse_id)
                if data and data.get("tracks"):
                    tracks = data["tracks"]
                    print(f"[PLAYLIST] {len(tracks)} pistes chargées (id={browse_id})")
            except Exception as e:
                print(f"[WARN] get_playlist({browse_id}): {e}")

        if not tracks and browse_id:
            # Tentative en tant qu'album (MPREb_...)
            try:
                data = self.api.get_album(browse_id)
                if data and data.get("tracks"):
                    album_tracks = data["tracks"]
                    # Injecter le nom d'artiste de l'album si absent dans les pistes
                    artists = data.get("artist", [])
                    artist_name = artists[0].get("name", "") if artists else ""
                    for t in album_tracks:
                        if not t.get("artists") and artist_name:
                            t["artists"] = [{"name": artist_name}]
                    tracks = album_tracks
                    print(f"[ALBUM] {len(tracks)} pistes chargées (id={browse_id})")
            except Exception as e:
                print(f"[WARN] get_album({browse_id}): {e}")

        if not tracks:
            # Fallback : recherche par titre
            query = item.get("title", "")
            if query:
                print(f"[FALLBACK] Recherche texte : {query}")
                tracks = self.api.search(query)

        sf = getattr(self, '_playlist_sf', None)
        self.after(0, lambda t=tracks, s=sf: self._display_playlist_tracks(t, s))

    def _display_playlist_tracks(self, tracks, sf):
        if sf is None:
            sf = getattr(self, '_playlist_sf', self.main_content)
        valid = [t for t in tracks if t.get("videoId") or t.get("id") or t.get("video_id")]
        if not valid:
            ctk.CTkLabel(sf, text="Aucune piste trouvée.",
                         font=("Arial", 14), text_color="gray").grid(row=1, column=0, pady=50)
            return
        liked_ids = self.db.get_all_liked_ids()
        # Bouton supprimer uniquement pour les playlists custom
        remove_pid = None
        if self.current_view == "playlist" and self.current_data and self.current_data.get("is_custom_playlist", False):
            remove_pid = self.current_data.get("id")
        for i, t in enumerate(valid):
            self._add_track_row(t, i + 1, container=sf, liked_ids=liked_ids, remove_pid=remove_pid, track_list=valid)

    def _add_track_row(self, raw_track, row, container=None, liked_ids=None, remove_pid=None, track_list=None):
        if container is None:
            container = self.main_content
        track = self._normalize_track(raw_track)
        title  = track.get("title", "Titre")
        artist = track.get("artist", "")
        
        row_frame = ctk.CTkFrame(container, fg_color="transparent", corner_radius=5)
        row_frame.grid(row=row, column=0, padx=15, pady=2, sticky="ew")
        container.grid_columnconfigure(0, weight=1)

        thumb_frame = ctk.CTkFrame(row_frame, width=50, height=50,
                                    corner_radius=3, fg_color="#272727")
        thumb_frame.pack(side="left", padx=(10, 15), pady=5)
        img_label = ctk.CTkLabel(thumb_frame, text="", width=50, height=50)
        img_label.pack()

        info_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True)

        # Liaison du clic sur toute la ligne (widgets et leurs canvas de rendu CustomTkinter)
        play_cmd = lambda e, t=track: self._play_track(t, track_list)
        for w in (row_frame, info_frame, thumb_frame, img_label):
            w.bind("<Button-1>", play_cmd)
            if hasattr(w, "canvas") and w.canvas:
                w.canvas.bind("<Button-1>", play_cmd)

        track_id = track.get("videoId")

        title_lbl = ctk.CTkLabel(info_frame,
                     text=title[:60] + ("..." if len(title) > 60 else ""),
                     font=("Arial", 13, "bold"), anchor="w")
        title_lbl.pack(fill="x", pady=(5, 2))
        title_lbl.bind("<Button-1>", play_cmd)
        
        row_frame._track_id = track_id
        row_frame._title_lbl = title_lbl
        if track_id and track_id == self.current_playing_track_id:
            title_lbl.configure(text_color="#1ed760")
        else:
            title_lbl.configure(text_color="white")
        
        _has_artist = bool(artist and artist not in ("Artiste inconnu", "—", ""))
        artist_lbl = ctk.CTkLabel(info_frame,
                     text=artist[:60] + ("..." if len(artist) > 60 else ""),
                     text_color="gray", anchor="w", font=("Arial", 11),
                     cursor="hand2" if _has_artist else "")
        artist_lbl.pack(anchor="w")
        if _has_artist:
            artist_lbl.bind("<Button-1>", lambda e, t=track: self._on_row_artist_click(t))
        else:
            artist_lbl.bind("<Button-1>", play_cmd)

        # Actions à droite
        actions_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        actions_frame.pack(side="right", padx=10, fill="y")
        
        track_id = track.get("videoId")
        is_liked = (track_id in liked_ids) if liked_ids is not None and track_id else False
        
        row_like_btn = ctk.CTkButton(
            actions_frame, text="+", width=24, height=24, corner_radius=12,
            fg_color="transparent", hover_color="#272727",
            text_color="gray", font=("Arial", 12, "bold"),
            border_width=1, border_color="gray",
            command=lambda t=track, tid=track_id, af=actions_frame: self._toggle_like_row(t, tid, af)
        )
        self._update_like_button(row_like_btn, is_liked)
        # Enregistrement dans le registre global pour synchronisation en temps réel
        if track_id:
            self._row_like_buttons.setdefault(track_id, []).append(row_like_btn)
        row_like_btn.pack(side="left", padx=5)

        # Ajouter aux playlists
        add_btn = ctk.CTkButton(
            actions_frame, text="➕", width=30, height=45,
            fg_color="transparent", hover_color="#272727",
            text_color="gray", font=("Arial", 14),
            command=lambda t=track: self._show_add_to_playlist_dialog(t)
        )
        add_btn.pack(side="left", padx=5)

        # Bouton supprimer de la playlist (custom playlists uniquement)
        if remove_pid and track_id:
            del_btn = ctk.CTkButton(
                actions_frame, text="➖", width=24, height=24, corner_radius=12,
                fg_color="transparent", hover_color="#272727",
                text_color="gray", font=("Arial", 12, "bold"),
                border_width=1, border_color="#444",
                command=lambda t=track, tid=track_id: self._remove_from_playlist(remove_pid, tid)
            )
            del_btn.pack(side="left", padx=5)

        # Pochette size-matched
        thumbs = track.get("thumbnails", [])
        thumb_url = self._get_best_thumbnail_url(thumbs, 50)
        if thumb_url:
            threading.Thread(
                target=self._load_thumb,
                args=(thumb_url, img_label, 50),
                daemon=True
            ).start()
        else:
            icon_img = _load_icon_ctk_image(50)
            if icon_img:
                img_label.configure(image=icon_img, text="")

        # Configuration de l'hover globalisé récursif
        self._setup_hover_highlight(row_frame, hover_color="#181818")

    # ═══════════════════════════════════════════════════════ LAZY RENDERING
    def _display_tracks_lazy(self, tracks, start_row=1, batch_size=15, container=None):
        """Affiche les pistes par lots avec détection de scroll pour la suite."""
        self._stop_lazy_render()
        if container is None:
            container = self.main_content
        if not tracks:
            ctk.CTkLabel(container, text="Aucune piste trouvée.",
                         font=("Arial", 14), text_color="gray").grid(row=start_row, column=0, pady=50)
            return

        loading = ctk.CTkLabel(container, text=f"Chargement de {len(tracks)} pistes...",
                               font=("Arial", 13), text_color="gray")
        loading.grid(row=start_row, column=0, pady=10)

        self._lazy_data = {
            "tracks": tracks, "index": 0, "total": len(tracks),
            "start_row": start_row, "batch_size": batch_size,
            "container": container, "active": True, "loading": loading
        }
        self._render_tracks_batch()
        self._monitor_tracks_scroll()

    def _stop_lazy_render(self):
        state = getattr(self, '_lazy_data', None)
        if state:
            state["active"] = False
            if state.get("loading"):
                try:
                    state["loading"].destroy()
                except Exception:
                    pass
        self._lazy_data = None

    def _render_tracks_batch(self):
        state = getattr(self, '_lazy_data', None)
        if not state or not state["active"]:
            return
        idx = state["index"]
        if idx >= state["total"]:
            self._stop_lazy_render()
            return
        end = min(idx + state["batch_size"], state["total"])
        for i in range(idx, end):
            self._add_track_row(state["tracks"][i], state["start_row"] + i, state["container"], track_list=state["tracks"])
        state["index"] = end
        # Déplacer le label "Chargement..." après le dernier lot rendu
        loading = state.get("loading")
        if loading and end < state["total"]:
            try:
                loading.grid(row=state["start_row"] + end, column=0, pady=10)
                loading.configure(text=f"Chargement... {end}/{state['total']}")
            except Exception:
                pass
        elif loading:
            try:
                loading.destroy()
            except Exception:
                pass
            state["loading"] = None

    def _monitor_tracks_scroll(self):
        state = getattr(self, '_lazy_data', None)
        if not state or not state["active"]:
            return
        near_bottom = False
        try:
            canvas = self.main_content._parent_canvas
            yview = canvas.yview()
            if yview[1] > 0.6:
                near_bottom = True
        except Exception:
            near_bottom = True
        if near_bottom:
            self._render_tracks_batch()
        self._safe_after('monitor_tracks', 400, self._monitor_tracks_scroll)

    # ─────────────────────────────────────────────── Lazy cards (search)
    def _stop_lazy_cards(self):
        state = getattr(self, '_lazy_cards_data', None)
        if state:
            state["active"] = False
        self._lazy_cards_data = None

    def _render_cards_batch(self):
        state = getattr(self, '_lazy_cards_data', None)
        if not state or not state["active"]:
            return
        idx = state["index"]
        if idx >= state["total"]:
            self._stop_lazy_cards()
            return
        end = min(idx + state["batch_size"], state["total"])
        batch = state["items"][idx:end]
        state["grid"].add_items(batch)
        state["index"] = end

    def _monitor_cards_scroll(self):
        state = getattr(self, '_lazy_cards_data', None)
        if not state or not state["active"]:
            return
        near_bottom = False
        try:
            canvas = self.main_content._parent_canvas
            yview = canvas.yview()
            if yview[1] > 0.6:
                near_bottom = True
        except Exception:
            near_bottom = True
        if near_bottom:
            self._render_cards_batch()
        self._safe_after('monitor_cards', 500, self._monitor_cards_scroll)

    # ═══════════════════════════════════════════════════════ END LAZY

    def _load_thumb(self, url, label, size=160):
        if not url:
            return
        try:
            cache_path = self.cache_manager.get_thumbnail_cache_path(url)
            if os.path.exists(cache_path):
                img = Image.open(cache_path).resize((size, size), Image.Resampling.LANCZOS)
            else:
                r = requests.get(url, timeout=10)
                img = Image.open(io.BytesIO(r.content)).resize((size, size), Image.Resampling.LANCZOS)
                try:
                    img.save(cache_path, "PNG")
                except Exception:
                    pass

            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
            self.card_images.append(ctk_img)
            self._perm_images.append(ctk_img)
            
            def _update():
                try:
                    if label.winfo_exists():
                        label.configure(image=ctk_img, text="")
                except Exception:
                    pass
            self.after(0, _update)
        except Exception:
            pass

    # ─────────────────────────────────────────────── Search
    def show_search(self):
        self.view_stack = []
        self.back_btn.pack_forget()
        self.current_view = "search"
        self.home_btn.configure(fg_color="transparent")
        self._clear_main()

        sf = self._get_scrollable()
        ctk.CTkLabel(sf, text="Explorer",
                     font=("Arial", 28, "bold")).grid(
            row=0, column=0, padx=20, pady=(20, 30), sticky="w")
        sf.grid_columnconfigure(0, weight=1)

        categories = [
            ("Pop", "#ff0050"), ("Rap", "#00c853"), ("Rock", "#ffc107"),
            ("Jazz", "#9c27b0"), ("Électro", "#00bcd4"), ("R&B", "#ff9800"),
        ]
        
        cat_frame = ctk.CTkFrame(sf, fg_color="transparent")
        cat_frame.grid(row=1, column=0, padx=15, pady=10, sticky="ew")
        
        for idx, (cat, color) in enumerate(categories):
            btn = ctk.CTkButton(
                cat_frame, text=cat, fg_color=color, corner_radius=10,
                height=100, hover_color=color, font=("Arial", 18, "bold"),
                command=lambda c=cat: self._search_category(c)
            )
            r = idx // 2
            c = idx % 2
            btn.grid(row=r, column=c, padx=15, pady=15, sticky="nsew")
            cat_frame.grid_columnconfigure(c, weight=1)

    # ─────────────────────────────────────────────── Library
    def show_library(self):
        self.view_stack = []
        self.back_btn.pack_forget()
        self.current_view = "library"
        self.home_btn.configure(fg_color="transparent")
        self._clear_main()

        sf = self._get_scrollable()
        # En-tête
        header = ctk.CTkFrame(sf, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(20, 20), sticky="ew")
        sf.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="Ma bibliothèque", font=("Arial", 28, "bold")).pack(side="left")
        
        create_pl_btn = ctk.CTkButton(
            header, text="➕ Créer une playlist", fg_color="#1db954", hover_color="#1ed760",
            text_color="black", font=("Arial", 12, "bold"),
            command=lambda: self._prompt_create_playlist(None)
        )
        create_pl_btn.pack(side="right", padx=10)

        # Section Playlists
        ctk.CTkLabel(sf, text="Playlists", font=("Arial", 20, "bold")).grid(
            row=1, column=0, padx=20, pady=(20, 10), sticky="w")
        
        # Charger playlists
        playlist_items = []
        
        # 1. Favoris
        liked_tracks = self.db.get_liked_tracks()
        playlist_items.append({
            "id": "liked_songs",
            "title": "Titres likés",
            "subtitle": f"{len(liked_tracks)} titres",
            "is_local": True
        })
        
        # 2. Playlists utilisateur
        custom_playlists = self.db.get_playlists()
        for pl in custom_playlists:
            playlist_items.append({
                "id": pl["id"],
                "title": pl["name"],
                "subtitle": f"{pl.get('track_count', 0)} titres",
                "is_local": True,
                "is_custom_playlist": True,
                "cover_url": pl.get("cover_url")
            })

        grid = ResponsiveCardGrid(sf, playlist_items, self)
        grid.grid(row=2, column=0, padx=15, pady=5, sticky="ew")

        # Section Récemment écoutés (historique)
        ctk.CTkLabel(sf, text="Récemment écoutés", font=("Arial", 20, "bold")).grid(
            row=3, column=0, padx=20, pady=(40, 10), sticky="w")

        history_tracks = self.db.get_history(limit=20)
        if history_tracks:
            for idx, t in enumerate(history_tracks):
                self._add_track_row(t, 4 + idx, track_list=history_tracks)
        else:
            ctk.CTkLabel(self.main_content, text="Aucun historique d'écoute.", font=("Arial", 13), text_color="gray").grid(
                row=4, column=0, pady=20, padx=20, sticky="w")

    def _search_category(self, cat):
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, cat)
        self._on_search(None)

    def _on_search(self, event):
        q = self.search_entry.get().strip()
        if not q:
            return
        self._close_dropdown()
        self._current_search_query = q
        self.current_search_filter = "Tout"
        self._save_view()
        self._clear_main()
        sf = self._get_scrollable()
        sf.grid_columnconfigure(0, weight=1)

        # Titre
        ctk.CTkLabel(sf, text=f"Résultats : {q}",
                     font=("Arial", 28, "bold")).grid(
            row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Chips de filtres
        self._build_filter_chips(row=1)

        threading.Thread(target=lambda: self._search_thread(q), daemon=True).start()

    def _build_filter_chips(self, row=1):
        """Affiche les puces de filtre de recherche sous le titre."""
        # Supprimer l'ancien chip_frame s'il existe
        if hasattr(self, '_chip_frame') and self._chip_frame.winfo_exists():
            self._chip_frame.destroy()

        self._chip_frame = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self._chip_frame.grid(row=row, column=0, padx=15, pady=(0, 10), sticky="w")

        filters = ["Tout", "Musiques", "Artistes", "Playlists"]
        self._chip_buttons = {}
        for label in filters:
            is_active = (label == self.current_search_filter)
            btn = ctk.CTkButton(
                self._chip_frame,
                text=label,
                width=90, height=30,
                corner_radius=15,
                fg_color="#ffffff" if is_active else "#282828",
                hover_color="#e0e0e0" if is_active else "#3a3a3a",
                text_color="#000000" if is_active else "#ffffff",
                font=("Arial", 12, "bold" if is_active else "normal"),
                command=lambda lbl=label: self._apply_search_filter(lbl)
            )
            btn.pack(side="left", padx=4)
            self._chip_buttons[label] = btn

    def _display_loading(self):
        if hasattr(self, '_search_grid') and self._search_grid is not None:
            try:
                self._search_grid.destroy()
            except Exception:
                pass
        self._search_grid = ctk.CTkLabel(self.main_content, text="Chargement...", font=("Arial", 16), text_color="gray")
        self._search_grid.grid(row=2, column=0, pady=60)

    def _apply_search_filter(self, filter_label):
        """Applique un filtre sur la recherche en relançant une requête filtrée."""
        self.current_search_filter = filter_label
        self._build_filter_chips(row=1)

        q = self._current_search_query
        if q:
            self._display_loading()
            threading.Thread(target=lambda: self._search_thread(q, filter_label), daemon=True).start()

    def _search_thread(self, q, filter_label="Tout"):
        api_filter = None
        if filter_label == "Musiques":
            api_filter = "songs"
        elif filter_label == "Artistes":
            api_filter = "artists"
        elif filter_label == "Playlists":
            api_filter = "playlists"

        if api_filter:
            results = self.api.search(q, filter_type=api_filter, limit=50)
        else:
            # Appel unique avec limite élevée (beaucoup plus rapide que 4 appels séparés)
            results = self.api.search(q, filter_type=None, limit=50)
        self.after(0, lambda: self._on_search_results(results))

    def _on_search_results(self, results):
        """Appelé après que la recherche a retourné des résultats."""
        self._current_search_results = results
        self._display_search(results)

    def _display_search(self, results):
        # Supprimer l'ancienne grille si elle existe
        self._stop_lazy_cards()
        for old in ("_search_grid", "_search_sections"):
            h = getattr(self, old, None)
            if h:
                try:
                    if isinstance(h, list):
                        for w in h:
                            w.destroy()
                    else:
                        h.destroy()
                except Exception:
                    pass
        self._search_grid = None
        self._search_sections = []

        valid = [r for r in results if r.get("videoId") or r.get("playlistId") or r.get("browseId")]
        if not valid:
            lbl = ctk.CTkLabel(self.main_content, text="Aucun résultat trouvé.",
                               font=("Arial", 16), text_color="gray")
            lbl.grid(row=2, column=0, pady=60)
            self._search_grid = lbl
            return

        # Grouper par type : artistes > albums > playlists > musiques
        artists  = [r for r in valid if r.get("resultType") == "artist"]
        albums   = [r for r in valid if r.get("resultType") == "album"]
        playlists= [r for r in valid if r.get("resultType") == "playlist"]
        songs    = [r for r in valid if r.get("resultType") in ("song", "video")]

        # Trier chaque groupe par popularité décroissante
        def _pop(item):
            v = item.get("views") or item.get("viewCount") or item.get("subscribers") or ""
            try:
                return int(''.join(c for c in v if c.isdigit()))
            except ValueError:
                return 0
        artists.sort(key=_pop, reverse=True)
        albums.sort(key=_pop, reverse=True)
        playlists.sort(key=_pop, reverse=True)
        songs.sort(key=_pop, reverse=True)

        row = 2  # commence après l'en-tête
        # Artistes / Albums / Playlists → cartes visuelles
        for title, items in [("Artistes", artists), ("Albums", albums), ("Playlists", playlists)]:
            if not items:
                continue
            sec = ctk.CTkLabel(self.main_content, text=title,
                               font=("Arial", 20, "bold"))
            sec.grid(row=row, column=0, padx=20, pady=(20, 10), sticky="w")
            self._search_sections.append(sec)
            row += 1
            grid = ResponsiveCardGrid(self.main_content, items[:12], self)
            grid.grid(row=row, column=0, padx=15, pady=5, sticky="ew")
            self._search_sections.append(grid)
            row += 1

        # Musiques → lignes détaillées (liste verticale)
        if songs:
            sec = ctk.CTkLabel(self.main_content, text="Musiques",
                               font=("Arial", 20, "bold"))
            sec.grid(row=row, column=0, padx=20, pady=(20, 10), sticky="w")
            self._search_sections.append(sec)
            row += 1
            for s in songs[:30]:
                self._add_search_track_row(s, row)
                row += 1

        self.main_content.grid_columnconfigure(0, weight=1)

    def _add_search_track_row(self, raw_track, row):
        track = self._normalize_track(raw_track)
        frame = ctk.CTkFrame(self.main_content, fg_color="transparent", corner_radius=5)
        frame.grid(row=row, column=0, padx=15, pady=2, sticky="ew")
        frame._track_data = track

        tf = ctk.CTkFrame(frame, width=50, height=50, corner_radius=3, fg_color="#272727")
        tf.pack(side="left", padx=(10, 15), pady=5)
        img = ctk.CTkLabel(tf, text="", width=50, height=50)
        img.pack()

        info = ctk.CTkFrame(frame, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        t = track.get("title", "Titre")
        ctk.CTkLabel(info, text=t[:60] + ("..." if len(t) > 60 else ""),
                     font=("Arial", 13, "bold"), anchor="w").pack(fill="x", pady=(5, 2))
        a = track.get("artist", "")
        a_lbl = ctk.CTkLabel(info, text=a[:60] + ("..." if len(a) > 60 else ""),
                     text_color="gray", anchor="w", font=("Arial", 11),
                     cursor="hand2" if a else "")
        a_lbl.pack(fill="x")
        if a:
            a_lbl.bind("<Button-1>", lambda e, t=track: self._on_row_artist_click(t))

        acts = ctk.CTkFrame(frame, fg_color="transparent")
        acts.pack(side="right", padx=10, fill="y")

        like_btn = ctk.CTkButton(acts, text="+", width=24, height=24, corner_radius=12,
                      fg_color="transparent", hover_color="#272727",
                      text_color="gray", font=("Arial", 12, "bold"),
                      border_width=1, border_color="gray")
        like_btn.pack(side="left", padx=5)
        tid = track.get("videoId")
        liked = tid in self._cached_liked_ids if tid else False
        self._update_like_button(like_btn, liked)
        like_btn.configure(command=lambda t_id=tid, lb=like_btn, trk=track: self._toggle_search_like(trk, t_id, lb))

        ctk.CTkButton(acts, text="➕", width=30, height=45,
                      fg_color="transparent", hover_color="#272727",
                      text_color="gray", font=("Arial", 14),
                      command=lambda t=track: self._show_add_to_playlist_dialog(t)).pack(side="left", padx=5)

        for w in (frame, img, info, tf):
            w.bind("<Button-1>", lambda e, t=track: self._play_track(t))

        thumb_url = track.get("thumbnail_url")
        if thumb_url:
            threading.Thread(target=self._load_thumb,
                             args=(thumb_url, img, 50), daemon=True).start()
        else:
            icon_img = _load_icon_ctk_image(50)
            if icon_img:
                img.configure(image=icon_img, text="")

    def _toggle_search_like(self, track, track_id, btn):
        if track_id:
            self.db.add_track(track)
            liked = self.db.toggle_like(track_id)
            self._update_like_button(btn, liked)
            self._sync_like_state_across_ui(track_id, liked)
            self._refresh_sidebar_playlists()

    # ─────────────────────────────────────────────── Normalisation des données
    def _normalize_track(self, track: dict) -> dict:
        if not track:
            return {}
            
        normalized = {}
        normalized["title"] = track.get("title") or "Titre inconnu"
        
        # Artiste
        artist_id = None
        if "artist" in track and isinstance(track["artist"], str):
            normalized["artist"] = track["artist"]
            artist_id = track.get("artist_id")
        elif "artists" in track and isinstance(track["artists"], list) and track["artists"]:
            first = track["artists"][0]
            if isinstance(first, dict):
                normalized["artist"] = first.get("name", "")
                artist_id = first.get("id")
            else:
                normalized["artist"] = str(first)
        else:
            normalized["artist"] = track.get("subtitle") or "Artiste inconnu"
            
        if "artist_id" in track:
            artist_id = track["artist_id"]
        normalized["artist_id"] = artist_id
            
        # ID unique
        vid = track.get("video_id") or track.get("videoId") or track.get("id")
        normalized["videoId"] = vid
        normalized["id"] = vid
        
        # Pochette
        thumb_url = ""
        thumbnails = []
        if "thumbnails" in track and isinstance(track["thumbnails"], list) and track["thumbnails"]:
            thumbnails = track["thumbnails"]
            thumb_url = thumbnails[0].get("url", "")
        elif "thumbnail_url" in track and track["thumbnail_url"]:
            thumb_url = track["thumbnail_url"]
            thumbnails = [{"url": thumb_url}]
        normalized["thumbnail_url"] = thumb_url
        normalized["thumbnails"] = thumbnails
        
        normalized["duration"] = track.get("duration")
        normalized["album"] = track.get("album")
        normalized["cache_path"] = track.get("cache_path")
        
        return normalized

    def _get_best_thumbnail_url(self, thumbnails, target_size: int) -> str:
        if not thumbnails:
            return ""
        if len(thumbnails) == 1:
            return thumbnails[0].get("url", "")
            
        best_url = ""
        best_diff = float("inf")
        for t in thumbnails:
            url = t.get("url", "")
            if not url:
                continue
            w = t.get("width")
            h = t.get("height")
            if w is None or h is None:
                import re
                match = re.search(r'=[ws](\d+)', url)
                if match:
                    size = int(match.group(1))
                    w = size
                    h = size
                else:
                    w = 0
            
            diff = abs(w - target_size)
            if diff < best_diff:
                best_diff = diff
                best_url = url
                
        return best_url or thumbnails[0].get("url", "")

    def _setup_hover_highlight(self, frame, hover_color="#181818", normal_color="transparent"):
        """
        Configure la surbrillance grisée (hover) sur un conteneur 'frame' et tous
        ses widgets enfants — y compris ceux ajoutés après l'appel initial.
        """
        def get_all_children(w):
            children = []
            try:
                for c in w.winfo_children():
                    children.append(c)
                    children.extend(get_all_children(c))
            except Exception:
                pass
            return children

        def set_hover(active):
            try:
                if frame.winfo_exists():
                    frame.configure(fg_color=hover_color if active else normal_color)
            except Exception:
                pass

        def on_enter(e):
            set_hover(True)

        def on_leave(e):
            # Vérifier si la souris est encore sur le frame ou un de ses enfants
            frame.after(20, check_still_inside)

        def check_still_inside():
            try:
                if not frame.winfo_exists():
                    return
                x = frame.winfo_pointerx() - frame.winfo_rootx()
                y = frame.winfo_pointery() - frame.winfo_rooty()
                w = frame.winfo_width()
                h = frame.winfo_height()
                if 0 <= x < w and 0 <= y < h:
                    set_hover(True)  # Toujours à l'intérieur
                else:
                    set_hover(False)
            except Exception:
                set_hover(False)

        # Lier le frame et tous ses enfants existants
        def bind_widget(w):
            try:
                w.bind("<Enter>", on_enter, add="+")
                w.bind("<Leave>", on_leave, add="+")
                if hasattr(w, "canvas") and w.canvas:
                    w.canvas.bind("<Enter>", on_enter, add="+")
                    w.canvas.bind("<Leave>", on_leave, add="+")
            except Exception:
                pass

        for w in [frame] + get_all_children(frame):
            bind_widget(w)

    def _prefetch_next_track(self):
        """Détermine la prochaine piste et résout son URL de flux en arrière-plan."""
        if not self.playback_queue:
            return
        
        next_track = None
        if self.repeat_mode == "one":
            next_track = self.playback_queue[self.queue_index]
        else:
            next_idx = self.queue_index + 1
            if next_idx < len(self.playback_queue):
                next_track = self.playback_queue[next_idx]
            elif self.repeat_mode == "all" and len(self.playback_queue) > 0:
                next_track = self.playback_queue[0]
                
        if not next_track:
            return
            
        video_id = next_track.get("videoId")
        if not video_id:
            return
            
        if self.cache_manager.is_cached(video_id):
            return
            
        if video_id in self.stream_url_cache:
            return
            
        def _worker():
            try:
                print(f"[PREFETCH] Résolution en arrière-plan pour : {next_track.get('title')}")
                url, duration = self.audio_player._get_stream_url(video_id)
                if url:
                    self.stream_url_cache[video_id] = (url, duration)
                    print(f"[PREFETCH] Succès résolution pour : {next_track.get('title')}")
                    # Télécharger également vers le cache local
                    self.cache_manager.download_to_cache(video_id, url)
            except Exception as e:
                print(f"[PREFETCH] Erreur lors de la résolution : {e}")
                
        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_track_playing_indicators(self):
        """Met à jour récursivement la couleur de tous les titres de morceaux affichés dans l'UI."""
        def update_widget_tree(parent):
            try:
                for child in parent.winfo_children():
                    if hasattr(child, "_track_id") and hasattr(child, "_title_lbl") and child._title_lbl:
                        if child._track_id == self.current_playing_track_id:
                            child._title_lbl.configure(text_color="#1ed760")
                        else:
                            child._title_lbl.configure(text_color="white")
                    update_widget_tree(child)
            except Exception:
                pass
        update_widget_tree(self)
        
        # Rafraîchir les listes virtuelles actives
        def find_and_render_virtual_lists(parent):
            try:
                for child in parent.winfo_children():
                    if child.__class__.__name__ == "VirtualTrackList":
                        child._render()
                    find_and_render_virtual_lists(child)
            except Exception:
                pass
        find_and_render_virtual_lists(self)



    # ─────────────────────────────────────────────── Like / Favoris
    def _toggle_like_current(self):
        if not self.audio_player.current_track:
            return
        track = self._normalize_track(self.audio_player.current_track)
        track_id = track.get("videoId")
        if not track_id:
            return

        self.db.add_track(track)
        is_liked = self.db.toggle_like(track_id)
        self._update_like_button(self.like_btn, is_liked)
        # Synchroniser tous les boutons like visibles pour ce titre
        self._sync_like_state_across_ui(track_id, is_liked)
        self._refresh_sidebar_playlists()

        # Actualiser la vue si nécessaire
        if self.current_view == "playlist" and self.current_data and self.current_data.get("id") == "liked_songs":
            self.show_playlist(self.current_data, False)
            cnt = len(self.db.get_liked_tracks())
            self.current_data["subtitle"] = f"Playlist • {cnt} titres"
            if hasattr(self, "playlist_subtitle_label") and self.playlist_subtitle_label.winfo_exists():
                self.playlist_subtitle_label.configure(text=f"Playlist • {cnt} titres")

    def _toggle_like_row(self, track, track_id, actions_frame):
        if not track_id:
            return
        normalized = self._normalize_track(track)
        self.db.add_track(normalized)
        is_liked = self.db.toggle_like(track_id)

        # Synchronisation globale immédiate (barre + tous les boutons like visibles)
        self._sync_like_state_across_ui(track_id, is_liked)
        self._refresh_sidebar_playlists()

        if self.current_view == "playlist" and self.current_data and self.current_data.get("id") == "liked_songs":
            self.show_playlist(self.current_data, False)
            cnt = len(self.db.get_liked_tracks())
            if self.current_data:
                self.current_data["subtitle"] = f"Playlist \u2022 {cnt} titres"
            if hasattr(self, "playlist_subtitle_label") and self.playlist_subtitle_label.winfo_exists():
                self.playlist_subtitle_label.configure(text=f"Playlist \u2022 {cnt} titres")

    def _sync_like_state_across_ui(self, track_id: str, is_liked: bool):
        """Synchronise en temps réel tous les boutons like enregistrés pour un track_id."""
        if not track_id:
            return
        # Màj cache mémoire
        if is_liked:
            self._cached_liked_ids.add(track_id)
        else:
            self._cached_liked_ids.discard(track_id)

        # 1. Barre de lecture
        if self.audio_player.current_track:
            cur = self._normalize_track(self.audio_player.current_track)
            if cur.get("videoId") == track_id:
                self._update_like_button(self.like_btn, is_liked)

        # 2. Tous les boutons like de la liste principale (via registre)
        for btn in list(self._row_like_buttons.get(track_id, [])):
            try:
                if btn.winfo_exists():
                    self._update_like_button(btn, is_liked)
            except Exception:
                pass

    # ─────────────────────────────────────────────── Modales & Gestion des Playlists
    def _show_add_to_playlist_dialog(self, track):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Ajouter à la playlist")
        dialog.geometry("350x450")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        
        dialog.update_idletasks()
        parent_x = self.winfo_x()
        parent_y = self.winfo_y()
        parent_w = self.winfo_width()
        parent_h = self.winfo_height()
        x = parent_x + (parent_w - 350) // 2
        y = parent_y + (parent_h - 450) // 2
        dialog.geometry(f"+{x}+{y}")
        
        ctk.CTkLabel(dialog, text="Ajouter à une playlist", font=("Arial", 18, "bold")).pack(pady=15)
        
        scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)
        
        playlists = self.db.get_playlists()
        
        if not playlists:
            ctk.CTkLabel(scroll, text="Aucune playlist créée.", text_color="gray").pack(pady=20)
        else:
            for pl in playlists:
                pl_id = pl["id"]
                pl_name = pl["name"]
                track_count = pl.get("track_count", 0)
                
                btn = ctk.CTkButton(
                    scroll, text=f"{pl_name} ({track_count} titres)",
                    fg_color="#272727", hover_color="#3a3a3a",
                    anchor="w", height=45,
                    command=lambda pid=pl_id: self._add_track_to_playlist_and_close(pid, track, dialog)
                )
                btn.pack(fill="x", pady=5)
                 
        create_btn = ctk.CTkButton(
            dialog, text="Créer une nouvelle playlist", fg_color="#1db954", hover_color="#1ed760",
            text_color="black", font=("Arial", 13, "bold"), height=40,
            command=lambda: self._prompt_create_playlist(dialog, track)
        )
        create_btn.pack(fill="x", padx=15, pady=15)

    def _add_track_to_playlist_and_close(self, playlist_id, track, dialog):
        normalized = self._normalize_track(track)
        track_id = normalized.get("videoId")
        if track_id:
            self.db.add_track(normalized)
            self.db.add_to_playlist(playlist_id, track_id)
        dialog.destroy()
        self._refresh_sidebar_playlists()
        if self.current_view == "library":
            self.show_library()

    def _prompt_create_playlist(self, parent_dialog, track_to_add=None):
        prompt = ctk.CTkToplevel(self)
        prompt.title("Nouvelle playlist")
        prompt.geometry("300x180")
        prompt.resizable(False, False)
        prompt.transient(parent_dialog or self)
        prompt.grab_set()

        prompt.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 300) // 2
        y = self.winfo_y() + (self.winfo_height() - 180) // 2
        prompt.geometry(f"+{x}+{y}")

        ctk.CTkLabel(prompt, text="Nom de la playlist :", font=("Arial", 14, "bold")).pack(pady=(15, 5))

        entry = ctk.CTkEntry(prompt, width=240, placeholder_text="Ma playlist...")
        entry.pack(pady=5)
        entry.focus()

        def do_create():
            name = entry.get().strip()
            if name:
                pid = self.db.create_playlist(name)
                if track_to_add:
                    normalized = self._normalize_track(track_to_add)
                    track_id = normalized.get("videoId")
                    if track_id:
                        self.db.add_track(normalized)
                        self.db.add_to_playlist(pid, track_id)
                prompt.destroy()
                if parent_dialog:
                    parent_dialog.destroy()
                # Toujours rafraîchir la sidebar après création
                self._refresh_sidebar_playlists()
                if self.current_view == "library":
                    self.show_library()

        btn_frame = ctk.CTkFrame(prompt, fg_color="transparent")
        btn_frame.pack(pady=15)

        ctk.CTkButton(btn_frame, text="Annuler", width=80, fg_color="transparent", border_width=1, command=prompt.destroy).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Créer", width=80, fg_color="#1db954", hover_color="#1ed760", text_color="black", command=do_create).pack(side="left", padx=5)

        entry.bind("<Return>", lambda e: do_create())

    def _remove_from_playlist(self, playlist_id, track_id):
        """Supprime un morceau d'une playlist custom et rafraîchit la vue."""
        if not playlist_id or not track_id:
            return
        self.db.remove_from_playlist(playlist_id, track_id)
        self._refresh_sidebar_playlists()
        # Recharger la playlist en cours
        if self.current_view == "playlist" and self.current_data and self.current_data.get("id") == playlist_id:
            self.show_playlist(self.current_data, save=False)

    def _delete_playlist_action(self, playlist_id):
        self.db.delete_playlist(playlist_id)
        self._refresh_sidebar_playlists()
        if self.current_view == "playlist" and self.current_data and self.current_data.get("id") == playlist_id:
            self.go_back()
        elif self.current_view == "library":
            self.show_library()

    def _duplicate_playlist_action(self, playlist_id):
        self.db.duplicate_playlist(playlist_id)
        self._refresh_sidebar_playlists()
        if self.current_view == "library":
            self.show_library()

    def _show_playlist_context_menu(self, event, item):
        if not item.get("is_custom_playlist", False):
            return
        
        import tkinter as tk
        menu = tk.Menu(self, tearoff=0, bg="#282828", fg="white", activebackground="#1db954", activeforeground="black", selectcolor="#1db954")
        
        playlist_id = item.get("id")
        
        menu.add_command(
            label="Dupliquer la playlist",
            command=lambda: self._duplicate_playlist_action(playlist_id)
        )
        menu.add_command(
            label="Supprimer la playlist",
            command=lambda: self._delete_playlist_action(playlist_id)
        )
        
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_playlist_options_menu(self, widget, playlist_id):
        import tkinter as tk
        menu = tk.Menu(self, tearoff=0, bg="#282828", fg="white", activebackground="#1db954", activeforeground="black", selectcolor="#1db954")
        
        menu.add_command(
            label="Dupliquer la playlist",
            command=lambda: self._duplicate_playlist_action(playlist_id)
        )
        menu.add_command(
            label="Supprimer la playlist",
            command=lambda: self._delete_playlist_action(playlist_id)
        )
        
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_bar_artist_click(self):
        artist_name = self.bar_artist.cget("text")
        if artist_name and artist_name != "—" and artist_name != "Artiste inconnu":
            self._save_view()
            if hasattr(self, "current_playing_artist_id") and self.current_playing_artist_id:
                self.show_artist({"browseId": self.current_playing_artist_id, "title": artist_name})
            else:
                self.show_artist_by_name(artist_name)

    def _on_row_artist_click(self, track):
        artist_id = track.get("artist_id")
        artist_name = track.get("artist")
        if artist_id:
            self._save_view()
            self.show_artist({"browseId": artist_id, "title": artist_name})
        elif artist_name and artist_name != "Artiste inconnu":
            self._save_view()
            self.show_artist_by_name(artist_name)

    def show_artist_by_name(self, name):
        self.current_view = "artist"
        self.back_btn.pack(side="left", padx=(20, 10), pady=15)
        self._clear_main()
        sf = self._get_scrollable()
        
        loading_lbl = ctk.CTkLabel(sf, text=f"Recherche de {name}...", font=("Arial", 18), text_color="gray")
        loading_lbl.grid(row=0, column=0, pady=100)
        
        threading.Thread(target=lambda: self._search_and_load_artist_thread(name), daemon=True).start()

    def _search_and_load_artist_thread(self, name):
        results = self.api.search(name, filter_type="artists", limit=3)
        if results:
            artist_id = results[0].get("browseId")
            if artist_id:
                artist_details = self.api.get_artist(artist_id)
                if artist_details:
                    self.after(0, lambda: self._display_artist(artist_details))
                    return
        self.after(0, self._display_artist_error)

    def show_artist(self, item, save=True):
        self.current_view = "artist"
        self.current_data = item
        self.back_btn.pack(side="left", padx=(20, 10), pady=15)
        self._clear_main()
        sf = self._get_scrollable()
        loading_lbl = ctk.CTkLabel(sf, text="Chargement de l'artiste...", font=("Arial", 18), text_color="gray")
        loading_lbl.grid(row=0, column=0, pady=100)
        
        channel_id = item.get("browseId")
        if channel_id:
            threading.Thread(target=lambda: self._load_artist_thread(channel_id), daemon=True).start()

    def _load_artist_thread(self, channel_id):
        artist_details = self.api.get_artist(channel_id)
        if artist_details:
            self.after(0, lambda: self._display_artist(artist_details))
        else:
            self.after(0, self._display_artist_error)

    def _display_artist_error(self):
        self._clear_main()
        sf = self._get_scrollable()
        ctk.CTkLabel(sf, text="Impossible de charger les détails de l'artiste.", font=("Arial", 16), text_color="red").grid(row=0, column=0, pady=100)

    def _display_artist(self, details):
        self._clear_main()
        sf = self._get_scrollable()
        sf.grid_columnconfigure(0, weight=1)
        
        # 1. Bannière
        banner_frame = ctk.CTkFrame(self.main_content, height=280, fg_color="#181818", corner_radius=10)
        banner_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        banner_frame.grid_propagate(False)
        
        banner_img_lbl = ctk.CTkLabel(banner_frame, text="", fg_color="#181818")
        banner_img_lbl.place(x=0, y=0, relwidth=1, relheight=1)
        
        banner_info = ctk.CTkFrame(banner_frame, fg_color="transparent")
        banner_info.pack(side="bottom", fill="x", padx=30, pady=30)
        
        name_lbl = ctk.CTkLabel(banner_info, text=details.get("name", "Artiste"), font=("Arial", 42, "bold"), text_color="white", anchor="w")
        name_lbl.pack(fill="x")
        
        sub_text = details.get("subscribers", "")
        if sub_text:
            sub_text = f"👤 {sub_text} abonnés"
        listeners = details.get("monthlyListeners", "")
        if listeners:
            if sub_text:
                sub_text += f" • 🎧 {listeners} auditeurs mensuels"
            else:
                sub_text = f"🎧 {listeners} auditeurs mensuels"
        
        if sub_text:
            ctk.CTkLabel(banner_info, text=sub_text, font=("Arial", 14), text_color="#cccccc", anchor="w").pack(fill="x", pady=(5, 0))
            
        # Charger l'image de la bannière
        thumbnails = details.get("thumbnails", [])
        if thumbnails:
            banner_url = thumbnails[-1].get("url")
            threading.Thread(target=lambda: self._load_artist_banner(banner_url, banner_img_lbl), daemon=True).start()
        else:
            icon_img = _load_icon_ctk_image(200)
            if icon_img:
                banner_img_lbl.configure(image=icon_img, text="")
                self._perm_images.append(icon_img)
            
        # 2. Section Titres Populaires et Biographie (2 colonnes)
        content_frame = ctk.CTkFrame(self.main_content, fg_color="transparent")
        content_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        content_frame.grid_columnconfigure(0, weight=3) # Titres populaires
        content_frame.grid_columnconfigure(1, weight=2) # Biographie
        
        left_col = ctk.CTkFrame(content_frame, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        
        ctk.CTkLabel(left_col, text="Titres populaires", font=("Arial", 22, "bold"), anchor="w").pack(fill="x", pady=(10, 15))
        
        songs_data = details.get("songs", {}).get("results", [])
        if songs_data:
            songs_container = ctk.CTkFrame(left_col, fg_color="transparent")
            songs_container.pack(fill="x")
            for idx, track in enumerate(songs_data[:5]):
                self._add_track_row(track, idx, songs_container, track_list=songs_data[:5])
        else:
            ctk.CTkLabel(left_col, text="Aucun titre populaire disponible.", text_color="gray", anchor="w").pack(fill="x")
            
        desc_text = details.get("description")
        if desc_text:
            right_col = ctk.CTkFrame(content_frame, fg_color="#181818", corner_radius=10)
            right_col.grid(row=0, column=1, sticky="nsew", padx=(20, 0))
            
            ctk.CTkLabel(right_col, text="À propos", font=("Arial", 20, "bold"), anchor="w").pack(fill="x", padx=20, pady=15)
            
            biography_lbl = ctk.CTkLabel(right_col, text=desc_text[:350] + ("..." if len(desc_text) > 350 else ""),
                                         font=("Arial", 13), text_color="#b3b3b3", justify="left", anchor="nw", wraplength=300)
            biography_lbl.pack(fill="both", expand=True, padx=20, pady=(0, 20))
            
        # 3. Section Albums
        albums_data = details.get("albums", {}).get("results", [])
        if albums_data:
            ctk.CTkLabel(self.main_content, text="Albums", font=("Arial", 22, "bold"), anchor="w").grid(row=2, column=0, padx=20, pady=(30, 15), sticky="w")
            
            album_items = []
            for alb in albums_data:
                album_items.append({
                    "id": alb.get("browseId"),
                    "browseId": alb.get("browseId"),
                    "title": alb.get("title"),
                    "subtitle": alb.get("type", "Album"),
                    "thumbnails": alb.get("thumbnails", []),
                    "resultType": "playlist"
                })
            
            grid = ResponsiveCardGrid(self.main_content, album_items[:12], self)
            grid.grid(row=3, column=0, padx=15, pady=5, sticky="ew")

    def _load_artist_banner(self, url, label):
        try:
            r = requests.get(url, timeout=10)
            img = Image.open(io.BytesIO(r.content)).resize((1100, 280), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(1100, 280))
            self.card_images.append(ctk_img)
            self._perm_images.append(ctk_img)
            
            def _update():
                try:
                    if label.winfo_exists():
                        label.configure(image=ctk_img)
                except Exception:
                    pass
            self.after(0, _update)
        except Exception:
            pass

    # ─────────────────────────────────────────────── Lecture
    def _play_track(self, track, track_list=None):
        track = self._normalize_track(track)
        title = track.get("title", "")
        
        print(f"[PLAY] Lecture : {title}")

        # Sauvegarde en base et historique
        self.db.add_track(track)
        track_id = track.get("videoId")
        if track_id:
            self.db.add_to_history(track_id)
            if track_id not in self.recent_played_ids:
                self.recent_played_ids.append(track_id)
                if len(self.recent_played_ids) > 10:
                    self.recent_played_ids.pop(0)

        # Gérer la file d'attente
        if track_list:
            self.original_queue = [self._normalize_track(t) for t in track_list]
            if self.shuffle_mode == "shuffle":
                import random
                others = [t for t in self.original_queue if t.get("videoId") != track.get("videoId")]
                random.shuffle(others)
                self.playback_queue = [track] + others
                self.queue_index = 0
            elif self.shuffle_mode == "intelligent":
                self.playback_queue = [track]
                self.queue_index = 0
                threading.Thread(target=self._load_intelligent_shuffle_suggestions, args=(track,), daemon=True).start()
            else:
                self.playback_queue = list(self.original_queue)
                self.queue_index = 0
                for i, t in enumerate(self.playback_queue):
                    if t.get("videoId") == track.get("videoId"):
                        self.queue_index = i
                        break
        else:
            self.playback_queue = [track]
            self.original_queue = [track]
            self.queue_index = 0
            if self.shuffle_mode == "intelligent":
                threading.Thread(target=self._load_intelligent_shuffle_suggestions, args=(track,), daemon=True).start()

        # Lancement audio (threading interne à AudioPlayer)
        self.audio_player.play_track(track)
        
        # Prefetch de la piste suivante
        self._prefetch_next_track()

    def _load_intelligent_shuffle_suggestions(self, seed_track, auto_play_next=False):
        try:
            print("[Intelligent Shuffle] Début de la génération de recommandations...")
            history = self.db.get_history(limit=5)
            if not history:
                history = [seed_track]
            
            recent_artists = {t.get("artist") for t in history if t.get("artist") and t.get("artist") != "Artiste inconnu"}
            recent_ids = {t.get("id") or t.get("videoId") for t in history}
            recent_ids.add(seed_track.get("videoId"))
            
            candidates = []
            for t in history[:2]:
                tid = t.get("videoId") or t.get("id")
                if not tid: continue
                res = self.api.get_watch_playlist(tid, limit=20)
                if res and "tracks" in res:
                    for track_candidate in res["tracks"]:
                        candidates.append(track_candidate)
            
            filtered = []
            seen_cands = set()
            for c in candidates:
                norm = self._normalize_track(c)
                cid = norm.get("videoId")
                if not cid or cid in recent_ids or cid in seen_cands:
                    continue
                
                c_artist = norm.get("artist")
                if c_artist in recent_artists:
                    continue
                    
                seen_cands.add(cid)
                filtered.append(norm)
            
            if len(filtered) < 10:
                for c in candidates:
                    norm = self._normalize_track(c)
                    cid = norm.get("videoId")
                    if cid and cid not in recent_ids and cid not in seen_cands:
                        seen_cands.add(cid)
                        filtered.append(norm)

            if not filtered:
                res = self.api.get_watch_playlist(seed_track.get("videoId"), limit=25)
                if res and "tracks" in res:
                    for c in res["tracks"]:
                        norm = self._normalize_track(c)
                        cid = norm.get("videoId")
                        if cid and cid != seed_track.get("videoId"):
                            filtered.append(norm)

            import random
            random.shuffle(filtered)
            
            self.playback_queue = [seed_track] + filtered
            self.queue_index = 0
            print(f"[Intelligent Shuffle] Génération terminée. {len(filtered)} recommandations ajoutées.")
            
            if auto_play_next and len(self.playback_queue) > 1:
                self.queue_index = 1
                self.after(0, lambda: self._play_track(self.playback_queue[1], self.playback_queue))
        except Exception as e:
            print(f"[ERROR] Intelligent Shuffle: {e}")

    # ─────────────────────────────────────────────── Fermeture
    def on_closing(self):
        # Supprimer toutes les miniatures du cache (elles seront retéléchargées au prochain lancement)
        try:
            self.cache_manager.clear_thumbnails()
        except Exception as e:
            print(f"[on_closing] Erreur nettoyage thumbnails: {e}")
        if hasattr(self, 'video_loader'):
            self.video_loader.running = False
        if hasattr(self, 'cap'):
            self.cap.release()
        if hasattr(self, 'bg_window'):
            try:
                self.bg_window.destroy()
            except Exception:
                pass
        self.audio_player.cleanup()
        self.db.close()
        self.destroy()


if __name__ == "__main__":
    app = RscrapApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()

