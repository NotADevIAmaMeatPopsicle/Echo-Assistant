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

Install PlatformIO in an isolated environment, then run `pio run -e round_voice`.
The pinned pioarduino platform downloads the required compiler/framework.
`PLATFORMIO_CORE_DIR` can override PlatformIO's standard cache directory.
Never commit `.pio/`, full flash dumps or device-specific pairing state.

Before any first flash, use esptool to identify your port/chip/MAC and read the
complete **16 MiB** flash into `backups/original.bin`. Hash that file with SHA-256
and retain both the hash and backup privately. esptool command spelling depends
on its installed version; use its help for `read_mac` and `read_flash`.

Stop the voice bridge and any other serial owner. This explicit flash command
requires your own board identity and verified original backup:

```powershell
./.venv/Scripts/python.exe tools/flash_device.py YOUR_PORT --mac YOUR_BOARD_MAC --backup backups/original.bin --backup-sha256 YOUR_BACKUP_SHA256
```

The script checks USB VID/PID, chip identity, backup hash, image hashes and partition
layout before writing. It writes a **DIO / 80 MHz / 16 MB** bootloader header;
the application retains `qio_opi` for its PSRAM configuration. Do not substitute
a generic ESP32 upload recipe. `--bundle` selects a previously verified archive.

The upper button toggles software mic mute on Home/Echo. On speaker pages the
buttons adjust the selected speaker's volume; on thermostat pages they adjust
the target temperature. Long holds preserve the board's power/boot functions.

Battery/charging reporting is read-only. The firmware does not change PMIC charge
current or voltage, and does not format the SD card. An absent battery is shown
as absent, not as 0%. Battery operation and charging still need broader physical
acceptance. Use a battery compatible with the vendor board specification.

References: [Waveshare board documentation](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.75),
[vendor BSP](https://github.com/waveshareteam/Waveshare-ESP32-components).
