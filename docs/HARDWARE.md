# Waveshare ESP32-S3-Touch-AMOLED-1.75

Target: ESP32-S3 with 16 MB flash and 8 MB octal PSRAM, 466 × 466 CO5300 display.

| Peripheral | Wiring |
| --- | --- |
| CO5300 QSPI | CS12, CLK38, D0/1/2/3 = 4/5/6/7, reset39 |
| CST9217 touch | SDA15, SCL14, reset40, IRQ11, I2C 0x5A |
| ES7210 microphone ADC | I2C 0x40, I2S DIN10 |
| ES8311 output codec | I2C 0x18, I2S DOUT8 |
| Audio clocks | BCLK9, WS45, MCLK42 |
| Speaker amplifier | GPIO46 high enables output |
| SDMMC, one bit | CLK2, CMD1, D0=3 |
| AXP2101 PMIC | I2C 0x34 |
| Upper PWR button | TCA9554 0x20, EXIO4, active high |
| Lower BOOT button | GPIO0, active low |

## Build and flash

### Screen protection

The current firmware adds **Settings → Screen** with independent dim/dark timers
(2 and 10 minutes by default), Never choices, and Sleep now. Dark sets the OLED's
brightness to zero and stops frame rendering; it does not suspend the ESP32 or
its audio/network tasks. Touch once to wake without activating a hidden control.
An accepted wake word, active conversation/call or alarm restores visibility.
Music alone may continue with the screen dark. Brightness and timer choices persist.
The upper button on Home/Echo still toggles microphone mute immediately, even
while dark; a physical button on a device-control page wakes first.

This is separate from the Deck's HDMI settings. New firmware must be installed
on the Mini before these controls appear. Hardware dark/wake and continued-audio
acceptance remain required; there is no configured presence sensor.

### Firmware installation

Firmware 0.19.0 adds [personal sign-in](PERSONAL_ACCOUNTS.md#sign-in-on-mini),
retaining [calendar review](ROUND_CALENDAR.md), screen protection,
intercom and timed group audio. The host detects the review capability explicitly.
Installation and physical acceptance of these additions are still required.

After the host setup has created `.venv`, install and run PlatformIO there:

```powershell
./.venv/Scripts/python.exe -m pip install platformio==6.1.18
./.venv/Scripts/python.exe -m platformio run -e round_voice
```

The pinned pioarduino platform downloads the required compiler/framework.
`PLATFORMIO_CORE_DIR` can override PlatformIO's standard cache directory.
Never commit `.pio/`, full flash dumps or device-specific pairing state.

Before the first flash, identify the board and save its complete **16 MiB** flash.
Close serial monitors and stop any running Echo bridge. List attached ports:

```powershell
./.venv/Scripts/python.exe -m serial.tools.list_ports -v
```

Use the ESP32-S3 USB device's port in place of `YOUR_PORT` below. The PlatformIO
build supplies the esptool version used by the flash helper. These commands
resolve that same cache rather than assuming a particular user's installation:

```powershell
$echoPioRoot = if ($env:PLATFORMIO_CORE_DIR) { $env:PLATFORMIO_CORE_DIR } else { Join-Path $env:USERPROFILE '.platformio' }
$echoEsptool = Join-Path $echoPioRoot 'packages/tool-esptoolpy/esptool.py'
./.venv/Scripts/python.exe $echoEsptool --chip esp32s3 --port YOUR_PORT read_mac
New-Item -ItemType Directory -Force backups | Out-Null
./.venv/Scripts/python.exe $echoEsptool --chip esp32s3 --port YOUR_PORT read_flash 0 0x1000000 backups/original.bin
Get-FileHash -LiteralPath backups/original.bin -Algorithm SHA256
```

For an existing build, keep the original backup intact and use a new filename
for a later backup. Retain the file, SHA-256, and reported MAC privately.

Stop the voice bridge and any other serial owner. This explicit flash command
requires your own board identity and verified original backup:

```powershell
./.venv/Scripts/python.exe tools/flash_device.py YOUR_PORT --mac YOUR_BOARD_MAC --backup backups/original.bin --backup-sha256 YOUR_BACKUP_SHA256
```

The script checks USB VID/PID, chip identity, backup hash, image hashes and partition
layout before writing. It writes a **DIO / 80 MHz / 16 MB** bootloader header;
the application retains `qio_opi` for its PSRAM configuration. Do not substitute
a generic ESP32 upload recipe. `--bundle` selects a previously verified archive.

Before starting the host, set the verified MAC in the same PowerShell session:

```powershell
$env:ECHO_DEVICE_MAC = 'YOUR_BOARD_MAC'
```

Use the colon-separated MAC printed by esptool, not the placeholder. Set it again
in a new terminal session before launching the host. Return to
[local setup](SETUP.md) for startup and the authenticated web launcher.

The upper button toggles software mic mute on Home/Echo. On speaker pages the
buttons adjust the selected speaker's volume; on thermostat pages they adjust
the target temperature. Long holds preserve the board's power/boot functions.

Battery/charging reporting is read-only. The firmware does not change PMIC charge
current or voltage, and does not format the SD card. An absent battery is shown
as absent, not as 0%. Battery operation and charging still need broader physical
acceptance. Use a battery compatible with the vendor board specification.

References: [Waveshare board documentation](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.75),
[vendor BSP](https://github.com/waveshareteam/Waveshare-ESP32-components).
