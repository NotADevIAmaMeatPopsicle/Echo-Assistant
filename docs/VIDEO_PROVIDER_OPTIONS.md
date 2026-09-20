# ECHO-09: video provider decision

Official sources checked **2026-09-20**. Research only: no browser/OS installation,
account change, playback or Pi configuration was performed. The repository's
Deck launcher uses Linux **Chromium** and a private browser profile; this research
did not inventory its current browser version, codecs, CDM or hardware decoding.

**Recommend YouTube's official embedded player for ordinary, embeddable hosted
videos**, disabled by default with no Echo-managed provider sign-in. This is a permitted integration
with a documented browser API; it is not evidence of successful playback on
this Pi. It does **not** include YouTube movies/rentals/purchases, YouTube TV,
Netflix or Prime Video. Existing local-file playback does not establish any of
those capabilities. ECHO-09 remains open pending authorized provider acceptance.

## What the official sources establish

| Provider / route | Evidence | Decision for the current Pi Chromium build |
| --- | --- | --- |
| **YouTube website and official iframe** | YouTube explicitly permits website embedding, subject to its API terms and uploader restrictions. The IFrame API requires HTML5 `postMessage`; minimum player size is 200 × 200, with 480 × 270 recommended for 16:9. [Embed help](https://support.google.com/youtube/answer/171780?hl=en), [IFrame API](https://developers.google.com/youtube/iframe_api_reference). | Smallest justified provider integration. Use the provider's player, controls, captions and ads. Actual codecs, touch interaction, playback and audio coordination still require this Pi. |
| **YouTube paid movies/TV** | Studio licensing determines device-specific quality; buying an HD/UHD title does not mean the purchasing browser can play that quality. [YouTube paid-video help](https://support.google.com/youtube/answer/3306741?hl=en). | Separate entitlement/DRM/device acceptance. An ordinary embedded clip proves none of this. No purchase, rental or paid-library feature is proposed. |
| **Netflix direct browser** | Netflix permits watching on *some* GNU/Linux computers but explicitly cannot guarantee Linux operation or provide Linux troubleshooting. Its current Linux list names Chrome **117+**, Firefox **129+**, Edge **118+**, Opera **92+**, with listed maxima up to 1080p. [Official requirements](https://help.netflix.com/en/node/30081). | The list does not name this Pi's Chromium build. Do not claim Netflix works, promise 1080p, or add an embedded Netflix player. No public supported Echo embed route was established. A legitimate provider-site test would be a separate owner-authorized acceptance step. |
| **Prime Video direct browser** | Amazon lists Linux and current Chrome, Firefox, Edge, Safari and Opera, but explicitly restricts systems other than Windows/macOS to **standard definition**. Its Chrome error-7235 guidance refers to the Widevine CDM. [Computer requirements](https://www.primevideo.com/help?nodeId=GUX9FYHU5D8LC9EJ), [CDM guidance](https://www.primevideo.com/help?nodeId=G8X362NHQ64MH5SY). | There is a documented Linux browser route, but it does not certify the installed Pi Chromium/CDM combination. No Prime embed/account adapter is justified yet. Do not promise HD on Linux. |
| **Remote Cast receiver** | Prime's Android app can send to an actual Chromecast on the same Wi-Fi; Google TV devices can use their own app. [Prime Cast instructions](https://www.primevideo.com/help?nodeId=GLK7BRU8S9LCUV8K). | This sends video to that supported device, not into Deck's browser. The Bluetooth adapter carries audio only. See [casting findings](CASTING_OPTIONS.md); controller libraries do not turn the Pi into a certified receiver. |
| **External supported hardware** | Netflix directs TV users to devices with its Netflix app. Prime lists Google TV/TV Streamer, Apple TV and other supported players. [Netflix TV guidance](https://help.netflix.com/en/node/33222), [Prime player list](https://www.primevideo.com/help?nodeId=GTAQMQBSRQKKE9FJ). | If dependable subscription-video playback is required, select an exact provider-supported model and use its native app. This is a separate video endpoint, account and audio path, not an Echo/Pi implementation. Check the actual panel's inputs, HDCP and control method before choosing hardware. |

Do not use obsolete architecture assumptions to reject a legitimate future
route. Google's current [Chrome Linux requirements](https://support.google.com/chrome/a/answer/7100626?hl=en)
include ARM processors; its [2026-03-12 announcement](https://blog.google/chromium/bringing-chrome-to-arm64-linux-devices/)
announced ARM64 Linux Chrome for Q2 2026. That does not install Chrome on Deck or
prove a particular Pi/CDM/provider combination works.

[Widevine's platform list](https://developers.google.com/widevine/drm/overview)
includes Chrome on Linux **and Chromium**. A browser's EME API, a codec test or
that platform listing alone does not prove an architecture-compatible CDM is
installed, provider licensing succeeds, or a particular title/resolution is
authorized. [Chromium's media documentation](https://www.chromium.org/audio-video/)
also distinguishes its default codecs from proprietary Chrome codecs. Inspect
the actual distribution build; do not infer H.264/AAC or hardware decoding from
the browser name. No user-agent spoofing, copied CDM from another platform,
stream extraction, DRM removal or patched provider player is proposed.

## Bounded future YouTube contract

Implement only the ordinary-video route above. A reasonable boundary is one
owner-selected video at a time, with no search/library OAuth or paid catalog:

- Owner-only configuration under `/v1/display/video/settings`: provider fixed to
  `youtube`, `enabled:false`, `video_id:""`, `allowed_display_ids:[]`, and a
  revision. IDs must match `[A-Za-z0-9_-]{11}`; the backend constructs no arbitrary
  outbound URL. Preserve encrypted configuration and existing display/access
  checks. A paired display or household membership does not grant setup rights.
- `GET /v1/display/video` returns only the selected ID, revision and permission
  for that current display. No provider credentials, cookies, account tokens or
  inferred Google sign-in. Access expiry/account changes destroy the player and
  discard stale callbacks using a player generation token.
- On Deck show **YouTube**, **Load selected video**, **Stop video**
  and **Watch on YouTube**. Contact YouTube only after the explicit load action;
  no background iframe, thumbnail prefetch or autoplay. Account, age, region or
  purchase requirements stay on the provider's own site/app, preferably through
  a phone handoff. Echo supplies no sign-in form/OAuth flow and must not infer
  the iframe's signed-in/signed-out state from existing browser cookies.
- Construct `https://www.youtube-nocookie.com/embed/<id>` with `enablejsapi=1`,
  `autoplay=0`, `playsinline=1`, `controls=1` and the real enclosing `origin`.
  Keep YouTube branding/controls/ads visible; do not overlay or cover the player.
  Start muted. Screen-awake state must use explicit player events because
  `screen.js` cannot discover a cross-origin iframe's inner `<video>` element.
- Show errors honestly: `5` means an HTML5 playback failure; `100` missing/private
  content; `101`/`150` embedding denied; `153` missing client identification.
  Offer the provider-site handoff; do not proxy, extract or retry around a
  provider restriction. Handle autoplay blocking without enabling autoplay.

Privacy-enhanced embedding reduces personalization; it is **not zero-egress or
anonymous playback**. Loading it contacts Google and may serve non-personalized
ads. The current Echo response policy is `Referrer-Policy: no-referrer`, while
YouTube now requires HTTP `Referer`/client identification and recommends
`strict-origin-when-cross-origin`. The `origin` query parameter does not replace
that requirement. Any implementation needs a narrow, explicit embed-context
referrer policy and only the required YouTube frame/API-script CSP allowances;
do not weaken all Echo pages, forge a referrer or expose credential-bearing URLs.
The real page origin may be disclosed. Test the Pi loopback bridge origin as well
as the owner page. [YouTube required functionality](https://developers.google.com/youtube/terms/required-minimum-functionality).

## Audio is an implementation gate

`deploy/pi/kiosk.py` selects the private PulseAudio server when Pi voice uses
`echo_cancelled` / `echo_processed`. The video must use that same **processed
speaker**, with no fallback to HDMI, another room or Mini. A plain external
browser launch is not proof that it inherits this route.

The iframe does **not** inherit native Spotify/Bluetooth focus. `pauseVideo()`
and its `PAUSED` event describe player state; they do not acknowledge that queued
Pi audio has stopped. Likewise, `setVolume(2)` is an initial player setting,
not an enforceable 2% output ceiling: YouTube's own controls can change it.
Do not claim that API calls alone preserve Echo's acoustic contract.

Before audible inline playback, the coordinator must establish a Pi-local,
enforced browser-video attenuation/stop boundary and register it with the same
synchronous focus admission used for other outputs. Define
`stop_video_for_capture(generation) -> confirmed` so only a real local output
stop acknowledgement admits microphone capture. On timeout/stale state, keep
capture blocked and tear down the iframe; neither a pause event nor DOM removal
alone is the acknowledgement. Volume, captions and touch controls must remain
usable under YouTube's player rules. If that boundary cannot be established,
keep audible inline playback unavailable and provide the phone/provider-site
handoff instead. Do not silently change host mixer gain or disable voice safety.

## Acceptance and product decision

First obtain a read-only Pi browser/OS/codec/CDM inventory. Then, only in an
authorized real-provider check, verify one ordinary embeddable YouTube video,
captions/touch controls, truthful error handling, private-origin identification,
the unchanged local output ceiling, hard focus, Stop, access revocation and
no resume after reload/outage. Synthetic player events cannot close that gate.

For Netflix/Prime, retain **unverified on this Pi**, rather than declaring Linux
categorically impossible. If paid catalogs are the requirement, choose either a
separate authorized test of an official supported browser/CDM combination
(Prime's documented Linux limit is SD; Netflix retains its Linux caveat), or a
provider-supported external device. Do not count an ordinary YouTube clip or
local MP4 as paid-video acceptance. No implementation or real acceptance was
performed in this investigation.
