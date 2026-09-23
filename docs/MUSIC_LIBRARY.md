# Music on Echo Deck

## Radio

Music → Radio opens the public Radio Browser directory. Search by station name,
country or genre, or start with Popular. The star saves a favorite in the current
browser. Owner-managed station presets remain available below the directory and
in Settings. A station starts only when you press Play. Streams must use HTTPS;
the directory hides broken and HLS-only stations that the browser cannot play.
Directory availability and individual station uptime can vary.

## Music stored on the SD card

The Pi bridge creates `~/Music/Echo` for the desktop user. Copy music there using
the Pi file manager or SFTP. Files automatically scans this folder when opened
and every 15 seconds while visible. Rescan picks up changes immediately. This
library is local to that Pi; another browser can choose its own files but cannot
read the Pi's SD card remotely.

Supported file extensions are MP3, M4A, AAC, OGG, Opus, WAV, FLAC, MP4 and WebM.
Actual playback depends on Chromium's codec support. The interface offers song
search, folder and playlist filters, queueing, Play and Shuffle, plus the existing
previous/next, pause and seek controls. Queue does not autoplay. The queue lasts
for the browser session; files and playlists remain on the card.

Use UTF-8 `.m3u` or `.m3u8` playlists with one path per line, relative to the
playlist file. For example, `Favorites.m3u` in `~/Music/Echo`:

```m3u
#EXTM3U
Quiet hours/Evening light.mp3
Quiet hours/Morning walk.flac
```

Missing entries are marked in the playlist selector. External URLs, files outside
the music folder and symbolic links are excluded. The index is read-only, supports
up to 5,000 tracks and 200 playlists, and shows the card's remaining space. A queue
holds up to 1,000 tracks. The authenticated Pi bridge supports byte ranges for
seeking; Guest mode cannot browse or stream the household SD library.

## Spotify account and playlists

For a new installation, Settings → Music Assistant accepts an optional provider
setup token from a Music Assistant admin. Echo encrypts it separately from the
normal playback token and uses it only for the owner-managed Spotify setup flow.

Music → Spotify → **Connect account** in the owner web UI starts Music Assistant's
Spotify setup. Approve Spotify in the new tab, then return to Echo to finish the
playback authorization steps. Choose the librespot playback backend. The setup
defaults to browser approval because Docker may prevent the temporary pairing
device from appearing in Spotify. Browser approval may ask you to paste the final
localhost callback URL into the setup form. App discovery is optional for servers
on the same network as the phone. A separate developer client ID is
optional. Spotify Premium is required.

Music Assistant stores the provider connection in its persistent `/data` volume.
Echo does not store Spotify passwords or refresh tokens in the browser. A restart
preserves the connection, although revoked or expired authorization may require
reconnecting. Choose a shared output, then browse My library, search, or inspect
its queue. Play replaces that output's queue. The Together tab provides Music
Assistant transport controls and room grouping. Spotify Connect from the phone
continues to work separately.

The Spotify shelf opens with three playlists. Names prefixed with `1.`, `2.` and
`3.` take priority; **More playlists** loads the rest. **Podcasts** shows followed
shows, with an **Episodes** button for each one. **New episodes** combines recent
episodes from those shows, newest first, excluding episodes marked completed by
Music Assistant. This is a release feed, not Spotify's saved-episodes collection.
Choose **Latest aired episode** to order the shows by their latest release date.
Dates load in the background; unavailable shows are reported. The recent feed
checks up to 64 followed shows and keeps the newest 200 episodes per show.
Music Assistant controls upstream freshness; Spotify episode metadata may be cached
there for up to 12 hours. Browsing and sorting never start playback.

Account setup is owner-only. Household displays can browse the connected library
and play to outputs shared with Echo. Only one setup flow runs at a time; close
or cancel it before beginning another. An unfinished setup expires after 20
minutes and may need to be restarted after an Echo host restart.
