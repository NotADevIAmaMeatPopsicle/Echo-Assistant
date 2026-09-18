# Home Assistant

Echo uses your existing Home Assistant installation. It does not install HA or
import Google Home devices automatically. Devices need to be exposed through HA.

Copy `config/home.example.json` to `local/home.json`, configure your server and
the optional thermostat/speaker/weather entities, and set `enabled` to true.
Supply a Home Assistant long-lived token in `local/ha-token` using a local editor;
never put it in a command line, issue or commit. These files are private runtime
inputs. Use an account with only the access you intend Echo to have.

Open **Devices** in the signed-in Echo UI. Choose Read state, Control or Hidden
for individual supported entities, and save. New devices do not inherit Control.
Room assignments can be set in Echo without modifying HA's registry. Unassigned
room buttons remain unavailable rather than guessing which lights they represent.

The Hermes MCP server `echo-home` exposes `home_devices`, `home_state` and
`home_action`. It reads fresh capabilities, validates exact targets and bounds,
and reports verified, accepted or unconfirmed results honestly. Current actions
cover lights, switches, thermostats, media players and scenes.

Conversational actions require both a device Control grant and an active Echo
request. In web chat, enable **Allow home actions for this message**. The native
Hermes dashboard can read HA state, but does not create Echo's action scope;
use Echo's voice/chat interface for control. Display buttons have their own
explicit action routes. No generic shell or arbitrary HA-service tool is needed.

Routines store exact targets and settings encrypted on the host. Saving a routine
does not run it. Stop cancels remaining actions and cannot undo an action already
sent to an appliance. Ambiguous command results are not automatically retried.
