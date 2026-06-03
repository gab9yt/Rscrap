import tkinter as tk
import threading
import requests
import io
from collections import OrderedDict
from PIL import Image
import customtkinter as ctk


class VirtualTrackList(ctk.CTkFrame):
    """
    Liste à défilement virtuel : pool fixe de ~30 slots recyclés.
    Évite la création de milliers de widgets, scroll fluide et mémoire maîtrisée.
    """

    ROW_HEIGHT = 68
    POOL_SIZE = 28
    BUFFER = 4

    def __init__(self, parent, tracks, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.tracks = list(tracks)
        self.total = len(self.tracks)
        self._scroll_px = 0
        self._view_h = 800
        self._container_w = 800
        self._max_scroll = 0
        self._thumb_cache = OrderedDict()
        self._thumb_loading = set()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        self.scrollbar = ctk.CTkScrollbar(self, command=self._on_scrollbar)
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.slots = []
        n = min(self.POOL_SIZE, max(self.total, 1))
        for _ in range(n):
            slot = self._create_slot()
            self.slots.append(slot)

        self.bind("<Configure>", self._on_resize)
        self.bind("<MouseWheel>", self._on_wheel)
        self._update_metrics()
        self._render()
        self._deferred_rid = self.after(100, lambda: self._update_metrics() or self._render())

    def _on_resize(self, event):
        self._container_w = event.width - self.scrollbar.winfo_width()
        self._update_metrics()
        self._render()

    def _on_wheel(self, event):
        self._scroll_px -= event.delta
        self._scroll_px = max(0, min(self._scroll_px, self._max_scroll))
        self._update_scrollbar()
        self._render()

    def _on_scrollbar(self, *args):
        if args[0] == "moveto":
            frac = float(args[1])
            self._scroll_px = int(frac * self._max_scroll) if self._max_scroll > 0 else 0
        elif args[0] == "scroll":
            amount = int(args[1])
            what = args[2]
            step = self.ROW_HEIGHT if what == "units" else self._view_h
            self._scroll_px += amount * step
            self._scroll_px = max(0, min(self._scroll_px, self._max_scroll))
        self._update_scrollbar()
        self._render()

    def _update_metrics(self):
        h = self.winfo_height()
        if h >= 50:
            self._view_h = h
        total_h = self.total * self.ROW_HEIGHT
        self._max_scroll = max(0, total_h - self._view_h)
        self._scroll_px = min(self._scroll_px, self._max_scroll)

    def _update_scrollbar(self):
        if self._max_scroll <= 0 or self.total == 0:
            self.scrollbar.set(0.0, 1.0)
        else:
            total_h = self.total * self.ROW_HEIGHT
            frac = self._scroll_px / self._max_scroll
            view_frac = self._view_h / total_h
            self.scrollbar.set(frac, min(1.0, frac + view_frac))

    def _create_slot(self):
        frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=5,
                             height=self.ROW_HEIGHT)
        frame.pack_propagate(False)

        # Miniature
        tf = ctk.CTkFrame(frame, width=50, height=50, corner_radius=3,
                          fg_color="#272727")
        tf.pack(side="left", padx=(10, 15), pady=9)
        img = ctk.CTkLabel(tf, text="", width=50, height=50)
        img.pack()

        # Infos
        info = ctk.CTkFrame(frame, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)
        title = ctk.CTkLabel(info, text="", font=("Arial", 13, "bold"),
                             anchor="w")
        title.pack(fill="x", pady=(10, 2))
        artist = ctk.CTkLabel(info, text="", text_color="gray", anchor="w",
                              font=("Arial", 11))
        artist.pack(fill="x")

        # Actions
        acts = ctk.CTkFrame(frame, fg_color="transparent")
        acts.pack(side="right", padx=10, fill="y")

        like = ctk.CTkButton(
            acts, text="+", width=24, height=24, corner_radius=12,
            fg_color="transparent", hover_color="#272727",
            text_color="gray", font=("Arial", 12, "bold"),
            border_width=1, border_color="gray")
        like.pack(side="left", padx=5)

        add = ctk.CTkButton(acts, text="➕", width=30, height=45,
                            fg_color="transparent", hover_color="#272727",
                            text_color="gray", font=("Arial", 14))
        add.pack(side="left", padx=5)

        frame._data = None
        frame._track_id = None
        frame._track_idx = -1
        frame._thumb_url = None
        frame._widgets = {
            "img": img, "title": title, "artist": artist,
            "like": like, "add": add, "thumb_frame": tf, "acts": acts,
        }

        # Clic = lecture (lié une seule fois, lit frame._data)
        for w in (frame, img, title, info, tf):
            w.bind("<Button-1>", lambda e, f=frame: self._play_slot(f))

        # Artiste (lié une seule fois, lit frame._data)
        artist.bind("<Button-1>", lambda e, f=frame: self._artist_click(f))

        # Hover globalisé récursif
        self.app._setup_hover_highlight(frame, hover_color="#181818")

        # Molette → scroll (bind sur tous les widgets enfants pour capturer l'événement)
        for w in (frame, img, title, info, tf, like, add, acts):
            w.bind("<MouseWheel>", self._on_wheel)

        frame.place_forget()
        return frame

    def _play_slot(self, slot):
        if slot._data:
            self.app._play_track(slot._data, self.tracks)

    def _artist_click(self, slot):
        if slot._data:
            self.app._on_row_artist_click(slot._data)

    def _render(self):
        if not self.total:
            return
        first_idx = max(0, self._scroll_px // self.ROW_HEIGHT - self.BUFFER)
        last_idx = min(self.total - 1,
                       (self._scroll_px + self._view_h) // self.ROW_HEIGHT + self.BUFFER)

        for i, slot in enumerate(self.slots):
            track_idx = first_idx + i
            if track_idx <= last_idx and track_idx < self.total:
                if slot._track_idx == track_idx:
                    continue  # déjà à jour
                y = track_idx * self.ROW_HEIGHT - self._scroll_px
                # Contenu AVANT position → pas de flash de données périmées
                self._update_slot(slot, track_idx)
                slot.configure(width=self._container_w)
                slot.place(x=0, y=y)
            else:
                slot.place_forget()
                slot._track_idx = -1
                slot._thumb_url = None

    def _update_slot(self, slot, track_idx):
        slot._track_idx = track_idx
        track = self.tracks[track_idx]
        norm = self.app._normalize_track(track)
        slot._data = norm
        slot._track_id = norm.get("videoId")
        w = slot._widgets

        # Titre
        t = norm.get("title", "Titre")
        title_color = "#1ed760" if slot._track_id and slot._track_id == self.app.current_playing_track_id else "white"
        w["title"].configure(text=t[:60] + ("..." if len(t) > 60 else ""), text_color=title_color)

        # Artiste
        a = norm.get("artist", "")
        w["artist"].configure(text=a[:60] + ("..." if len(a) > 60 else ""),
                              cursor="hand2" if a and a not in (
                                  "Artiste inconnu", "—", "") else "")

        # Thumbnail
        thumbs = norm.get("thumbnails", [])
        url = self.app._get_best_thumbnail_url(thumbs, 50)
        slot._thumb_url = url
        w["img"].configure(image=None, text="")
        if url:
            if url in self._thumb_cache:
                w["img"].configure(image=self._thumb_cache[url], text="")
                self._thumb_cache.move_to_end(url)
            elif url not in self._thumb_loading:
                self._thumb_loading.add(url)
                threading.Thread(target=self._load_thumb,
                                 args=(url,), daemon=True).start()

        # Like
        tid = norm.get("videoId")
        liked = self.app.db.is_liked(tid) if tid else False
        self._like_btn(w["like"], liked)
        w["like"].configure(command=lambda t=tid, f=slot: self._toggle_like(t, f))

        # Add to playlist
        w["add"].configure(command=lambda n=norm: self.app._show_add_to_playlist_dialog(n))

    def _like_btn(self, btn, liked):
        if liked:
            btn.configure(text="✓", fg_color="#1ed760", text_color="black",
                          hover_color="#1db954", border_width=0)
        else:
            btn.configure(text="+", fg_color="transparent", text_color="gray",
                          hover_color="#272727", border_width=1,
                          border_color="gray")

    def _toggle_like(self, track_id, slot):
        if not track_id:
            return
        if slot._data:
            self.app.db.add_track(slot._data)
        liked = self.app.db.toggle_like(track_id)
        self._like_btn(slot._widgets["like"], liked)
        self.app._sync_like_state_across_ui(track_id, liked)
        self.app._refresh_sidebar_playlists()
        if (self.app.current_view == "playlist"
                and self.app.current_data
                and self.app.current_data.get("id") == "liked_songs"
                and not liked):
            self.app.show_playlist(self.app.current_data, False)

    def _load_thumb(self, url):
        import os
        try:
            cache_path = self.app.cache_manager.get_thumbnail_cache_path(url)
            if os.path.exists(cache_path):
                img = Image.open(cache_path).resize((50, 50), Image.Resampling.LANCZOS)
            else:
                r = requests.get(url, timeout=10)
                img = Image.open(io.BytesIO(r.content)).resize((50, 50), Image.Resampling.LANCZOS)
                try:
                    img.save(cache_path, "PNG")
                except Exception:
                    pass

            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(50, 50))
            while len(self._thumb_cache) > 200:
                self._thumb_cache.popitem(last=False)
            self._thumb_cache[url] = ctk_img
            self.app.after(0, lambda: self._apply_thumb(url, ctk_img))
        except Exception:
            pass
        finally:
            self._thumb_loading.discard(url)

    def _apply_thumb(self, url, ctk_img):
        for s in self.slots:
            if s._thumb_url == url and s._track_idx >= 0:
                try:
                    s._widgets["img"].configure(image=ctk_img, text="")
                except Exception:
                    pass

    def cleanup(self):
        """Libère les ressources (appelé lors du changement de vue)."""
        self.tracks = []
        self._thumb_cache.clear()
        self._thumb_loading.clear()
        try:
            self.after_cancel(self._deferred_rid)
        except Exception:
            pass
        for s in self.slots:
            s.place_forget()
