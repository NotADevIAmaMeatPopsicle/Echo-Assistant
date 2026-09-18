"""Optional, explicitly configured Home Assistant bridge. No discovery or cloud fallback."""
from dataclasses import dataclass, field
from ipaddress import ip_address, ip_network
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
import httpx
from .core import spoken_number


class HomeUnavailable(Exception):
    pass


@dataclass
class HomeConfig:
    enabled: bool = False
    base_url: str = ""
    token: str = field(default="", repr=False)
    entities: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        domains = {"thermostat": "climate", "soundbar": "media_player", "weather": "weather"}
        for key, entity in self.entities.items():
            if key not in domains or not re.fullmatch(domains[key] + r"\.[a-z0-9_]+", entity):
                raise ValueError("Invalid home entity binding")
        if not self.enabled:
            return
        url = urlsplit(self.base_url)
        try:
            address = ip_address(url.hostname or "")
            _ = url.port
        except ValueError as error:
            raise ValueError("Home Assistant requires an explicit local IP address") from error
        networks = [ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                            "127.0.0.0/8", "::1/128", "fc00::/7")]
        if (url.scheme not in {"http", "https"} or url.username is not None
                or url.password is not None or url.path not in {"", "/"} or url.query or url.fragment
                or not any(address in network for network in networks)):
            raise ValueError("Home Assistant must use a local origin without credentials or a path")
        if not self.token or not self.entities:
            raise ValueError("Home Assistant token and entity bindings are required")
        self.base_url = self.base_url.rstrip("/")

    @classmethod
    def load(cls, root: Path):
        path = root / "local/home.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        enabled = data.get("enabled", False)
        if type(enabled) is not bool:
            raise ValueError("Home enabled must be a boolean")
        token = (root / "local/ha-token").read_text(encoding="utf-8").strip() if enabled else ""
        return cls(enabled=enabled, base_url=data.get("base_url", ""), token=token,
                   entities=data.get("entities", {}))


