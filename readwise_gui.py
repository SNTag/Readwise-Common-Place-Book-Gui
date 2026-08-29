#!/usr/bin/env python3
"""
Readwise Obsidian sync — parses quote notes from a folder and sends them
to Readwise. Files already tagged 'readwise' are skipped. After a
successful upload the tag is added to the file so it won't be re-sent.

Requires: pip install requests keyring
"""

LAST_MODIFIED = "2026-08-29"

# ── User configuration ────────────────────────────────────────────────────────
# Adjust OBSIDIAN_FOLDER before running. The token is stored securely via
# your OS keychain (Windows Credential Manager / macOS Keychain / Linux
# Secret Service) — no need to put it in a file.

OBSIDIAN_FOLDER = r"C:\Users\YourName\Documents\Obsidian\Vault\Quotes"

# Tag written into a file after it has been successfully sent to Readwise.
SENT_TAG = "readwise"

# Default title when a note's 'book title' field is blank.
DEFAULT_TITLE = "CommonPlace Book"

# Keychain service name used to store/retrieve the API token.
KEYCHAIN_SERVICE = "readwise-gui"
KEYCHAIN_USER    = "api-token"

# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

API_URL = "https://readwise.io/api/v2/highlights/"


# ── Token ─────────────────────────────────────────────────────────────────────

def load_token():
    # 1. Environment variable (overrides everything)
    t = os.environ.get("READWISE_TOKEN")
    if t:
        return t.strip()
    # 2. OS keychain
    if _KEYRING_AVAILABLE:
        t = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_USER)
        if t:
            return t.strip()
    return ""

def save_token(token):
    token = token.strip()
    if _KEYRING_AVAILABLE:
        keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_USER, token)
    else:
        # Fallback: plain file (Windows path, no chmod)
        path = os.path.join(os.path.expanduser("~"), ".config", "readwise", "token")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(token)


# ── YAML frontmatter helpers ──────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_TAG_LINE_RE    = re.compile(r"^tags\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)


