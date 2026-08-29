#!/usr/bin/env python3
"""
Readwise Obsidian sync — scans a folder, shows all notes, sends pending
quotes to Readwise. Files tagged 'readwise' are shown in blue and skipped.
After a successful upload the tag and Readwise ID are written back to the file.

Requires: pip install requests keyring
"""

LAST_MODIFIED = "2026-08-29"

# ── User configuration ────────────────────────────────────────────────────────
# OBSIDIAN_FOLDER is the default used on first run only.
# After that the saved setting in ~/.config/readwise/settings.json takes over.
OBSIDIAN_FOLDER = r"C:\Users\YourName\Documents\Obsidian\Vault\Quotes"

DEFAULT_TITLE    = "CommonPlace Book"
KEYCHAIN_SERVICE = "readwise-gui"
KEYCHAIN_USER    = "api-token"
# ─────────────────────────────────────────────────────────────────────────────

import json
import os

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".config", "readwise", "settings.json")
import re
import urllib.parse
import webbrowser
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
    t = os.environ.get("READWISE_TOKEN")
    if t:
        return t.strip()
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
        path = os.path.join(os.path.expanduser("~"), ".config", "readwise", "token")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(token)


# ── Settings persistence ──────────────────────────────────────────────────────

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"folder": OBSIDIAN_FOLDER}

def save_settings(data):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── YAML frontmatter helpers ──────────────────────────────────────────────────

_FRONTMATTER_RE  = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_SOURCE_LINE_RE = re.compile(r"^source\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)

READWISE_HL_URL = "https://readwise.io/bookreview/{id}"


def parse_frontmatter(text):
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip().lower()] = val.strip()
    return result


def is_sent(text):
    """A file is considered sent if its source field contains 'readwise:'."""
    fm = parse_frontmatter(text)
    return "readwise:" in fm.get("source", "")


