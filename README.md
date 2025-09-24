## MusicBrainz Picard: Navidrome (Subsonic) Integration

Bring your Navidrome library into MusicBrainz Picard. This plugin adds a Navidrome menu, an options page, a playlists browser, and a powerful library browser with filtering, search, progress, and drag-and-drop interactions. Create and send playlists to Navidrome directly from Picard.

### Highlights
- **Navidrome menu and actions**: Connect…, Create Playlist from Library…, Edit Playlists…
- **Options page**: Server URL, username, password, SSL verification, optional credential saving, connection test
- **Library browser**: Filter menu, search, adjustable columns/rows, live progress, local reordering, playlist creation
- **Playlists browser**: View playlists, preview and reorder tracks locally, then save back safely

---

## Feature Overview (Comprehensive)

- **Authentication and connectivity**
  - Subsonic-compatible client for Navidrome
  - Salted token authentication (MD5 with per-request salt)
  - SSL verification toggle (enable/disable certificate verification)
  - Optional “Save credentials” (can keep credentials ephemeral)

- **Picard integration**
  - Adds a top-level **Navidrome** menu to Picard’s menubar
    - Connect… (opens a lightweight Options dialog)
    - Create Playlist from Navidrome Library… (opens library browser)
    - Edit Playlists in Navidrome… (opens playlists browser)
  - Adds context menu actions on albums/tracks/files (mirrors menu functions)
  - Options page under `Options > Plugins > Navidrome`

- **Playlists browser**
  - Lists server playlists and shows their tracks
  - Local drag-and-drop reordering with clear drop indicators
  - Adjustable column widths; reorderable headers
  - Non-destructive preview; only changes server order when you choose to save

- **Library browser**
  - Live progress dialog while fetching: “Fetched X of Y”
  - “Filter ▼” menu to hide/show columns via checkboxes
  - Search box filters across visible columns
  - First column shows cleaned file “dataname” (removes prefixes like “NN-NN - ”)
  - Columns adjustable (resizable & re-orderable by drag)
  - Rows are height-adjustable; local reordering (does not impact server order)
  - Create playlist from selected rows; IDs are taken from table order and unaffected by sorting

- **Selection review dialog**
  - Review and finalize the order of selected tracks with **≡** drag handles
  - Clear UX cues and safe handling of drag/release edge-cases

- **Error handling and UX**
  - Clear error dialogs for network/API problems
  - Responsive UI; avoids blocking Picard during network operations

- **Security & privacy**
  - Token auth, optional SSL verify
  - Credentials can be avoided from being persisted
  - No audio upload or file modification; only metadata lookup and playlist definitions

---

## Interactions & Symbols

- **Navidrome menu**: Picard menubar → Navidrome → { Connect…, Create Playlist from Library…, Edit Playlists… }
- **Options page**: Picard → Options → Plugins → Navidrome
  - Test Connection, open Library/Playlists, and About… buttons
- **Filter menu**: “Filter ▼” → toggle columns via checkboxes
- **Search**: type text to filter rows across visible columns
- **Drag handles (rows)**: **≡**
  - Drag to reorder rows locally in review and browser dialogs
- **Resize handles (columns)**: **⋮**
  - Drag to adjust column widths

---

## Installation

1) Download the single-file plugin (`picard_navidrome_integration_(0.6.0)-stable.py`).
2) Open Picard and go to: Help → Open plugin folder (this opens your Picard plugins directory).
3) Place the plugin file into that folder and restart Picard.
4) Enable the plugin in Picard: Options → Plugins → check “Navidrome (Subsonic) Integration”.

Notes:
- On Windows/macOS/Linux, the “Open plugin folder” menu item is the most reliable way to locate the correct directory.
- For Docker Picard, mount the plugin file into the container’s Picard config/plugins directory (see your Docker image docs).

---

## Configuration

Options → Plugins → Navidrome:
- Server URL (e.g. `https://navidrome.example.com`)
- Username
- Password (token auth is derived internally)
- Verify SSL (recommended)
- Save credentials (optional)
- Buttons: Test Connection, Edit Playlists…, Create Playlist from Library…, About…

---

## Usage

### Connect to Navidrome
- Use Navidrome → Connect… or open Options → Plugins → Navidrome and press “Test Connection”.

### Browse your library and create a playlist
1) Navidrome → Create Playlist from Navidrome Library…
2) Use Filter ▼ to show/hide columns; type in the search box to narrow results.
3) Select rows using the leftmost checkbox column; adjust column widths and row heights as needed.
4) Click “Create playlist” to open the review dialog.
5) Use **≡** drag handles to reorder tracks; confirm to send the playlist to Navidrome.

### Edit playlists
1) Navidrome → Edit Playlists in Navidrome…
2) Select a playlist to view tracks; reorder locally with drag-and-drop.
3) Save to update the playlist on the server.

---

## Compatibility

- Picard API: 2.0–2.14
- Subsonic API: 1.16.1+ (Navidrome compatible)
- Docker Picard: supported (mount plugin into the Picard plugins dir inside the container)

---

## Changelog

- In-app: Navidrome → About… → Changelog
- GitHub Releases: update link as needed (`https://github.com/vikshepo` or your repository URL)

---

## Troubleshooting

- “Connection error” / “Please fill in Server URL, Username and Password”
  - Ensure the base URL, username, and password are set in Options and that “Verify SSL” matches your server configuration.
- “No playlists found”
  - Verify the account has access and that playlists exist on the server.
- Slow fetching
  - Large libraries can take time; the progress dialog shows status. Try narrowing results via Filter/Search.
- Playlist names rejected
  - Ensure a non-empty name and required permissions on the server.

---

## Contributing

PRs and issues are welcome. Please describe your environment (Picard version, OS, Navidrome version) and provide clear steps to reproduce problems.

---

## Donate

If you enjoy this plugin, consider supporting development:

- PayPal: `https://paypal.me/vikshepo` ☕❤

---

## Credits

- Developed by **Viktor Shepotynnyk**
- Thanks to the MusicBrainz Picard and Navidrome communities