class HomeBridge:
    def __init__(self, config: HomeConfig, transport=None):
        self.config = config
        self.transport = transport

    def _request(self, method, path, body=None):
        if not self.config.enabled:
            raise HomeUnavailable("Home integration is not configured")
        # Ignore proxy environment variables; never redirect the HA credential elsewhere.
        try:
            with httpx.Client(transport=self.transport, timeout=3, trust_env=False,
                              follow_redirects=False) as client:
                response = client.request(method, self.config.base_url + path, json=body,
                    headers={"Authorization": "Bearer " + self.config.token})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            # Responses can contain private details. Return a content-free error.
            raise HomeUnavailable("Home Assistant is unavailable or rejected the request") from error

    def _state(self, key):
        if key not in self.config.entities:
            raise ValueError("Device is not configured")
        state = self._request("GET", "/api/states/" + self.config.entities[key])
        if not isinstance(state, dict) or not isinstance(state.get("attributes"), dict):
            raise HomeUnavailable("Invalid device state")
        if not isinstance(state.get("state"), str) or state["state"] in {"unavailable", "unknown"}:
            raise HomeUnavailable("Device is unavailable")
        return state

    def snapshot(self):
        status = "configured" if self.config.enabled else "not_configured"
        devices = {}
        fields = {
            "thermostat": ("current_temperature", "temperature", "target_temp_low", "target_temp_high",
                           "current_humidity", "hvac_action", "hvac_modes", "min_temp", "max_temp"),
            "soundbar": ("volume_level", "is_volume_muted", "media_title", "supported_features"),
            "weather": ("temperature", "temperature_unit", "humidity"),
        }
        for key in self.config.entities:
            try:
                state = self._state(key)
                attrs = {k: v for k, v in state["attributes"].items() if k in fields[key]}
                if key == "thermostat":
                    attrs["temperature_unit"] = self._request("GET", "/api/config").get("unit_system", {}).get("temperature")
                devices[key] = {"status": "available", "state": state["state"], "attributes": attrs}
            except HomeUnavailable:
                devices[key] = {"status": "unavailable" if self.config.enabled else "not_configured"}
        return {"status": status, "devices": devices}

    def answer(self, text):
        query = re.sub(r"\s+", " ", text.strip().lower().rstrip("?.!").replace('%', ' percent')).strip()
        query = re.sub(r"\bsound bar\b", "soundbar", query)
        queries = {
            "what is the temperature": "thermostat", "what's the temperature": "thermostat",
            "what is the indoor temperature": "thermostat", "what is the thermostat set to": "thermostat",
            "what is the soundbar status": "soundbar", "is the soundbar on": "soundbar",
            "what is the soundbar volume": "soundbar", "what's the soundbar volume": "soundbar",
            "is the soundbar muted": "soundbar",
            "what is the weather": "weather", "what's the weather": "weather",
        }
        device = queries.get(query)
        if device is None:
            return self.command(query)
        try:
            state = self._state(device)
            attrs = state["attributes"]
            if device == "thermostat":
                units = self._request("GET", "/api/config").get("unit_system", {}).get("temperature", "")
                current, target = attrs.get("current_temperature"), attrs.get("temperature")
                if not _number(current): raise HomeUnavailable("Temperature unavailable")
                message = f"Indoors {current:g}{units}"
                if _number(target): message += f", set {target:g}{units}"
            elif device == "soundbar":
                if query in {"what is the soundbar volume", "what's the soundbar volume"}:
                    volume = attrs.get("volume_level")
                    if not _number(volume) or not 0 <= volume <= 1:
                        raise HomeUnavailable("Soundbar volume unavailable")
                    message = f"Soundbar volume is {round(volume * 100)} percent."
                elif query == "is the soundbar muted":
                    muted = attrs.get("is_volume_muted")
                    if type(muted) is not bool: raise HomeUnavailable("Soundbar mute state unavailable")
                    message = "Soundbar is muted." if muted else "Soundbar is not muted."
                else:
                    message = "Soundbar is " + state["state"]
            else:
                temperature = attrs.get("temperature")
                if not _number(temperature): raise HomeUnavailable("Weather unavailable")
                message = f"Outside {temperature:g}{attrs.get('temperature_unit', '')}"
            return {"status": "complete", "capability": "home", "text": message}
        except (HomeUnavailable, ValueError):
            return {"status": "unavailable", "capability": "home", "text": "Home device unavailable"}

    def command(self, query):
        # Small explicit grammar; never guess a device or interpret arbitrary
        # conversation as a service call. Existing act() validates fresh state.
        match = re.fullmatch(r"set (?:the )?thermostat to ([a-z0-9]+(?: [a-z]+)?) degrees(?: (fahrenheit|celsius))?", query)
        sound = re.fullmatch(r"(play|pause|stop|turn on|turn off) (?:the )?soundbar", query)
        mode = re.fullmatch(r"set (?:the )?thermostat (?:mode )?to (heat|cool|off|auto)", query)
        volume = re.fullmatch(r"set (?:the )?soundbar volume to ([a-z0-9]+(?: [a-z]+)?) percent", query)
        mute = re.fullmatch(r"(mute|unmute) (?:the )?soundbar", query)
        step = (re.fullmatch(r"turn (?:the )?soundbar volume (up|down)", query)
                or re.fullmatch(r"turn (up|down) (?:the )?soundbar(?: volume)?", query))
        track = re.fullmatch(r"(?:play )?(?:the )?(next|previous) (?:track|song) on (?:the )?soundbar", query)
        if not (match or sound or mode or volume or mute or step or track): return None
        try:
            if match:
                value = spoken_number(match[1])
                if value is None: raise ValueError("Temperature was not understood")
                unit = {"fahrenheit": "°F", "celsius": "°C"}.get(match[2])
                if not unit: unit = self._request("GET", "/api/config").get("unit_system", {}).get("temperature")
                self.act("thermostat", "set_temperature", value, unit)
                message = f"Requested {value} degrees {'Fahrenheit' if unit == '°F' else 'Celsius'} on the thermostat."
            elif mode:
                self.act("thermostat", "set_mode", mode[1])
                message = "Requested thermostat mode " + mode[1] + "."
            elif volume:
                percent = 100 if volume[1] in {"hundred", "one hundred"} else spoken_number(volume[1])
                if percent is None or not 0 <= percent <= 100:
                    raise ValueError("Volume must be zero to one hundred percent")
                self.act("soundbar", "volume", percent / 100)
                message = f"Requested soundbar volume {percent} percent."
            elif mute:
                self.act("soundbar", "mute", mute[1] == "mute")
                message = "Sent the " + mute[1] + " command to the soundbar."
            elif step:
                self.act("soundbar", "adjust_volume", .02 if step[1] == "up" else -.02)
                message = "Requested soundbar volume " + step[1] + " two percent."
            elif track:
                self.act("soundbar", track[1])
                message = "Sent the " + track[1] + " track command to the soundbar."
            else:
                self.act("soundbar", sound[1].replace(" ", "_"))
                message = "Sent the " + sound[1] + " command to the soundbar."
            return {"status": "accepted", "capability": "home", "text": message}
        except HomeUnavailable:
            return {"status": "unavailable", "capability": "home", "text": "Home Assistant could not reach that device."}
        except ValueError:
            return {"status": "unavailable", "capability": "home", "text": "That setting is not supported by the device."}

    def act(self, device, action, value=None, unit=None):
        state = self._state(device)  # Fresh state: never act on stale temperature bounds/modes.
        attrs = state["attributes"]
        data = {"entity_id": self.config.entities[device]}
        if device == "thermostat":
            if action in {"set_temperature", "adjust_temperature"}:
                ha_config = self._request("GET", "/api/config")
                actual_unit = ha_config.get("unit_system", {}).get("temperature")
                if unit not in {"°F", "°C"} or unit != actual_unit:
                    raise ValueError("Temperature unit must match Home Assistant")
                if action == "adjust_temperature":
                    if not _number(value) or value not in {-.5, .5, -1, 1} or not _number(attrs.get("temperature")):
                        raise ValueError("Temperature adjustment must be a single small step")
                    value += attrs["temperature"]
                low, high = attrs.get("min_temp"), attrs.get("max_temp")
                if not all(_number(v) for v in (low, high, value)) or not low <= value <= high:
                    raise ValueError("Temperature must be within the device's current bounds")
                if state["state"] == "heat_cool":
                    raise ValueError("Range mode requires separate high and low targets; not implemented")
                data["temperature"] = value
                service = "climate/set_temperature"
            elif action == "set_mode" and value in attrs.get("hvac_modes", []):
                if not isinstance(value, str):
                    raise ValueError("HVAC mode must be a string")
                data["hvac_mode"] = value
                service = "climate/set_hvac_mode"
            else:
                raise ValueError("Unsupported thermostat action or mode")
        elif device == "soundbar":
            features = attrs.get("supported_features", 0)
            if type(features) is not int or features < 0:
                raise HomeUnavailable("Device capabilities unavailable")
            actions = {"play": ("media_play", 16384), "pause": ("media_pause", 1),
                       "stop": ("media_stop", 4096), "previous": ("media_previous_track", 16),
                       "next": ("media_next_track", 32), "turn_on": ("turn_on", 128),
                       "turn_off": ("turn_off", 256), "volume": ("volume_set", 4),
                       "mute": ("volume_mute", 8), "adjust_volume": ("volume_set", 4)}
            if action not in actions or not features & actions[action][1]:
                raise ValueError("Soundbar does not currently support that action")
            service = "media_player/" + actions[action][0]
            if action in {"volume", "adjust_volume"}:
                if action == "adjust_volume":
                    current = attrs.get('volume_level')
                    if not _number(value) or value not in {-.02, .02}:
                        raise ValueError("Volume adjustment must be a two percent step")
                    if not _number(current) or not 0 <= current <= 1:
                        raise HomeUnavailable("Current soundbar volume is unavailable")
                    value = round(max(0, min(1, current + value)), 4)
                if not _number(value) or not 0 <= value <= 1:
                    raise ValueError("Volume must be between zero and one")
                data["volume_level"] = value
            elif action == "mute":
                if type(value) is not bool:
                    raise ValueError("Mute must be a boolean")
                data["is_volume_muted"] = value
            elif value is not None:
                raise ValueError("This action does not take a value")
        else:
            raise ValueError("This device is read-only")
        self._request("POST", "/api/services/" + service, data)
        # HA accepting a service call is not proof of physical actuation.
        return {"status": "accepted", "device": device, "action": action}


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)
