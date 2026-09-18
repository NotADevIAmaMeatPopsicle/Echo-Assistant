#include "host_transport.h"
#include <WiFi.h>
#include <NetworkClientSecure.h>
#include <Preferences.h>
#include <esp_heap_caps.h>
#include <mbedtls/base64.h>

HostTransport Host;
namespace {
constexpr uint32_t configMagic=0x52565031;
struct Pairing { uint32_t magic; char ssid[33],password[65],host[16],key[65]; } pairing{},staging{};
unsigned staged=0;
uint32_t stagedAt=0;
portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;
struct Ring {
    uint8_t* data=nullptr; size_t size=0,head=0,tail=0,count=0;
    bool begin(size_t capacity) { size=capacity; data=(uint8_t*)heap_caps_malloc(size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT); return data; }
    void clear() { head=tail=count=0; }
    bool put(const uint8_t* source,size_t length) {
        if (length>size-count) return false;
        size_t first=min(length,size-head); memcpy(data+head,source,first); memcpy(data,source+first,length-first);
        head=(head+length)%size; count+=length; return true;
    }
    size_t get(uint8_t* out,size_t length) {
        length=min(length,count); size_t first=min(length,size-tail);
        memcpy(out,data+tail,first); memcpy(out+first,data,length-first);
        tail=(tail+length)%size; count-=length; return length;
    }
} rx,tx;
volatile bool connected=false,abortLink=false;
volatile unsigned epoch=0;
volatile int state=0;
NetworkStats stats;
UsbStats usb;
volatile unsigned abortReason=0;
char identity[40];

bool privateHost(const char* value) {
    IPAddress ip;
    return ip.fromString(value) && (ip[0]==10 || (ip[0]==172 && ip[1]>=16 && ip[1]<=31) || (ip[0]==192 && ip[1]==168));
}
bool valid(const Pairing& value) {
    if (value.magic!=configMagic || !memchr(value.ssid,0,sizeof(value.ssid)) || !strlen(value.ssid)
        || !memchr(value.password,0,sizeof(value.password)) || !memchr(value.host,0,sizeof(value.host))
        || !memchr(value.key,0,sizeof(value.key)) || strlen(value.key)!=64 || !privateHost(value.host)) return false;
    for (char c:String(value.key)) if (!isxdigit(c)) return false;
    return true;
}
bool decode(const String& source,char* destination,size_t capacity) {
    unsigned char output[96]; size_t count=0;
    if (mbedtls_base64_decode(output,sizeof(output),&count,(const unsigned char*)source.c_str(),source.length()) || count>=capacity) return false;
    if (memchr(output,0,count)) return false;
    memcpy(destination,output,count); destination[count]=0; return true;
}
void linkState(bool up,unsigned reason=0) {
    portENTER_CRITICAL(&lock);
    if (connected && !up) { ++stats.disconnects; stats.reason=reason; }
    connected=up; rx.clear(); tx.clear(); ++epoch;
    portEXIT_CRITICAL(&lock);
}
void task(void*) {
    NetworkClientSecure client;
    client.setPreSharedKey(identity,pairing.key);
    client.setHandshakeTimeout(4);
    WiFi.persistent(false); WiFi.mode(WIFI_STA); WiFi.setSleep(false);
    WiFi.begin(pairing.ssid,pairing.password);
    uint32_t nextAttempt=0,lastWifi=millis();
    uint8_t buffer[4096];
    while (true) {
        if (WiFi.status()!=WL_CONNECTED) {
            if (connected) linkState(false,1);
            client.stop(); state=1;
            if (millis()-lastWifi>15000) { WiFi.disconnect(); WiFi.begin(pairing.ssid,pairing.password); lastWifi=millis(); }
        } else if (!connected) {
            state=2;
            if (int32_t(millis()-nextAttempt)>=0) {
                // TLS PSK authenticates both peers using a random 256-bit USB-paired secret.
                // There is no certificate bypass, cloud lookup, DNS, or clock dependency.
                if (client.connect(pairing.host,8769,2500)) {
                    client.setNoDelay(true); abortLink=false; abortReason=0; linkState(true); state=3;
                } else nextAttempt=millis()+3000;
            }
        } else if (abortLink || !client.connected()) {
            linkState(false,abortLink?abortReason:2); client.stop(); state=2; nextAttempt=millis()+3000;
        } else {
            portENTER_CRITICAL(&lock);
            size_t length=tx.get(buffer,sizeof(buffer));
            portEXIT_CRITICAL(&lock);
            if (length) {
                uint32_t began=millis(); size_t written=client.write(buffer,length); uint32_t elapsed=millis()-began;
                portENTER_CRITICAL(&lock); stats.maxWriteMs=max(stats.maxWriteMs,elapsed);
                if (written!=length) ++stats.writeErrors;
                portEXIT_CRITICAL(&lock);
                if (written!=length) { abortReason=4; abortLink=true; continue; }
            }
            int available=client.available();
            if (available>0) {
                portENTER_CRITICAL(&lock); size_t room=rx.size-rx.count; portEXIT_CRITICAL(&lock);
                size_t count=min(min(room,sizeof(buffer)),size_t(available));
                if (count) {
                    int got=client.read(buffer,count);
                    if (got>0) { portENTER_CRITICAL(&lock); rx.put(buffer,got); stats.rxHigh=max(stats.rxHigh,rx.count); portEXIT_CRITICAL(&lock); }
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}
}

bool networkConnected() { return connected; }
unsigned networkEpoch() { return epoch; }
int networkRssi() { return WiFi.status()==WL_CONNECTED?WiFi.RSSI():0; }
const char* networkState() { return state==3?"connected":state==2?"waiting_host":state==1?"connecting_wifi":state==4?"memory_error":"not_paired"; }
void networkDisconnect() { abortReason=5; abortLink=true; }
NetworkStats networkStats() { portENTER_CRITICAL(&lock); NetworkStats copy=stats; portEXIT_CRITICAL(&lock); return copy; }
UsbStats usbStats() { return usb; } // USB writes and reporting belong to the main task.
void networkBegin() {
    Preferences prefs; prefs.begin("rv-network",true);
    bool loaded=prefs.getBytesLength("pairing")==sizeof(pairing) && prefs.getBytes("pairing",&pairing,sizeof(pairing))==sizeof(pairing);
    prefs.end();
    if (!loaded || !valid(pairing)) return;
    // Use the immutable chip MAC; the Wi-Fi interface is not initialized yet.
    uint64_t mac=ESP.getEfuseMac();
    snprintf(identity,sizeof(identity),"round-voice/%02x:%02x:%02x:%02x:%02x:%02x",unsigned(mac&255),unsigned((mac>>8)&255),unsigned((mac>>16)&255),unsigned((mac>>24)&255),unsigned((mac>>32)&255),unsigned((mac>>40)&255));
    // Measured Wi-Fi writes can stall >500 ms. 16 KiB filled during that stall;
    // bound microphone backlog to ~2 seconds and retain room for control lines.
    if (!rx.begin(65536) || !tx.begin(65536) || xTaskCreatePinnedToCore(task,"round-network",12288,nullptr,3,nullptr,0)!=pdPASS) state=4;
}
bool networkCommand(const String& command) {
    if (!command.startsWith("PAIR_")) return false;
    if (command=="PAIR_BEGIN") { staging={}; staged=0; stagedAt=millis(); Serial.println("PAIR_OK BEGIN"); return true; }
    if (command=="PAIR_FORGET") {
        Preferences prefs; prefs.begin("rv-network",false); bool exists=prefs.isKey("pairing");
        bool removed=!exists || prefs.remove("pairing"); prefs.end();
        Serial.println(removed?"PAIR_OK FORGET":"PAIR_ERROR STORAGE");
        if (removed) { delay(150); ESP.restart(); } return true;
    }
    if (!stagedAt || millis()-stagedAt>30000) { Serial.println("PAIR_ERROR EXPIRED"); return true; }
    bool ok=false;
    if (command.startsWith("PAIR_SSID ")) { ok=decode(command.substring(10),staging.ssid,sizeof(staging.ssid)); if (ok) staged|=1; }
    else if (command.startsWith("PAIR_WIFI ")) { ok=decode(command.substring(10),staging.password,sizeof(staging.password)); if (ok) staged|=2; }
    else if (command.startsWith("PAIR_HOST ")) { String host=command.substring(10); ok=host.length()<sizeof(staging.host) && privateHost(host.c_str()); if (ok) { strcpy(staging.host,host.c_str()); staged|=4; } }
    else if (command.startsWith("PAIR_KEY ")) { String key=command.substring(9); ok=key.length()==64; for (char c:key) if (!isxdigit(c)) ok=false; if (ok) { strcpy(staging.key,key.c_str()); staged|=8; } }
    else if (command=="PAIR_SAVE") {
        staging.magic=configMagic;
        if (staged==15 && valid(staging)) {
            Preferences prefs; prefs.begin("rv-network",false);
            ok=prefs.putBytes("pairing",&staging,sizeof(staging))==sizeof(staging); prefs.end();
            if (ok) { memset(&staging,0,sizeof(staging)); staged=0; Serial.println("PAIR_OK SAVED"); delay(150); ESP.restart(); return true; }
        }
    }
    if (!ok) { memset(&staging,0,sizeof(staging)); staged=0; stagedAt=0; }
    Serial.println(ok?"PAIR_OK FIELD":"PAIR_ERROR INVALID"); return true;
}
int HostTransport::available() {
    if (!connected) return Serial.available();
    portENTER_CRITICAL(&lock); int result=rx.count; portEXIT_CRITICAL(&lock); return result;
}
int HostTransport::read() {
    if (!connected) return Serial.read();
    uint8_t value; portENTER_CRITICAL(&lock); size_t count=rx.get(&value,1); portEXIT_CRITICAL(&lock); return count?value:-1;
}
int HostTransport::peek() {
    if (!connected) return Serial.peek();
    portENTER_CRITICAL(&lock); int result=rx.count?rx.data[rx.tail]:-1; portEXIT_CRITICAL(&lock); return result;
}
size_t HostTransport::write(const uint8_t* data,size_t length) {
    if (!connected) {
        // HWCDC queues while disconnected and can discard the front of its
        // ring to make room. That is unsuitable for a framed binary stream.
        if (!Serial.isConnected()) { ++usb.skipped; return 0; }
        uint32_t began=millis(); size_t written=Serial.write(data,length);
        usb.maxWriteMs=max(usb.maxWriteMs,millis()-began);
        if (written!=length) ++usb.partial;
        return written;
    }
    portENTER_CRITICAL(&lock); bool ok=tx.put(data,length); stats.txHigh=max(stats.txHigh,tx.count);
    if (!ok) { ++stats.txFull; abortReason=3; abortLink=true; }
    portEXIT_CRITICAL(&lock); // Never continue a partially written audio/status frame.
    return ok?length:0;
}
int HostTransport::availableForWrite() {
    if (!connected) return Serial.isConnected()?max(0,Serial.availableForWrite()-2048):0;
    portENTER_CRITICAL(&lock); int result=max(0,int(tx.size-tx.count)-2048); portEXIT_CRITICAL(&lock); return result;
}
