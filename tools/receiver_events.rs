// Included in the pinned receiver by build_receiver.py. No child process or audio pipe.
fn round_voice_json_string(value: &str) -> String {
    let mut output = String::from("\"");
    for character in value.chars().take(400) {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\u{0}'..='\u{1f}' => output.push_str(&format!("\\u{:04x}", character as u32)),
            _ => output.push(character),
        }
    }
    output.push('"');
    output
}

pub fn round_voice_event(fields: &std::collections::HashMap<&str, String>) {
    let Some(kind) = fields.get("PLAYER_EVENT") else { return };
    if !matches!(kind.as_str(), "receiver_ready" | "track_changed" | "playing" | "paused"
        | "stopped" | "session_connected" | "session_disconnected" | "volume_changed"
        | "seeked" | "position_correction" | "shuffle_changed" | "repeat_changed") { return; }
    let Ok(key) = std::env::var("ROUND_VOICE_EVENT_KEY") else { return };
    if key.len() < 32 || key.len() > 128 { return; }
    let Some(port) = std::env::var("ROUND_VOICE_EVENT_PORT").ok()
        .and_then(|value| value.parse::<u16>().ok()).filter(|port| *port >= 1024) else { return };
    let mut body = format!("{{\"key\":{},\"event\":{}", round_voice_json_string(&key), round_voice_json_string(kind));
    // Current-track presentation only. Never forward account, connection or local file paths.
    for (source, target) in [("NAME", "name"), ("ARTISTS", "artists"), ("DURATION_MS", "duration_ms"),
        ("POSITION_MS", "position_ms"), ("VOLUME", "volume"), ("UI_VERSION", "ui_version"),
        ("ALBUM", "album"), ("COVERS", "covers"), ("URI", "uri"), ("ITEM_TYPE", "item_type"),
        ("SHOW_NAME", "show_name"), ("IS_EXPLICIT", "is_explicit"), ("SHUFFLE", "shuffle"),
        ("REPEAT", "repeat"), ("REPEAT_TRACK", "repeat_track")] {
        if let Some(value) = fields.get(source) {
            body.push_str(&format!(",\"{target}\":{}", round_voice_json_string(value)));
        }
    }
    body.push('}');
    let result = std::net::UdpSocket::bind((std::net::Ipv4Addr::LOCALHOST, 0))
        .and_then(|socket| socket.send_to(body.as_bytes(), (std::net::Ipv4Addr::LOCALHOST, port)));
    if result.is_err() { log::warn!("Round Voice event delivery failed"); }
}

#[cfg(test)]
mod round_voice_tests {
    #[test]
    fn event_strings_escape_json_and_bound_metadata() {
        assert_eq!(super::round_voice_json_string("quote\"\\\n\u{0}é"), "\"quote\\\"\\\\\\u000a\\u0000é\"");
        assert_eq!(super::round_voice_json_string(&"x".repeat(500)).len(), 402);
    }
}
