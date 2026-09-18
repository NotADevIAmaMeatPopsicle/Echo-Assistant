// ES7210 mic ADC bring-up over I2C. Register map and init sequence ported from the ES7210
// component actually running on this exact board's prior JARVIS firmware
// (Round-AMOLED-Spotify-Test/firmware/jarvis-from-ha, itself based on espressif/esp-bsp and
// esp-adf), NOT reverse-engineered from a datasheet - this sequence is proven working hardware.
//
// I2C address 0x40, on the same bus as touch (SDA=15, SCL=14) - confirmed from that project's
// compiled build output (`adc_bus_a->set_i2c_address(0x40)`), which also resolves what
// Hardware-Inventory's specs.json had logged as an "unknown" I2C device at that address.
#pragma once

#include <stdint.h>

#define ES7210_I2C_ADDR 0x40

// Brings up the ADC for 16-bit/16kHz capture at 37.5dB mic gain (matches Harness's default voice
// rate exactly - no resampling needed downstream). Wire.begin() must already have been called
// (touch_init() does this). Returns false if the chip doesn't ack at ES7210_I2C_ADDR.
bool es7210_init();
