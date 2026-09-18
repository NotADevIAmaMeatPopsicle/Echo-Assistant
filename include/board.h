#pragma once
namespace Board {
constexpr int width=466, height=466;
constexpr int lcdCs=12, lcdClock=38, lcdD0=4, lcdD1=5, lcdD2=6, lcdD3=7, lcdReset=39;
constexpr int sda=15, scl=14, touchReset=40, touchIrq=11;
constexpr int audioBclk=9, audioWs=45, audioMclk=42, audioOut=8, audioIn=10, ampEnable=46;
constexpr int sdClk=2, sdCmd=1, sdD0=3;
// Upper PWR key: active high on TCA9554 EXIO4; BOOT is a separate GPIO0 key.
constexpr int keyExpander=0x20, powerKeyMask=1<<4;
constexpr int bootButton=0;
constexpr int sampleRate=48000, voiceRate=16000;
}