def mark_sent(filepath, text, hl_id):
    """Write the Readwise ID and link into the summary frontmatter field."""
    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        return
    fm_body = fm_match.group(1)

    link  = READWISE_HL_URL.format(id=hl_id)
    entry = f"[readwise:{hl_id}]({link})"

    def source_replacer(m):
        existing = m.group(1).strip().strip('"')
        merged   = f"{existing} | {entry}" if existing else entry
        return f'source: "{merged}"'

    if _SOURCE_LINE_RE.search(fm_body):
        fm_body = _SOURCE_LINE_RE.sub(source_replacer, fm_body)
    else:
        fm_body += f'\nsource: "{entry}"'

    new_text = text[:fm_match.start(1)] + fm_body + text[fm_match.end(1):]
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
    Return a list of dicts for every .md file in folder.
    Each dict includes 'uploaded' (bool) based on whether SENT_TAG is present.
    Only files with a non-empty 'quote' field are included.
    """
    files = []
    if not os.path.isdir(folder):
        return files
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(folder, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue

        fm = parse_frontmatter(text)
        quote = fm.get("quote", "").strip()
        if not quote:
            continue

        uploaded = is_sent(text)
        files.append({
            "path":     fpath,
            "filename": fname,
            "title":    fm.get("book title", "").strip() or DEFAULT_TITLE,
            "author":   fm.get("author", "").strip() or None,
            "quote":    quote,
            "uploaded": uploaded,
        })
    return files


# ── Obsidian opener ───────────────────────────────────────────────────────────

def open_in_obsidian(filepath):
    """Open a file in Obsidian using the obsidian:// URI scheme."""
    uri = "obsidian://open?path=" + urllib.parse.quote(filepath, safe=":/\\")
    webbrowser.open(uri)


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

        ttk.Label(f, text="Obsidian folder").grid(row=0, column=0, sticky="w", padx=(0, p), pady=4)
        self._folder_var = tk.StringVar(value=folder)
        ttk.Entry(f, textvariable=self._folder_var, width=48).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(f, text="API token").grid(row=1, column=0, sticky="w", padx=(0, p), pady=4)
        self._token_var = tk.StringVar(value=load_token())
        token_entry = ttk.Entry(f, textvariable=self._token_var, show="•", width=48)
        token_entry.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(f, text="Show",
                   command=lambda: token_entry.configure(
                       show="" if token_entry.cget("show") == "•" else "•")
                   ).grid(row=1, column=2, padx=(4, 0))

        storage = "Windows Credential Manager" if _KEYRING_AVAILABLE else "plain file (~/.config/readwise/token)"
        ttk.Label(f, text=f"Token stored in: {storage}", foreground="grey").grid(row=2, column=1, sticky="w")

        link = tk.Label(f, text="Get token →", fg="blue", cursor="hand2",
                        font=("TkDefaultFont", 9, "underline"))
        link.grid(row=3, column=1, sticky="w", pady=(2, p))
        link.bind("<Button-1>", lambda _: webbrowser.open("https://readwise.io/access_token"))

        bf = ttk.Frame(f)
        bf.grid(row=4, column=0, columnspan=3, sticky="e")
        ttk.Button(bf, text="Save",   command=self._save).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=self.destroy).grid(row=0, column=1)

        self.bind("<Return>", lambda _: self._save())
        self.bind("<Escape>", lambda _: self.destroy())
        self._center(parent)

    def _center(self, parent):
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
    def __init__(self, parent, pending):
        super().__init__(parent)
        self.title("Confirm upload")
        self.resizable(True, True)
        self.minsize(660, 380)
        self.transient(parent)
        self.grab_set()
        self.result = None

        p = 10
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="Click a row to toggle it. Only checked notes will be sent.",
                  padding=(p, p, p, 0)).grid(row=0, column=0, sticky="w")

        frame = ttk.Frame(self, padding=p)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        cols = ("send", "file", "book title", "author", "quote")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="none")
        for col, width in zip(cols, (40, 160, 140, 110, 260)):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(frame, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self._checks = {}
        for item in pending:
            var = tk.BooleanVar(value=True)
            iid = self.tree.insert("", "end", values=(
                "✓", item["filename"], item["title"],
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
        self._center(parent)

    def _center(self, parent):
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
        vals = list(self.tree.item(iid, "values"))
        vals[0] = "✓" if var.get() else "✗"
        self.tree.item(iid, values=vals)

    def _confirm(self):
        self.result = [item for var, item in self._checks.values() if var.get()]
        self.destroy()


# ── Main window ───────────────────────────────────────────────────────────────

FILTER_OPTIONS = ["All files", "Not yet uploaded", "Already uploaded"]

class App(tk.Tk):
    PAD = 10

    def __init__(self):
        super().__init__()
        self.title("Readwise — Obsidian Sync")
        self.resizable(True, True)
        self.minsize(620, 520)
        self._folder  = load_settings().get("folder", OBSIDIAN_FOLDER)
        self._all     = []   # full scan results
        self._build()
        self._scan()

    def _build(self):
        p = self.PAD
        self.columnconfigure(0, weight=1)

        # Top bar
        top = ttk.Frame(self, padding=(p, p, p, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Folder:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._folder_label = ttk.Label(top, text=self._folder, foreground="grey", anchor="w")
        self._folder_label.grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="⚙ Settings", command=self._open_settings).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(top, text="↺ Scan",     command=self._scan).grid(row=0, column=3, padx=(4, 0))

        # Filter row
        frow = ttk.Frame(self, padding=(p, 4, p, 0))
        frow.grid(row=1, column=0, sticky="ew")
        ttk.Label(frow, text="Show:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._filter_var = tk.StringVar(value=FILTER_OPTIONS[0])
        cb = ttk.Combobox(frow, textvariable=self._filter_var,
                          values=FILTER_OPTIONS, state="readonly", width=20)
        cb.grid(row=0, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda _: self._apply_filter())

        # File list
        lf = ttk.LabelFrame(self, text="Notes", padding=p)
        lf.grid(row=2, column=0, sticky="nsew", padx=p, pady=(p, 0))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        cols = ("status", "file", "book title", "author", "quote")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", selectmode="extended")
        for col, width in zip(cols, (60, 160, 140, 110, 260)):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=width, anchor="w")
        self.tree.tag_configure("uploaded", background="#cce5ff")  # light blue
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self._open_selected)

        # Log
        logf = ttk.LabelFrame(self, text="Log", padding=p)
        logf.grid(row=3, column=0, sticky="ew", padx=p, pady=(p, 0))
        logf.columnconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(logf, height=4, state="disabled", wrap="word")
        self.log.grid(row=0, column=0, sticky="ew")

        # Bottom buttons
        bf = ttk.Frame(self, padding=(p, p // 2, p, p))
        bf.grid(row=4, column=0, sticky="ew")
        bf.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar()
        ttk.Label(bf, textvariable=self.status_var, foreground="grey").grid(row=0, column=0, sticky="w")
        ttk.Button(bf, text="Open in Obsidian", command=self._open_selected).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(bf, text="Send all →",        command=self._send_all).grid(row=0, column=2)
        ttk.Button(bf, text="Send selected",     command=self._send_selected).grid(row=0, column=3, padx=(6, 0))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _scan(self):
        self._all = scan_folder(self._folder)
        self._apply_filter()
        total    = len(self._all)
        pending  = sum(1 for f in self._all if not f["uploaded"])
        uploaded = total - pending
        self.status_var.set(f"{total} notes — {pending} pending, {uploaded} uploaded.")
        self._log(f"Scanned '{self._folder}': {pending} pending, {uploaded} uploaded.")

    def _apply_filter(self):
        filt = self._filter_var.get()
        if filt == "Already uploaded":
            shown = [f for f in self._all if f["uploaded"]]
        elif filt == "Not yet uploaded":
            shown = [f for f in self._all if not f["uploaded"]]
        else:
            shown = self._all

        self.tree.delete(*self.tree.get_children())
        for item in shown:
            tag    = "uploaded" if item["uploaded"] else ""
            status = "✓ sent" if item["uploaded"] else "pending"
            self.tree.insert("", "end", tags=(tag,), values=(
                status,
                item["filename"],
                item["title"],
                item["author"] or "",
                item["quote"][:80] + ("…" if len(item["quote"]) > 80 else ""),
            ))
        self._shown = shown

    def _open_settings(self):
        def on_save(new_folder):
            self._folder = new_folder
            self._folder_label.configure(text=new_folder)
            save_settings({"folder": new_folder})
            self.status_var.set("Settings saved.")
            self._scan()
        SettingsDialog(self, self._folder, on_save)

    def _open_selected(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select a note first.")
            return
        for iid in selection:
            idx  = self.tree.index(iid)
            item = self._shown[idx]
            open_in_obsidian(item["path"])

    def _pending_items(self):
        return [f for f in self._all if not f["uploaded"]]

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
        if not approved:
            self._log("Upload cancelled.")
            return

        sent = 0
        for item in approved:
            try:
                result = post_highlight(token, item["quote"], item["title"], item["author"])
                hl_id  = result[0].get("id", "?") if result else "?"
                with open(item["path"], encoding="utf-8") as fh:
                    text = fh.read()
                mark_sent(item["path"], text, hl_id)
                self._log(f"✓ Sent '{item['title']}' — {item['filename']} (id {hl_id})")
                sent += 1
            except requests.HTTPError as e:
                self._log(f"✗ API error for '{item['filename']}': {e.response.status_code} {e.response.text[:80]}")
            except requests.ConnectionError:
                self._log(f"✗ Connection error — '{item['filename']}' not sent.")

        self.status_var.set(f"Done: {sent}/{len(approved)} sent.")
        self._scan()

    def _ask_resubmit(self, already_uploaded):
        """
        Show a per-file prompt for each already-uploaded item.
        Returns the subset the user approves for re-sending.
        """
        approved = []
        for item in already_uploaded:
            answer = messagebox.askyesno(
                "Already uploaded",
                f"'{item['filename']}' has already been sent to Readwise.\n\n"
                f"Re-send it?",
                icon="question",
            )
            if answer:
                approved.append(item)
            else:
                self._log(f"Skipped (already uploaded): {item['filename']}")
        return approved

    def _send_all(self):
        self._confirm_and_send(self._pending_items())

    def _send_selected(self):
        indices  = [self.tree.index(iid) for iid in self.tree.selection()]
        selected = [self._shown[i] for i in indices]
        pending  = [f for f in selected if not f["uploaded"]]
        already  = [f for f in selected if f["uploaded"]]
        if already:
            pending += self._ask_resubmit(already)
        self._confirm_and_send(pending)


if __name__ == "__main__":
    app = App()
    app.mainloop()
