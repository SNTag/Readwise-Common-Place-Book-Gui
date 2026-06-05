#!/usr/bin/env python3
"""
Readwise quote capture — cross-platform GUI (tkinter).
Requires: pip install requests
"""

import os
import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox
import requests

API_URL       = "https://readwise.io/api/v2/highlights/"
TOKEN_FILE    = os.path.join(os.path.expanduser("~"), ".config", "readwise", "token")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".config", "readwise", "settings.json")

DEFAULT_SETTINGS = {
    "default_title":  "",
    "default_author": "",
    "default_tags":   "",
}


# ── Token helpers ─────────────────────────────────────────────────────────────

def load_token():
    t = os.environ.get("READWISE_TOKEN")
    if t:
        return t.strip()
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    return ""

def save_token(token):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(token.strip())
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass  # Windows doesn't support chmod


# ── Settings helpers ──────────────────────────────────────────────────────────

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                data = json.load(f)
            return {**DEFAULT_SETTINGS, **data}
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ── API ───────────────────────────────────────────────────────────────────────

def post_highlight(token, text, title=None, author=None, note=None, tags=None):
    hl = {"text": text}
    if title:  hl["title"]  = title
    if author: hl["author"] = author
    if note:   hl["note"]   = note
    if tags:
        hl["tags"] = [{"name": t.strip().lstrip("#")} for t in tags if t.strip()]
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Token {token}"},
        json={"highlights": [hl]},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── Settings dialog ───────────────────────────────────────────────────────────

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._on_save = on_save

        p = 10
        frame = ttk.Frame(self, padding=p)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Defaults are used when a field is left blank.",
                  foreground="grey").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, p))

        fields = [
            ("Default title",  "default_title"),
            ("Default author", "default_author"),
            ("Default tags",   "default_tags"),
        ]
        self._vars = {}
        for i, (label, key) in enumerate(fields, start=1):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, p))
            var = tk.StringVar(value=settings.get(key, ""))
            ttk.Entry(frame, textvariable=var, width=36).grid(row=i, column=1, sticky="ew", pady=3)
            self._vars[key] = var

        ttk.Label(frame, text="Tags: space-separated  e.g. stoicism writing",
                  foreground="grey").grid(row=4, column=1, sticky="w")

        bf = ttk.Frame(frame)
        bf.grid(row=5, column=0, columnspan=2, sticky="e", pady=(p, 0))
        ttk.Button(bf, text="Save", command=self._save).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=self.destroy).grid(row=0, column=1)

        self.bind("<Return>", lambda _: self._save())
        self.bind("<Escape>", lambda _: self.destroy())

        # Center over parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _save(self):
        settings = {key: var.get().strip() for key, var in self._vars.items()}
        save_settings(settings)
        self._on_save(settings)
        self.destroy()


# ── Main window ───────────────────────────────────────────────────────────────

