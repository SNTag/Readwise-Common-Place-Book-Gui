# Readwise Common Place Book GUI

A lightweight desktop GUI for capturing quotes and highlights directly into [Readwise](https://readwise.io), built with Python and tkinter.

## Features

- Submit quotes/highlights to Readwise with a single click
- Optional metadata: book/article title, author, tags, and personal notes
- API token stored securely in `~/.config/readwise/token` (permissions set to `0600`)
- Token visibility toggle (show/hide)
- Keyboard shortcut: `Ctrl+Enter` to submit
- Works on Linux, macOS, and Windows

## Requirements

- Python 3.7+
- `requests` library

```bash
pip install requests
```

## Usage

```bash
python readwise_gui.py
```

1. Paste your Readwise API token (get it at [readwise.io/access_token](https://readwise.io/access_token)) and click **Save**
2. Enter your quote in the **Quote** field
3. Optionally fill in Title, Author, Tags (space-separated), and a personal Note
4. Click **Submit →** or press `Ctrl+Enter`

## Token Storage

The token is saved to `~/.config/readwise/token` with read/write permissions restricted to your user. Alternatively, set the `READWISE_TOKEN` environment variable to avoid storing it on disk.
