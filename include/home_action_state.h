#pragma once
#include <stdint.h>
#include <string.h>

// Touch-request acknowledgement state only. It never retries or performs an action.
struct HomeActionState {
    enum class Phase { Idle, Pending, Accepted, Failed, Unavailable, Busy, Unconfirmed };
    Phase phase=Phase::Idle;
    uint32_t request=0,changedAt=0;
    bool pending() const { return phase==Phase::Pending; }
    bool begin(uint32_t now) {
        if(pending())return false;
        if(++request==0)++request;
        changedAt=now;phase=Phase::Pending;return true;
    }
    bool acknowledge(uint32_t id,const char* status,uint32_t now) {
        if(!pending() || !id || id!=request)return false;
        if(strcmp(status,"pending")==0)return true; // Do not extend the local deadline.
        Phase next;
        if(strcmp(status,"accepted")==0)next=Phase::Accepted;
        else if(strcmp(status,"failed")==0)next=Phase::Failed;
        else if(strcmp(status,"unavailable")==0)next=Phase::Unavailable;
        else if(strcmp(status,"busy")==0)next=Phase::Busy;
        else return false;
        phase=next;changedAt=now;return true;
    }
    void tick(uint32_t now,bool connected) {
        if(pending() && (!connected || uint32_t(now-changedAt)>=15000)) { phase=Phase::Unconfirmed;changedAt=now; }
        else if(!pending() && phase!=Phase::Idle && uint32_t(now-changedAt)>=8000)phase=Phase::Idle;
    }
    bool failed() const { return phase==Phase::Failed || phase==Phase::Unavailable || phase==Phase::Busy || phase==Phase::Unconfirmed; }
    const char* message() const {
        switch(phase) {
            case Phase::Pending:return "Sending request...";
            case Phase::Accepted:return "Request accepted";
            case Phase::Failed:return "Request failed";
            case Phase::Unavailable:return "Device unavailable";
            case Phase::Busy:return "Another request is in progress";
            case Phase::Unconfirmed:return "No confirmation. Check status";
            default:return "";
        }
    }
};
