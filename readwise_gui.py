#!/usr/bin/env python3
"""
Readwise Obsidian sync — parses quote notes from a folder and sends them
to Readwise. Files already tagged 'readwise' are skipped. After a
successful upload the tag is added to the file so it won't be re-sent.

Requires: pip install requests
"""

LAST_MODIFIED = "2026-08-17"

# ── User configuration ────────────────────────────────────────────────────────
# Adjust these two paths before running.

OBSIDIAN_FOLDER = r"C:\Users\YourName\Documents\Obsidian\Vault\Quotes"
TOKEN_FILE      = r"C:\Users\YourName\.config\readwise\token"

# On Linux / macOS you can use forward slashes and ~ expansion, e.g.:
#   OBSIDIAN_FOLDER = os.path.expanduser("~/Documents/Obsidian/Quotes")
#   TOKEN_FILE      = os.path.expanduser("~/.config/readwise/token")

# Tag written into a file after it has been successfully sent to Readwise.
SENT_TAG = "readwise"

# Default title used when a note has no title field (or it is blank).
DEFAULT_TITLE = "CommonPlace Book"

# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests

API_URL = "https://readwise.io/api/v2/highlights/"


# ── Token ─────────────────────────────────────────────────────────────────────

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
        pass  # not supported on Windows


# ── YAML frontmatter helpers ──────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_TAG_LINE_RE    = re.compile(r"^tags\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)


def parse_frontmatter(text):
    """Return a dict of key/value pairs from YAML frontmatter, or {}."""
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
    # Support both inline (tags: foo bar) and quoted forms
    return [t.strip().strip('"').lower() for t in raw.split() if t.strip()]


def add_sent_tag(filepath, text):
    """Append SENT_TAG to the tags line in frontmatter and rewrite the file."""
    def replacer(m):
        existing = m.group(1).strip()
        if existing:
            return f"tags: {existing} {SENT_TAG}"
        return f"tags: {SENT_TAG}"

    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        return  # no frontmatter to update

    if _TAG_LINE_RE.search(fm_match.group(1)):
        # tags line exists — append to it
        new_fm = _TAG_LINE_RE.sub(replacer, fm_match.group(1))
    else:
        # no tags line — add one
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
      - does NOT already have the SENT_TAG tag
    Each dict: {path, title, author, quote}
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
            "path":   fpath,
            "title":  fm.get("title", "").strip() or DEFAULT_TITLE,
            "author": fm.get("author", "").strip() or None,
            "quote":  quote,
        })
    return pending


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    PAD = 10

    def __init__(self):
        super().__init__()
        self.title("Readwise — Obsidian Sync")
        self.resizable(True, True)
        self.minsize(560, 520)
        self._pending = []
        self._build()
        self._load_token()
        self._scan()

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
        ttk.Button(tf, text="Save",  command=self._save_token).grid(row=0, column=1)
        ttk.Button(tf, text="Show",  command=lambda: self._toggle_show(token_entry)).grid(row=0, column=2, padx=(4, 0))

        link = tk.Label(tf, text="Get token →", fg="blue", cursor="hand2",
                        font=("TkDefaultFont", 9, "underline"))
        link.grid(row=1, column=0, sticky="w", pady=(4, 0))
        link.bind("<Button-1>", lambda _: self._open_url("https://readwise.io/access_token"))

        # Folder row
        ff = ttk.LabelFrame(self, text="Obsidian folder", padding=p)
        ff.grid(row=1, column=0, sticky="ew", padx=p, pady=(p, 0))
        ff.columnconfigure(0, weight=1)

        self.folder_var = tk.StringVar(value=OBSIDIAN_FOLDER)
        ttk.Entry(ff, textvariable=self.folder_var).grid(row=0, column=0, sticky="ew", padx=(0, p))
        ttk.Button(ff, text="Scan", command=self._scan).grid(row=0, column=1)

        # Pending files list
        lf = ttk.LabelFrame(self, text="Pending notes", padding=p)
        lf.grid(row=2, column=0, sticky="nsew", padx=p, pady=(p, 0))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        cols = ("title", "author", "quote")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", selectmode="extended")
        for col, width in zip(cols, (160, 120, 260)):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col,  width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        # Log
        logf = ttk.LabelFrame(self, text="Log", padding=p)
        logf.grid(row=3, column=0, sticky="ew", padx=p, pady=(p, 0))
        logf.columnconfigure(0, weight=1)

        self.log = scrolledtext.ScrolledText(logf, height=5, state="disabled", wrap="word")
        self.log.grid(row=0, column=0, sticky="ew")

        # Buttons
        bf = ttk.Frame(self, padding=(p, p // 2, p, p))
        bf.grid(row=4, column=0, sticky="ew")
        bf.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar()
        ttk.Label(bf, textvariable=self.status_var, foreground="grey").grid(row=0, column=0, sticky="w")

        self.send_btn = ttk.Button(bf, text="Send all →", command=self._send_all)
        self.send_btn.grid(row=0, column=1)
        ttk.Button(bf, text="Send selected", command=self._send_selected).grid(row=0, column=2, padx=(6, 0))

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
        self._log("Token saved.")

    def _toggle_show(self, entry):
        entry.configure(show="" if entry.cget("show") == "•" else "•")

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _scan(self):
        folder = self.folder_var.get().strip()
        self._pending = scan_folder(folder)
        self.tree.delete(*self.tree.get_children())
        for item in self._pending:
            self.tree.insert("", "end", values=(
                item["title"],
                item["author"] or "",
                item["quote"][:80] + ("…" if len(item["quote"]) > 80 else ""),
            ))
        self.status_var.set(f"{len(self._pending)} note(s) pending.")
        self._log(f"Scanned '{folder}': {len(self._pending)} pending.")

    # ── Send ──────────────────────────────────────────────────────────────────

    def _get_token(self):
        t = self.token_var.get().strip()
        if not t:
            messagebox.showwarning("No token", "Enter your Readwise API token first.")
        return t

    def _send_items(self, items):
        token = self._get_token()
        if not token:
            return
        sent = 0
        for item in items:
            try:
                result = post_highlight(token, item["quote"], item["title"], item["author"])
                hl_id  = result[0].get("id", "?") if result else "?"
                with open(item["path"], encoding="utf-8") as f:
                    text = f.read()
                add_sent_tag(item["path"], text)
                self._log(f"✓ Sent '{item['title']}' (id {hl_id})")
                sent += 1
            except requests.HTTPError as e:
                self._log(f"✗ API error for '{item['title']}': {e.response.status_code}")
            except requests.ConnectionError:
                self._log(f"✗ Connection error — '{item['title']}' not sent.")
        self.status_var.set(f"Done: {sent}/{len(items)} sent.")
        self._scan()

    def _send_all(self):
        if not self._pending:
            messagebox.showinfo("Nothing to send", "No pending notes found.")
            return
        self.send_btn.state(["disabled"])
        self.update()
        try:
            self._send_items(self._pending)
        finally:
            self.send_btn.state(["!disabled"])

    def _send_selected(self):
        selected_indices = [self.tree.index(iid) for iid in self.tree.selection()]
        items = [self._pending[i] for i in selected_indices]
        if not items:
            messagebox.showinfo("Nothing selected", "Select one or more notes first.")
            return
        self._send_items(items)


if __name__ == "__main__":
    app = App()
    app.mainloop()
