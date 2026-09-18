#pragma once
#include <Arduino.h>

// Only this abstraction carries assistant commands/audio. Provisioning stays USB-only.
class HostTransport : public Stream {
public:
    using Print::write;
    int available() override;
    int read() override;
    int peek() override;
    void flush() override {}
    size_t write(uint8_t value) override { return write(&value,1); }
    size_t write(const uint8_t* data,size_t length) override;
    int availableForWrite();
};
extern HostTransport Host;
void networkBegin();
bool networkCommand(const String& command); // Call only for a USB command.
bool networkConnected();
unsigned networkEpoch();
const char* networkState();
int networkRssi();
void networkDisconnect();
struct NetworkStats {
    uint32_t disconnects=0,txFull=0,writeErrors=0,maxWriteMs=0;
    size_t txHigh=0,rxHigh=0;
    unsigned reason=0; // 1 Wi-Fi lost, 2 peer closed, 3 TX full, 4 write failed, 5 requested.
};
NetworkStats networkStats();
struct UsbStats { uint32_t skipped=0,partial=0,maxWriteMs=0; };
UsbStats usbStats();