def parse_frontmatter(text):
    """Return a dict of lowercase key → value from YAML frontmatter, or {}."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip().lower()] = val.strip()
    return result


def get_tags(text):
    """Return the tags list from frontmatter as lowercase strings."""
    fm = parse_frontmatter(text)
    raw = fm.get("tags", "")
    if not raw:
        return []
    return [t.strip().strip('"').lower() for t in raw.split() if t.strip()]


def add_sent_tag(filepath, text):
    """Append SENT_TAG to the tags line in frontmatter and rewrite the file."""
    def replacer(m):
        existing = m.group(1).strip()
        return f"tags: {existing} {SENT_TAG}" if existing else f"tags: {SENT_TAG}"

    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        return

    if _TAG_LINE_RE.search(fm_match.group(1)):
        new_fm = _TAG_LINE_RE.sub(replacer, fm_match.group(1))
    else:
        new_fm = fm_match.group(1) + f"\ntags: {SENT_TAG}"

    new_text = text[:fm_match.start(1)] + new_fm + text[fm_match.end(1):]
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_text)


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


# ── File scanning ─────────────────────────────────────────────────────────────

def scan_folder(folder):
    """
    Return a list of dicts for every .md file that:
      - has a non-empty 'quote' field in its frontmatter
      - does NOT already have SENT_TAG in its tags
    Each dict: {path, filename, title, author, quote}
    """
    pending = []
    if not os.path.isdir(folder):
        return pending
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(folder, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue

        if SENT_TAG in get_tags(text):
            continue

        fm = parse_frontmatter(text)
        quote = fm.get("quote", "").strip()
        if not quote:
            continue

        pending.append({
            "path":     fpath,
            "filename": fname,
            "title":    fm.get("book title", "").strip() or DEFAULT_TITLE,
            "author":   fm.get("author", "").strip() or None,
            "quote":    quote,
        })
    return pending


# ── Settings dialog ───────────────────────────────────────────────────────────

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, folder, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._on_save = on_save

        p = 10
        f = ttk.Frame(self, padding=p)
        f.grid(sticky="nsew")
        f.columnconfigure(1, weight=1)

        # Folder
        ttk.Label(f, text="Obsidian folder").grid(row=0, column=0, sticky="w", padx=(0, p), pady=4)
        self._folder_var = tk.StringVar(value=folder)
        ttk.Entry(f, textvariable=self._folder_var, width=48).grid(row=0, column=1, sticky="ew", pady=4)

        # Token
        ttk.Label(f, text="API token").grid(row=1, column=0, sticky="w", padx=(0, p), pady=4)
        self._token_var = tk.StringVar(value=load_token())
        token_entry = ttk.Entry(f, textvariable=self._token_var, show="•", width=48)
        token_entry.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(f, text="Show",
                   command=lambda: token_entry.configure(
                       show="" if token_entry.cget("show") == "•" else "•")
                   ).grid(row=1, column=2, padx=(4, 0))

        storage = "Windows Credential Manager" if _KEYRING_AVAILABLE else "plain file (~/.config/readwise/token)"
        ttk.Label(f, text=f"Token stored in: {storage}", foreground="grey").grid(
            row=2, column=1, sticky="w")

        link = tk.Label(f, text="Get token →", fg="blue", cursor="hand2",
                        font=("TkDefaultFont", 9, "underline"))
        link.grid(row=3, column=1, sticky="w", pady=(2, p))
        link.bind("<Button-1>", lambda _: __import__("webbrowser").open("https://readwise.io/access_token"))

        bf = ttk.Frame(f)
        bf.grid(row=4, column=0, columnspan=3, sticky="e")
        ttk.Button(bf, text="Save",   command=self._save).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=self.destroy).grid(row=0, column=1)

        self.bind("<Return>", lambda _: self._save())
        self.bind("<Escape>", lambda _: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _save(self):
        token = self._token_var.get().strip()
        if token:
            save_token(token)
        self._on_save(self._folder_var.get().strip())
        self.destroy()


# ── Confirmation dialog ───────────────────────────────────────────────────────

class ConfirmDialog(tk.Toplevel):
    """Shows pending quotes and lets the user deselect any before sending."""

    def __init__(self, parent, pending):
        super().__init__(parent)
        self.title("Confirm upload")
        self.resizable(True, True)
        self.minsize(640, 400)
        self.transient(parent)
        self.grab_set()
        self.result = None  # list of approved items, or None if cancelled

        p = 10
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        ttk.Label(self, text="Uncheck any notes you do NOT want to send, then click Send.",
                  padding=(p, p, p, 0)).grid(row=0, column=0, sticky="w")

        frame = ttk.Frame(self, padding=p)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        cols = ("send", "file", "book title", "author", "quote")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="none")
        widths = {"send": 40, "file": 160, "book title": 140, "author": 110, "quote": 240}
        for col in cols:
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col,  width=widths[col], anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(frame, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self._checks = {}
        for item in pending:
            var = tk.BooleanVar(value=True)
            iid = self.tree.insert("", "end", values=(
                "✓",
                item["filename"],
                item["title"],
                item["author"] or "",
                item["quote"][:60] + ("…" if len(item["quote"]) > 60 else ""),
            ))
            self._checks[iid] = (var, item)
        self.tree.bind("<Button-1>", self._toggle_row)

        bf = ttk.Frame(self, padding=(p, 0, p, p))
        bf.grid(row=2, column=0, sticky="e")
        ttk.Button(bf, text="Send",   command=self._confirm).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=self.destroy).grid(row=0, column=1)

        self.bind("<Return>", lambda _: self._confirm())
        self.bind("<Escape>", lambda _: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _toggle_row(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        var, item = self._checks[iid]
        var.set(not var.get())
        tick = "✓" if var.get() else "✗"
        vals = list(self.tree.item(iid, "values"))
        vals[0] = tick
        self.tree.item(iid, values=vals)

    def _confirm(self):
        self.result = [item for var, item in self._checks.values() if var.get()]
        self.destroy()


# ── Main window ───────────────────────────────────────────────────────────────

class App(tk.Tk):
    PAD = 10

    def __init__(self):
        super().__init__()
        self.title("Readwise — Obsidian Sync")
        self.resizable(True, True)
        self.minsize(560, 480)
        self._folder = OBSIDIAN_FOLDER
        self._pending = []
        self._build()
        self._scan()

    def _build(self):
        p = self.PAD
        self.columnconfigure(0, weight=1)

        # Folder + controls row
        top = ttk.Frame(self, padding=(p, p, p, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Folder:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._folder_label = ttk.Label(top, text=self._folder, foreground="grey", anchor="w")
        self._folder_label.grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="⚙ Settings", command=self._open_settings).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(top, text="↺ Scan",     command=self._scan).grid(row=0, column=3, padx=(6, 0))

        # Pending files list
        lf = ttk.LabelFrame(self, text="Pending notes", padding=p)
        lf.grid(row=1, column=0, sticky="nsew", padx=p, pady=(p, 0))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        cols = ("file", "book title", "author", "quote")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", selectmode="extended")
        widths = {"file": 160, "book title": 140, "author": 110, "quote": 260}
        for col in cols:
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col,  width=widths[col], anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        # Log
        logf = ttk.LabelFrame(self, text="Log", padding=p)
        logf.grid(row=2, column=0, sticky="ew", padx=p, pady=(p, 0))
        logf.columnconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(logf, height=5, state="disabled", wrap="word")
        self.log.grid(row=0, column=0, sticky="ew")

        # Bottom buttons
        bf = ttk.Frame(self, padding=(p, p // 2, p, p))
        bf.grid(row=3, column=0, sticky="ew")
        bf.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar()
        ttk.Label(bf, textvariable=self.status_var, foreground="grey").grid(row=0, column=0, sticky="w")
        ttk.Button(bf, text="Send all →",    command=self._send_all).grid(row=0, column=1)
        ttk.Button(bf, text="Send selected", command=self._send_selected).grid(row=0, column=2, padx=(6, 0))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _scan(self):
        self._pending = scan_folder(self._folder)
        self.tree.delete(*self.tree.get_children())
        for item in self._pending:
            self.tree.insert("", "end", values=(
                item["filename"],
                item["title"],
                item["author"] or "",
                item["quote"][:80] + ("…" if len(item["quote"]) > 80 else ""),
            ))
        n = len(self._pending)
        self.status_var.set(f"{n} note(s) pending.")
        self._log(f"Scanned '{self._folder}': {n} pending.")

    def _open_settings(self):
        def on_save(new_folder):
            self._folder = new_folder
            self._folder_label.configure(text=new_folder)
            self.status_var.set("Settings saved.")
            self._scan()
        SettingsDialog(self, self._folder, on_save)

    def _confirm_and_send(self, items):
        if not items:
            messagebox.showinfo("Nothing to send", "No pending notes to send.")
            return
        token = load_token()
        if not token:
            messagebox.showwarning("No token",
                "No API token found.\nOpen ⚙ Settings and enter your Readwise token.")
            return

        dlg = ConfirmDialog(self, items)
        self.wait_window(dlg)
        approved = dlg.result
        if approved is None or not approved:
            self._log("Upload cancelled.")
            return

        sent = 0
        for item in approved:
            try:
                result = post_highlight(token, item["quote"], item["title"], item["author"])
                hl_id  = result[0].get("id", "?") if result else "?"
                with open(item["path"], encoding="utf-8") as f:
                    text = f.read()
                add_sent_tag(item["path"], text)
                self._log(f"✓ Sent '{item['title']}' — {item['filename']} (id {hl_id})")
                sent += 1
            except requests.HTTPError as e:
                self._log(f"✗ API error for '{item['filename']}': {e.response.status_code} {e.response.text[:80]}")
            except requests.ConnectionError:
                self._log(f"✗ Connection error — '{item['filename']}' not sent.")

        self.status_var.set(f"Done: {sent}/{len(approved)} sent.")
        self._scan()

    def _send_all(self):
        self._confirm_and_send(self._pending)

    def _send_selected(self):
        indices = [self.tree.index(iid) for iid in self.tree.selection()]
        self._confirm_and_send([self._pending[i] for i in indices])


if __name__ == "__main__":
    app = App()
    app.mainloop()