class App(tk.Tk):
    PAD = 10

    def __init__(self):
        super().__init__()
        self.title("Readwise — Add Quote")
        self.resizable(True, True)
        self.minsize(480, 520)
        self._settings = load_settings()
        self._build()
        self._load_token()
        self._apply_defaults()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        p = self.PAD
        self.columnconfigure(0, weight=1)

        # Token row
        tf = ttk.LabelFrame(self, text="API Token", padding=p)
        tf.grid(row=0, column=0, sticky="ew", padx=p, pady=(p, 0))
        tf.columnconfigure(0, weight=1)

        self.token_var = tk.StringVar()
        token_entry = ttk.Entry(tf, textvariable=self.token_var, show="•", width=50)
        token_entry.grid(row=0, column=0, sticky="ew", padx=(0, p))

        ttk.Button(tf, text="Save", command=self._save_token).grid(row=0, column=1)
        ttk.Button(tf, text="Show", command=lambda: self._toggle_show(token_entry)).grid(row=0, column=2, padx=(4, 0))

        link = tk.Label(tf, text="Get token →", fg="blue", cursor="hand2",
                        font=("TkDefaultFont", 9, "underline"))
        link.grid(row=1, column=0, sticky="w", pady=(4, 0))
        link.bind("<Button-1>", lambda _: self._open_url("https://readwise.io/access_token"))

        # Quote
        qf = ttk.LabelFrame(self, text="Quote *", padding=p)
        qf.grid(row=1, column=0, sticky="nsew", padx=p, pady=(p, 0))
        qf.columnconfigure(0, weight=1)
        qf.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.quote_text = tk.Text(qf, height=8, wrap="word", undo=True)
        self.quote_text.grid(row=0, column=0, sticky="nsew")
        qs = ttk.Scrollbar(qf, command=self.quote_text.yview)
        qs.grid(row=0, column=1, sticky="ns")
        self.quote_text.configure(yscrollcommand=qs.set)

        # Metadata
        mf = ttk.LabelFrame(self, text="Source (optional)", padding=p)
        mf.grid(row=2, column=0, sticky="ew", padx=p, pady=(p, 0))
        mf.columnconfigure(1, weight=1)

        for i, lbl in enumerate(("Title", "Author", "Tags")):
            ttk.Label(mf, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
        self.title_var  = tk.StringVar()
        self.author_var = tk.StringVar()
        self.tags_var   = tk.StringVar()
        ttk.Entry(mf, textvariable=self.title_var).grid( row=0, column=1, sticky="ew", padx=(p,0))
        ttk.Entry(mf, textvariable=self.author_var).grid(row=1, column=1, sticky="ew", padx=(p,0))
        ttk.Entry(mf, textvariable=self.tags_var).grid(  row=2, column=1, sticky="ew", padx=(p,0))
        ttk.Label(mf, text="space-separated  e.g. stoicism writing",
                  foreground="grey").grid(row=3, column=1, sticky="w", padx=(p,0))

        # Note
        nf = ttk.LabelFrame(self, text="Your note (optional)", padding=p)
        nf.grid(row=3, column=0, sticky="ew", padx=p, pady=(p, 0))
        nf.columnconfigure(0, weight=1)

        self.note_text = tk.Text(nf, height=3, wrap="word", undo=True)
        self.note_text.grid(row=0, column=0, sticky="ew")
        ns = ttk.Scrollbar(nf, command=self.note_text.yview)
        ns.grid(row=0, column=1, sticky="ns")
        self.note_text.configure(yscrollcommand=ns.set)

        # Status + submit
        bf = ttk.Frame(self, padding=(p, p//2, p, p))
        bf.grid(row=4, column=0, sticky="ew")
        bf.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar()
        ttk.Label(bf, textvariable=self.status_var, foreground="grey").grid(
            row=0, column=0, sticky="w")

        ttk.Button(bf, text="⚙ Settings", command=self._open_settings).grid(row=0, column=1, padx=(0, 6))
        self.submit_btn = ttk.Button(bf, text="Submit →", command=self._submit)
        self.submit_btn.grid(row=0, column=2)
        ttk.Button(bf, text="Clear", command=self._clear).grid(
            row=0, column=3, padx=(6, 0))

        self.bind("<Return>",    lambda e: None)           # don't submit on Enter in text box
        self.bind("<Control-Return>", lambda e: self._submit())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_token(self):
        t = load_token()
        if t:
            self.token_var.set(t)

    def _save_token(self):
        t = self.token_var.get().strip()
        if not t:
            messagebox.showwarning("No token", "Paste your token first.")
            return
        save_token(t)
        self.status_var.set("Token saved.")

    def _toggle_show(self, entry):
        entry.configure(show="" if entry.cget("show") == "•" else "•")

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def _apply_defaults(self):
        self.title_var.set(self._settings.get("default_title", ""))
        self.author_var.set(self._settings.get("default_author", ""))
        self.tags_var.set(self._settings.get("default_tags", ""))

    def _open_settings(self):
        def on_save(new_settings):
            self._settings = new_settings
            self.status_var.set("Settings saved.")

        SettingsDialog(self, self._settings, on_save)

    def _clear(self):
        self.quote_text.delete("1.0", "end")
        self.note_text.delete("1.0", "end")
        self.status_var.set("")
        self._apply_defaults()
        self.quote_text.focus()

    # ── Submit ────────────────────────────────────────────────────────────────

    def _submit(self):
        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("No token", "Enter your Readwise API token first.")
            return

        text = self.quote_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Empty quote", "The quote field cannot be empty.")
            return

        title  = self.title_var.get().strip()  or None
        author = self.author_var.get().strip()  or None
        note   = self.note_text.get("1.0", "end").strip() or None
        tags   = self.tags_var.get().split()   or None

        self.status_var.set("Sending…")
        self.submit_btn.state(["disabled"])
        self.update()

        try:
            result = post_highlight(token, text, title, author, note, tags)
            hl_id  = result[0].get("id", "?") if result else "?"
            dest   = title or "Quotes"
            self.status_var.set(f"✓ Saved to '{dest}'  (id {hl_id})")
            self._clear()
        except requests.HTTPError as e:
            messagebox.showerror("API error",
                f"Status {e.response.status_code}:\n{e.response.text}")
            self.status_var.set("Error — not saved.")
        except requests.ConnectionError:
            messagebox.showerror("Connection error",
                "Could not reach Readwise.\nCheck your internet connection.")
            self.status_var.set("Error — not saved.")
        finally:
            self.submit_btn.state(["!disabled"])


if __name__ == "__main__":
    app = App()
    app.mainloop()
