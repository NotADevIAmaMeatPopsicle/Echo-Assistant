"""Flash the verified round board using the existing cached esptool (no downloads)."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.firmware_bundle import create_bundle, load_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument('--mac', required=True, help='MAC reported by esptool read_mac')
    parser.add_argument('--backup', type=Path, required=True, help='Your full 16 MiB original flash backup')
    parser.add_argument('--backup-sha256', required=True)
    parser.add_argument('--bundle', type=Path, help='Restore a verified archived bundle instead of the latest build')
    args = parser.parse_args()
    MAC = args.mac.lower()
    BACKUP_HASH = args.backup_sha256.lower()
    if (ROOT/'local/voice-process.json').exists():
        raise SystemExit('Stop the voice bridge before flashing; run tools/run.ps1 stop')
    backup = args.backup
    if not backup.is_file() or backup.stat().st_size != 16 * 1024 * 1024:
        raise SystemExit("Complete original flash backup is missing; refusing to flash")
    with backup.open("rb") as stream:
        backup_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if backup_hash != BACKUP_HASH:
        raise SystemExit("Original backup hash mismatch; refusing to flash")
    # Validate/archive all images before touching the USB device. Restoring a
    # bundle does not depend on the current build directory or framework files.
    try:
        directory = args.bundle or create_bundle()[0]
        manifest, images = load_bundle(directory)
    except (OSError, ValueError) as error:
        raise SystemExit('Firmware validation failed; no device writes: '+str(error)) from None
    matches = [p for p in list_ports.comports() if p.device == args.port
               and (p.vid, p.pid) == (0x303A, 0x1001)
               and (p.serial_number or "").lower() == MAC]
    if len(matches) != 1:
        raise SystemExit("Unexpected or absent USB device; refusing to flash")
    packages = Path(__import__('os').environ.get('PLATFORMIO_CORE_DIR', str(Path.home()/'.platformio')))/'packages'
    esptool = packages / "tool-esptoolpy/esptool.py"
    if not esptool.is_file() or not all(p.is_file() for _, p in images):
        raise SystemExit("Cached tool or build artifact missing; run the build first")
    base = [sys.executable, str(esptool), "--chip", "esp32s3", "--port", args.port,
            "--baud", "921600", "--before", "default_reset", "--after", "hard_reset"]
    probe = subprocess.run(base + ["read_mac"], capture_output=True, text=True, check=True)
    if "MAC: " + MAC not in probe.stdout:
        raise SystemExit("Chip MAC did not match; refusing to flash")
    print("Verified ESP32-S3 identity and complete original backup", flush=True)
    print('Firmware bundle:', str(directory), 'version:', manifest['version'], flush=True)
    print("Application SHA256:", hashlib.sha256(images[-1][1].read_bytes()).hexdigest(), flush=True)
    # ROM bootloader requires DIO. QIO here caused an ets_loader.c 78 boot loop.
    # qio_opi remains the app/PSRAM memory configuration in platformio.ini.
    command = base + ["write_flash", "-z", "--flash_mode", "dio", "--flash_freq", "80m",
                      "--flash_size", "16MB"]
    for address, path in images:
        command.extend([address, str(path)])
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
