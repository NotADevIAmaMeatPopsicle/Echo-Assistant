# Music in more than one room

**Music → Together** connects Echo to a private [Music Assistant](https://www.music-assistant.io/)
server. It shows shared players, track titles, current groups, transport controls,
mute and volume. Choose **Choose rooms**, review the outputs, then **Apply group**.
A playing source can become audible in a room as soon as it joins.

Echo uses the players' advertised grouping support. Compatible native groups can
provide synchronized playback; combining unrelated protocols does not guarantee
synchronization. The controls do not convert an ordinary Spotify receiver into a
Music Assistant player.

## Connect a server

1. Install Music Assistant using its [installation guide](https://www.music-assistant.io/installation/).
   The Echo adapter is checked against server **2.10.4**. Complete its first-run
   setup and add the players and music providers you want to use.
2. Create a dedicated regular user and an integration access token in Music
   Assistant. Keep its administrative account separate. Long-lived tokens in this
   version expire after one year; replace an expired token in Echo Settings.
3. In Echo's owner workspace, open **Settings → Music Assistant → Connection &
   outputs**. Enter the private server origin and token, enable the connection,
   and save. Use an explicit private IP, or `http://echo-music:8095` when both
   services run on Echo's Docker network. `localhost` means the API's own host or
   container, not the browser's computer.
4. **Load outputs**, select the players Echo may control, then **Save shared
   outputs**. New or unselected players are not automatically shared.
5. Open **Music → Together**. Start your desired source through Music Assistant,
   then choose compatible outputs. Existing Spotify Connect and local-media tabs
   remain separate playback paths.

The token is encrypted on the Echo host and is not returned to the browser. A
changed server origin requires a new token entry. Requests do not follow redirects
or system proxies. Music Assistant remains responsible for its own users, provider
accounts, library and player configuration.

## Private Docker option

The optional [music overlay](../deploy/host/music.yaml) pins the image and stores
Music Assistant data in its own persistent volume:

```sh
docker compose -f deploy/host/compose.yaml -f deploy/host/music.yaml up -d music
```

This only starts the service. It deliberately publishes no port and is not a
complete endpoint-discovery or first-run setup solution. Configure it through an
authenticated management path on the Docker host, or use an already configured
private Music Assistant server. The Echo API can reach its internal port 8095.
Do not expose an unfinished setup page or unauthenticated Sendspin listener to a
shared network. A bridge network does not carry LAN multicast discovery by itself.

Music Assistant's `/data` volume contains its separate account and provider state.
Back it up using Music Assistant's supported backup workflow. Echo recovery
archives include only Echo's encrypted connection settings and selected outputs;
they do not back up the Music Assistant database, library or service credentials.
Stopping the optional service leaves Echo's existing Spotify path available.

## What the controls protect

- Only the owner can configure the connection or discover and share new players.
  Trusted Household displays can control shared outputs. Guest displays have no
  grouped-music access in this version.
- Commands are rejected when a group includes an output not shared with Echo.
  Review those groups in Music Assistant before controlling them through Echo.
- Group changes recheck availability, membership and permissions after the review
  dialog. Echo refuses incompatible outputs and does not automatically move a
  speaker out of another group.
- The owner can cap new volume commands. This is a control limit, not an acoustic
  limiter: it does not lower an amplifier, existing player volume or volume changes
  made in other applications. Start with a low level on each physical device.
- A command acknowledgement means Music Assistant accepted the request. The next
  refresh reports the player's state; it does not prove that a speaker was audible.
  Uncertain network responses are not retried automatically.

## Current endpoint status

The API and display controls have synthetic coverage for room selection, stale
state, permissions, volume limits and phone layout. A private Music Assistant
2.10.4 instance has also accepted an authenticated player-inventory request.

The bundled Pi Spotify receiver and round firmware are **not yet Sendspin
players**. Native client installation, private audio transport, interaction with
voice ducking and real multi-speaker timing remain in the build queue. The
[Sendspin project](https://www.sendspin-audio.com/) supplies clients and an ESP-IDF
SDK for that integration; this page does not claim they are already installed.
