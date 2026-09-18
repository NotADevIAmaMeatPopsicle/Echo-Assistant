#include "es7210.h"

#include <Arduino.h>
#include <Wire.h>

// Register addresses, from the reference component (see es7210.h for provenance).
#define REG_RESET 0x00
#define REG_CLOCK_OFF 0x01
#define REG_MAINCLK 0x02
#define REG_LRCK_DIVH 0x04
#define REG_LRCK_DIVL 0x05
#define REG_POWER_DOWN 0x06
#define REG_OSR 0x07
#define REG_MODE_CONFIG 0x08
#define REG_TIME_CONTROL0 0x09
#define REG_TIME_CONTROL1 0x0A
#define REG_SDP_INTERFACE1 0x11
#define REG_SDP_INTERFACE2 0x12
#define REG_ADC34_HPF2 0x20
#define REG_ADC34_HPF1 0x21
#define REG_ADC12_HPF1 0x22
#define REG_ADC12_HPF2 0x23
#define REG_ANALOG 0x40
#define REG_MIC12_BIAS 0x41
#define REG_MIC34_BIAS 0x42
#define REG_MIC1_GAIN 0x43
#define REG_MIC2_GAIN 0x44
#define REG_MIC3_GAIN 0x45
#define REG_MIC4_GAIN 0x46
#define REG_MIC1_POWER 0x47
#define REG_MIC2_POWER 0x48
#define REG_MIC3_POWER 0x49
#define REG_MIC4_POWER 0x4A
#define REG_MIC12_POWER 0x4B
#define REG_MIC34_POWER 0x4C

// 37.5dB -> register value 14, per the reference driver's gain curve (12=34.5dB, 13=36dB, 14=37.5dB).
#define MIC_GAIN_REG_VALUE 14

static bool writeReg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(ES7210_I2C_ADDR);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

static bool readReg(uint8_t reg, uint8_t* value) {
    Wire.beginTransmission(ES7210_I2C_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;  // repeated start, keep the bus
    if (Wire.requestFrom((int)ES7210_I2C_ADDR, 1) != 1) return false;
    *value = Wire.read();
    return true;
}

static void updateRegBit(uint8_t reg, uint8_t mask, uint8_t data) {
    uint8_t v;
    if (!readReg(reg, &v)) return;
    v = (uint8_t)((v & ~mask) | (mask & data));
    writeReg(reg, v);
}

static void configureMicGain() {
    for (uint8_t i = 0; i < 4; i++) updateRegBit(REG_MIC1_GAIN + i, 0x10, 0x00);
    writeReg(REG_MIC12_POWER, 0xFF);
    writeReg(REG_MIC34_POWER, 0xFF);

    updateRegBit(REG_CLOCK_OFF, 0x0b, 0x00);
    writeReg(REG_MIC12_POWER, 0x00);
    updateRegBit(REG_MIC1_GAIN, 0x10, 0x10);
    updateRegBit(REG_MIC1_GAIN, 0x0f, MIC_GAIN_REG_VALUE);

    updateRegBit(REG_CLOCK_OFF, 0x0b, 0x00);
    writeReg(REG_MIC12_POWER, 0x00);
    updateRegBit(REG_MIC2_GAIN, 0x10, 0x10);
    updateRegBit(REG_MIC2_GAIN, 0x0f, MIC_GAIN_REG_VALUE);

    updateRegBit(REG_CLOCK_OFF, 0x0b, 0x00);
    writeReg(REG_MIC34_POWER, 0x00);
    updateRegBit(REG_MIC3_GAIN, 0x10, 0x10);
    updateRegBit(REG_MIC3_GAIN, 0x0f, MIC_GAIN_REG_VALUE);

    updateRegBit(REG_CLOCK_OFF, 0x0b, 0x00);
    writeReg(REG_MIC34_POWER, 0x00);
    updateRegBit(REG_MIC4_GAIN, 0x10, 0x10);
    updateRegBit(REG_MIC4_GAIN, 0x0f, MIC_GAIN_REG_VALUE);
}

bool es7210_init() {
    // Software reset. If this doesn't ack, the chip isn't there (wrong address, bus issue) -
    // everything after this point would just be writes into the void.
    if (!writeReg(REG_RESET, 0xFF)) {
        Serial.println("es7210: no ack at 0x40 - not present or I2C bus issue");
        return false;
    }
    writeReg(REG_RESET, 0x32);
    writeReg(REG_CLOCK_OFF, 0x3F);

    writeReg(REG_TIME_CONTROL0, 0x30);
    writeReg(REG_TIME_CONTROL1, 0x30);

    writeReg(REG_ADC12_HPF2, 0x2a);
    writeReg(REG_ADC12_HPF1, 0x0a);
    writeReg(REG_ADC34_HPF2, 0x0a);
    writeReg(REG_ADC34_HPF1, 0x2a);

    updateRegBit(REG_MODE_CONFIG, 0x01, 0x00);  // secondary (slave) I2S mode

    writeReg(REG_ANALOG, 0xC3);
    writeReg(REG_MIC12_BIAS, 0x70);
    writeReg(REG_MIC34_BIAS, 0x70);

    // I2S format: 16-bit, non-TDM (mics 1&2 -> SDOUT1, mics 3&4 -> SDOUT2).
    writeReg(REG_SDP_INTERFACE1, 0x60);
    writeReg(REG_SDP_INTERFACE2, 0x00);

    // Espressif's ES7210 coefficient table gives identical settings for
    // 48 kHz / 12.288 MHz and 16 kHz / 4.096 MHz (MCLK = 256 * fs).
    // Capture at 48 kHz; the audio worker low-passes and decimates voice to 16 kHz.
    writeReg(REG_MAINCLK, 0xC1);
    writeReg(REG_OSR, 0x20);
    writeReg(REG_LRCK_DIVH, 0x01);
    writeReg(REG_LRCK_DIVL, 0x00);

    configureMicGain();

    writeReg(REG_MIC1_POWER, 0x08);
    writeReg(REG_MIC2_POWER, 0x08);
    writeReg(REG_MIC3_POWER, 0x08);
    writeReg(REG_MIC4_POWER, 0x08);

    writeReg(REG_POWER_DOWN, 0x04);  // power down DLL

    writeReg(REG_MIC12_POWER, 0x0F);
    writeReg(REG_MIC34_POWER, 0x0F);

    writeReg(REG_RESET, 0x71);
    writeReg(REG_RESET, 0x41);

    Serial.println("es7210: initialized (16-bit/48kHz, 37.5dB)");
    return true;
}
