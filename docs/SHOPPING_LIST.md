# Echo Mini and Echo Deck shopping list

Amazon US parts for building either Echo endpoint, with quantities for **one Mini
and one Deck**. Reuse working parts you already own. Both endpoints can share one
Echo host, so a second server is not required.

Listings checked **23 September 2026**. Prices are snapshots in USD before tax and
shipping. Links have no affiliate tags. **Product** links were inspected on Amazon;
**Search** links are specification-based sourcing links, not verified individual
offers. Seller, variant, contents, and availability can change.

## Echo Mini: round AMOLED smart speaker

| Item | Qty | Amazon link | Selection and fit notes |
| --- | ---: | --- | --- |
| Waveshare ESP32-S3-Touch-AMOLED-1.75 | 1 | [Product, $42.99](https://www.amazon.com/dp/B0F7XTJ1ZL) | Exact supported board: 1.75-inch, 466 × 466 AMOLED, 16 MB flash, 8 MB PSRAM. Display, touch, microphones, codec, speaker amplifier, and battery management are onboard. Choose the standard board for the Crescent carrier. |
| Speaker | 1 | [Product: CQRobot 8-ohm, 3 W enclosed pair, $7.99](https://www.amazon.com/dp/B0738NLFTG) | Retail alternative, not the prototype's physical speaker. One pair supplies one speaker per build. Requires a different mount and an MX1.25 adapter on Mini. See the donor option below. Check whether the chosen Waveshare bundle already supplies a small speaker before buying another. |
| Original Google Home Mini speaker assembly | 1 instead of the retail speaker | [Search: Google Home Mini donor](https://www.amazon.com/s?k=Google+Home+Mini+1st+generation+renewed) | Closest reproduction of the photographed build. Salvage the speaker **with its original acoustic housing**. An exact loose replacement assembly was not verified on Amazon. Do not assume a Nest Mini assembly has the same geometry. |
| USB-A to USB-C **data** cable | 1 | [Search: short USB-C data cable](https://www.amazon.com/s?k=USB+A+to+USB+C+data+cable+1+foot) | Used for firmware, pairing, and power. The Crescent design checked a straight plug envelope of 16 × 10 × 7 mm; check the actual moulding and bend before buying a bulky cable. |
| Regulated USB 5 V supply | 1, if operating without host USB power | [Search: 5 V 2 A USB-A wall adapter](https://www.amazon.com/s?k=UL+listed+5V+2A+USB+A+wall+charger) | For standalone Wi-Fi use with the cable above. Use a reputable regulated supply. No separate amplifier supply is needed. |
| MX1.25 2-pin speaker pigtail | 1, if adapting a speaker | [Search: MX1.25 2-pin pigtails](https://www.amazon.com/s?k=MX1.25+2+pin+connector+wire+pigtail) | The board uses **MX1.25**, not the PH2.0 plug on the CQRobot speaker. Match housing and polarity to the board; do not force a similar-looking connector. |
| microSD card | Optional, 1 | [Search: SanDisk 32 GB microSDHC](https://www.amazon.com/s?k=SanDisk+32GB+microSDHC+Class+10) | For local media/storage features. Not required to power the board or use its screen and microphones. Follow the firmware's filesystem requirements. |
| Rechargeable battery | Optional, 1 | [Search: protected 3.7 V battery with MX1.25](https://www.amazon.com/s?k=3.7V+protected+lithium+battery+MX1.25+2+pin) | Vendor specifies a 3.7 V lithium battery connection. Voltage, charging limits, protection, polarity, connector, and physical fit must all match. This search is **not an approved drop-in battery recommendation**. USB power is sufficient for the initial build. |
| CS-MSX200SL-size battery used as the enclosure reference | Reference only | [Search: CS-MSX200SL](https://www.amazon.com/s?k=CS-MSX200SL+battery) | The Crescent cradle was sized around 51.816 × 29.972 × 12.192 mm. That establishes a mechanical envelope only, not electrical compatibility. Do not buy a pack solely because it fits the cradle. |
| Crescent printed enclosure and fasteners | 1 set | [Enclosure shopping details below](#mini-enclosure-and-shared-assembly-supplies) | Print the small fit kit first. The actual STL files are included in this repository. |

**Speaker choice:** use either a donor assembly or the retail speaker, not both.
The CQRobot alternative is a small rectangular enclosure; it will sound and mount
differently from the salvaged Google module. A higher wattage rating does not make
it draw that power continuously or increase the board's amplifier output.

## Echo Deck: touchscreen, voice, music, and camera

| Item | Qty | Amazon link | Selection and fit notes |
| --- | ---: | --- | --- |
| Raspberry Pi 4 Model B, 4 GB | 1 | [Product: CanaKit 4 GB Starter PRO Kit, $159.99](https://www.amazon.com/dp/B07V5JTMV9) · [Search: board only](https://www.amazon.com/s?k=Raspberry+Pi+4+Model+B+4GB+board+only) | Matches the Pi generation used by Deck. The kit is a convenient bundle, not a requirement. Compare the board-only price if reusing cables, storage, and power. |
| HDMI capacitive touchscreen | 1 | [Product: Waveshare 7-inch HDMI LCD (H), $59.99](https://www.amazon.com/dp/B07P8P3X6M) | **Alternative panel**, not an identification of the prototype. 1024 × 600 IPS with touch. Confirm its power arrangement, included cables, dimensions, and mounting holes before designing an enclosure. |
| Pi USB-C power supply | 1; included in kit | [Search: official Pi 4 5.1 V 3 A US supply](https://www.amazon.com/s?k=official+Raspberry+Pi+4+5.1V+3A+USB+C+power+supply+US) | The listed CanaKit instead includes its 3.5 A Pi 4 supply. Buy one supply, not both. Peripheral loading still has to stay within the Pi's USB power budget. |
| microSD boot and music card | 1; 32 GB included in kit | [Product: SanDisk High Endurance 128 GB, $36.99](https://www.amazon.com/dp/B07NY23WBG) | Optional capacity upgrade. 32 GB is the starting minimum; 64–128 GB is more comfortable for local music. The kit already includes a USB card reader. |
| Pi 4 heatsinks/cooling | 1 set; included in kit | [Search: Pi 4 heatsinks](https://www.amazon.com/s?k=Raspberry+Pi+4+heatsink+set) | The kit includes heatsinks and a fan/case. Preserve airflow when moving into a display enclosure. A fan is optional if passive cooling remains adequate under load. |
| Micro-HDMI to full-size HDMI cable | 1; display cable included in kit | [Search: short Pi 4 micro-HDMI cable](https://www.amazon.com/s?k=micro+HDMI+to+HDMI+cable+1+foot+Raspberry+Pi+4) | Pi 4 uses **micro-HDMI**, not mini-HDMI. A short flexible cable is easier to route than the kit's six-foot cable. |
| USB touch/power cable for display | 1, unless supplied with panel | [Search: USB-A to micro-USB data cable](https://www.amazon.com/s?k=USB+A+to+micro+USB+data+cable+1+foot) | The existing Deck panel uses HDMI for video and USB for both touch and power; it has no separate power input. Match a replacement panel's actual USB connector, which may differ. A charge-only cable loses touch. |
| Waveshare USB TO AUDIO sound card | 1 | [Product, $14.99](https://www.amazon.com/dp/B08R38TXXL) | Exact purchased model. Includes a codec, onboard microphone hardware, and **amplified speaker outputs**. This is not just a headphone dongle. |
| USB 2.0 mini microphone | 1 | [Product: SuziePi two-pack, $9.59](https://www.amazon.com/dp/B0CYM618H7) | Exact purchased listing. Use one mic; keep the second as a spare. The sound card's onboard microphones are another input option, so this separate mic can be omitted if that placement performs well. Two USB mics do not automatically form an array. |
| Passive speaker | 1 | [Product: CQRobot enclosed 8-ohm, 3 W pair, $7.99](https://www.amazon.com/dp/B0738NLFTG) | Retail alternative with PH2.0 leads matching the audio board's connector family. One pair can serve both endpoints. The photographed Deck uses another salvaged Google Home Mini speaker instead. |
| PH2.0 2-pin speaker pigtail | 1, if using the donor speaker | [Search: PH2.0 speaker pigtails](https://www.amazon.com/s?k=JST+PH2.0+2+pin+speaker+connector+pigtail) | Usually unnecessary with the linked CQRobot speaker. Check connector orientation and the audio board's channel labels. |
| Arducam IMX519 16 MP autofocus camera with ABS case | 1 for camera features | [Product, $29.99](https://www.amazon.com/dp/B09STL7S88) | Exact purchased model. Select **IMX519 Autofocus with Case**. Not needed for music/voice alone. Requires the correct Pi camera software and overlay. |
| Pi 4 CSI camera ribbon | 1; camera package lists an FPC cable | [Search: 15-pin Pi 4 camera ribbon](https://www.amazon.com/s?k=Raspberry+Pi+4+camera+ribbon+cable+15+pin+15cm) | Only buy an extra if more length is needed or the included cable is unsuitable. Pi 4's connector is 15-pin; do not substitute a Pi 5-only 22-pin cable. Install with Pi power disconnected. |
| Powered USB hub | Optional, 1 | [Product: Sabrent HB-UMP3, $19.99](https://www.amazon.com/dp/B00TPMEOYM) | Candidate with four data ports and a 5 V / 2.5 A supply. Useful when the display and audio peripherals overload the Pi's shared USB power budget. Verify per-port requirements and no upstream back-powering in the final arrangement. Keep the Pi on its own supply. This hub has not been tested in the build. |
| Short USB-A extension lead | Optional, 1–2 | [Search: USB-A male/female extension](https://www.amazon.com/s?k=short+USB+A+male+female+extension+cable+1+foot) | Moves the audio board or mic away from crowded ports and helps place the mic away from the speaker. |
| M2.5 Pi mounting standoffs and screws | 1 set | [Search: M2.5 nylon Pi standoff kit](https://www.amazon.com/s?k=M2.5+nylon+standoff+kit+Raspberry+Pi) | Pi mounting hardware, separate from the Mini's M2/M3 kit. Select height after checking PCB clearance and mounting material. |
| Frame/backing plate | 1, for a frame-style prototype | [Search: deep shadow-box frame](https://www.amazon.com/s?k=deep+shadow+box+frame) | Choose only after measuring the complete panel and connectors. Nominal screen diagonal is not enough to size a frame. The Deck Blender enclosure is a concept, not a print-ready housing. |

### Screen identity and camera expectations

The installed Deck panel is documented as **1024 × 600, HDMI video, USB touch and
power**. Its exact manufacturer/model and diagonal have not been established.
The linked 7-inch panel is a purchasable alternative, not a claimed match to the
existing approximately 8-inch assembly. Do not order a replacement frame or
commit to enclosure dimensions until the actual panel is measured.

The IMX519 uses the CSI camera stack. Working sensor capture does not by itself
guarantee Chromium/Google Meet support. See [camera and audio bring-up](AV_BRINGUP.md)
for the driver, focus, browser, and calling checks.

## Mini enclosure and shared assembly supplies

| Item | Quantity to buy/use | Link | Notes |
| --- | --- | --- | --- |
| M2/M3 screw, nut, and washer kit | 1 kit | [Product: Taiss 540-piece kit, $9.99](https://www.amazon.com/dp/B0D6R67GHD) | Listing includes 6/8/10/12/16/20 mm M2 and M3 screws, nuts, washers, and hex keys. Contains enough of every size below for one Mini. |
| 405 nm tough/ABS-like resin | 1 bottle, if printing in resin | [Search: ABS-like 405 nm resin](https://www.amazon.com/s?k=405nm+ABS+like+resin+500g) | Choose a material/profile suited to the printer and flexible catches. The full standard model volume is about 42.08 mL before supports and losses; a whole bottle is not consumed by one build. A printing service is also an option. |
| Thin compliant display gasket/tape | Small strips | [Search: 0.3 mm silicone gasket sheet](https://www.amazon.com/s?k=silicone+rubber+sheet+0.3mm) | Target 0.2–0.3 mm at the inactive glass rim. Thick foam tape changes the fit. Verify actual thickness and use a suitable attachment method. |
| Narrow cable ties | Small pack | [Search: 2.5 mm nylon cable ties](https://www.amazon.com/s?k=2.5mm+nylon+cable+ties) | Rear wire routing and strain relief; soft straps can restrain the optional battery. |
| Flexible hookup wire | Small assortment | [Search: 24 AWG stranded silicone wire](https://www.amazon.com/s?k=24+AWG+stranded+silicone+hookup+wire) | For speaker adapters and tidy short wiring. Size battery wiring for its actual current separately. |
| Heat-shrink tubing | Small assortment | [Search: small heat-shrink assortment](https://www.amazon.com/s?k=heat+shrink+tubing+assortment+small+electronics) | Insulate splices and prevent exposed contacts. |
| Removable mounting/strain-relief supplies | As needed | [Search: adhesive cable tie mounts](https://www.amazon.com/s?k=small+adhesive+cable+tie+mounts) | Useful for the Deck frame; do not obstruct vents, microphones, or the speaker cone. |
| Rubber feet | Optional, 4 per freestanding build | [Search: self-adhesive silicone feet](https://www.amazon.com/s?k=self+adhesive+silicone+rubber+feet) | Add stability and protect furniture. |

Use these quantities from the screw kit for one standard Crescent enclosure:

| Fastener | Qty |
| --- | ---: |
| M2 × 8 mm screws | 4 |
| M2 hex nuts | 4 |
| M3 × 12 mm screws | 4 |
| M3 × 8 mm screws | 4 |
| M3 hex nuts | 8 |
| M3 flat washers | 12 |

With the optional 4 mm speaker spacers, replace the four M3 × 8 screws with four
additional M3 × 12 screws. The linked kit still contains enough.

Download the [Crescent STL files](../enclosure/crescent-v1/STL/) and follow the
[print and assembly walkthrough](../enclosure/crescent-v1/PRINT_AND_ASSEMBLY.md).
Print one main stand, one ring, two button plungers, two keepers, four speaker
arms, and four posts for the standard assembly. Check the fit kit before printing
the complete stand. A retail rectangular speaker needs a revised mounting solution.

## Tools to share across both builds

Borrow or reuse these; there is no need to buy a tool set per endpoint.

- [Precision screwdriver/hex driver set](https://www.amazon.com/s?k=precision+screwdriver+hex+driver+set+electronics).
- [Temperature-controlled soldering iron](https://www.amazon.com/s?k=temperature+controlled+soldering+iron+electronics), [electronics solder](https://www.amazon.com/s?k=electronics+rosin+core+solder), and [flush cutters/wire stripper](https://www.amazon.com/s?k=precision+wire+stripper+flush+cutter+electronics) if adapting donor speakers.
- [Digital multimeter](https://www.amazon.com/s?k=digital+multimeter+continuity+resistance) for polarity, continuity, and resistance checks; DC resistance is not the speaker's nominal impedance rating.
- [Digital calipers](https://www.amazon.com/s?k=digital+caliper+150mm) for connector, panel, and enclosure fit.
- [USB microSD reader](https://www.amazon.com/s?k=USB+microSD+card+reader) if one is not already available or included in a Pi kit.
- If resin printing at home: [nitrile gloves](https://www.amazon.com/s?k=nitrile+gloves), [wash/cure equipment](https://www.amazon.com/s?k=resin+print+wash+cure+station), and the resin manufacturer's specified wash supplies and ventilation arrangements. The files include Photon Mono M7 orientations; buying that printer is not required if using a print service.

## Avoid duplicate or incompatible purchases

- The Mini's screen, touch sensor, microphones, and amplifier are already on its board. No extra USB sound card or microphone is required for Mini.
- The Pi kit already supplies a 32 GB card, reader, power supply, display cable, heatsinks, case, and fan. The 128 GB card, shorter HDMI cable, and separate PSU rows are alternatives/upgrades.
- One CQRobot speaker pair supplies one speaker per build. The USB microphone two-pack provides one Deck mic and a spare.
- The Mini speaker/battery headers are **MX1.25 2-pin**. The Deck sound card uses **PH2.0**. Connector colour does not establish polarity.
- Connect a passive Deck speaker across one amplified channel's two terminals. Do not combine channels or connect either speaker lead to ground. The Pi headphone jack cannot replace a speaker power amplifier, and it is not a microphone input.
- The current USB audio/CSI build does not require the breadboard, GPIO ribbon, or breakout board seen in some early assembly photos.
- Keep the optional battery and final enclosure work separate from the first USB-powered bench build. No battery or portable power system is specified for Deck.

## Sources

- [Waveshare round AMOLED board specifications](https://www.waveshare.com/esp32-s3-touch-amoled-1.75.htm), including its MX1.25 speaker and 3.7 V battery connectors.
- [Waveshare USB TO AUDIO](https://www.waveshare.com/usb-to-audio.htm) and [manual](https://www.waveshare.com/wiki/USB_TO_AUDIO).
- Project [hardware guide](HARDWARE.md), [build options](BUILD_OPTIONS.md), [Deck AV guide](AV_BRINGUP.md), and [Crescent assembly guide](../enclosure/crescent-v1/PRINT_AND_ASSEMBLY.md).
