"""Build pinned librespot with a private stdin control pipe; no extra network API."""
import hashlib
import io
import os
import shutil
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SHA256 = '030c5e98cc06f20283b5948ae23bdac1de0dec58dee2c5ec4c8dafc7aaa796ab'
VERSION = '0.8.0'
SETUP = '''    // Round Voice: only the parent process owns this bounded control pipe.
    player_event_handler::round_voice_event(&std::collections::HashMap::from([
        ("PLAYER_EVENT", "receiver_ready".to_owned()),
        ("UI_VERSION", "2".to_owned()),
    ]));
    let (control_tx, mut control_rx) = tokio::sync::mpsc::channel::<String>(16);
    std::thread::spawn(move || {
        use std::io::BufRead;
        for line in std::io::stdin().lock().lines() {
            let Ok(line) = line else { break };
            if line.len() <= 32 && control_tx.blocking_send(line).is_err() { return; }
        }
        let _ = control_tx.blocking_send("shutdown".into());
    });
'''
BRANCH = '''            control = control_rx.recv() => {
                let Some(control) = control else { break };
                if control == "shutdown" { break; }
                if let Some(ref receiver) = spirc {
                    let _ = match control.as_str() {
                        "play" => receiver.play(),
                        "pause" => receiver.pause(),
                        "toggle" => receiver.play_pause(),
                        "next" => receiver.next(),
                        "previous" => receiver.prev(),
                        "transfer" => receiver.transfer(None),
                        "shuffle true" => receiver.shuffle(true),
                        "shuffle false" => receiver.shuffle(false),
                        "repeat off" => { let _ = receiver.repeat_track(false); receiver.repeat(false) },
                        "repeat context" => { let _ = receiver.repeat_track(false); receiver.repeat(true) },
                        "repeat track" => receiver.repeat_track(true),
                        value if value.starts_with("seek ") => {
                            let Some(position) = value[5..].parse::<u32>().ok().filter(|v| *v <= 86400000) else { continue };
                            receiver.set_position_ms(position)
                        },
                        value if value.starts_with("volume ") => {
                            let Some(volume) = value[7..].parse::<u32>().ok().filter(|v| *v <= 100) else { continue };
                            receiver.set_volume((volume * 65535 / 100) as u16)
                        },
                        _ => continue,
                    };
                }
            },
'''


def main():
    runtime = ROOT/'local/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    archive = runtime/f'librespot-{VERSION}.crate'
    if not archive.exists():
        with urllib.request.urlopen(f'https://static.crates.io/crates/librespot/librespot-{VERSION}.crate', timeout=30) as response:
            archive.write_bytes(response.read(4*1024*1024))
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256: raise SystemExit('Receiver source checksum mismatch')
    source = runtime/'receiver-source'
    source.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        # Debian's Rust image includes Python 3.11 before tar's data filter.
        # Extract only plain files/directories inside the verified source root.
        for member in tar:
            target = source/member.name
            if not target.resolve().is_relative_to(source.resolve()):
                raise SystemExit('Receiver archive contains an unsafe path')
            if member.isdir(): target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as content, target.open('wb') as output:
                    shutil.copyfileobj(content, output)
            else: raise SystemExit('Receiver archive contains an unsupported entry')
    crate = source/f'librespot-{VERSION}'
    main_path = crate/'src/main.rs'
    original = main_path.read_text(encoding='utf-8')
    marker = '    let mut last_credentials = None;'
    event = '    loop {\n        tokio::select! {\n            credentials = async {'
    if original.count(marker) != 1 or original.count(event) != 1: raise SystemExit('Upstream receiver layout changed')
    modified = original.replace(marker, SETUP+'\n'+marker)
    modified = modified.replace(event, '    loop {\n        tokio::select! {\n'+BRANCH+'            credentials = async {')
    session_ready = '                spirc = Some(spirc_);'
    if modified.count(session_ready) != 1: raise SystemExit('Upstream session initialization changed')
    modified = modified.replace(session_ready, session_ready+'''\n                player_event_handler::round_voice_event(&std::collections::HashMap::from([
                    ("PLAYER_EVENT", "session_connected".to_owned()),
                ]));''')
    main_path.write_text(modified, encoding='utf-8')
    handler_path = crate/'src/player_event_handler.rs'
    handler = handler_path.read_text(encoding='utf-8')
    hook = 'fn run_program(env_vars: HashMap<&str, String>, onevent: &str) {'
    if handler.count(hook) != 1: raise SystemExit('Upstream event handler layout changed')
    handler = handler.replace(hook, hook+'\n    if onevent == "round-voice-events" { round_voice_event(&env_vars); return; }')
    handler_path.write_text((ROOT/'tools/receiver_events.rs').read_text(encoding='utf-8')+'\n'+handler, encoding='utf-8')
    licenses = ROOT/'third_party/licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    (licenses/'librespot-MIT.txt').write_bytes((crate/'LICENSE').read_bytes())
    env = dict(os.environ, CARGO_BUILD_JOBS='2')
    if os.name == 'nt':
        env.update(CARGO_HOME=str(runtime/'cargo'), RUSTUP_HOME=str(runtime/'rustup'))
        cargo = runtime/'cargo/bin/cargo.exe'
    else:
        cargo = shutil.which('cargo')
        if not cargo: raise SystemExit('Use the pinned Rust container to build the Linux receiver')
    subprocess.run([str(cargo), 'build', '--release', '--locked', '--no-default-features',
        '--features', 'native-tls,with-libmdns', '--manifest-path', str(crate/'Cargo.toml'),
        '--target-dir', str(runtime/'receiver-target')], env=env, check=True)
    subprocess.run([str(cargo), 'test', '--release', '--locked', '--no-default-features',
        '--features', 'native-tls,with-libmdns', '--manifest-path', str(crate/'Cargo.toml'),
        '--target-dir', str(runtime/'receiver-target'), 'round_voice_tests'], env=env, check=True)
    binary = runtime/'receiver-target/release'/('librespot.exe' if os.name=='nt' else 'librespot')
    print('Controlled receiver built; SHA256 '+hashlib.sha256(binary.read_bytes()).hexdigest())


if __name__ == '__main__': main()
