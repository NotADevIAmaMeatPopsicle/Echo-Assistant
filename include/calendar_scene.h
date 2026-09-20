#pragma once
#include "calendar_review.h"
#include "control_scene.h"
namespace CalendarScene {
template<class Surface> void render(Surface& g,const ControlScene::Model& system,const CalendarReview& draft){
    using namespace VoiceScene;
    using ControlScene::centered;using ControlScene::pill;
    g.background();header(g,system.system,draft.pending?amber:mint);
    centered(g,"Calendar draft",111,2);
    char text[64];snprintf(text,sizeof(text),"Page %u / %u",draft.page+1,draft.pages());
    centered(g,draft.pending?"Sending once...":draft.result!=CalendarReview::None?"Calendar result":draft.confirming?"Create this event?":text,143,1,dim);
    if(draft.result!=CalendarReview::None){
        centered(g,draft.result==CalendarReview::Accepted?"Home Assistant accepted":draft.result==CalendarReview::Rejected?"Calendar request rejected":"Completion unconfirmed",196,1,draft.result==CalendarReview::Accepted?mint:amber);
        centered(g,"Check the calendar on Deck.",230,1,dim);
        centered(g,"Do not create a duplicate.",254,0,dim);
        pill(g,125,282,216,"Close",dim);
    }else if(draft.pending){
        centered(g,"Waiting for the calendar.",199,1);
        centered(g,"Leaving cannot undo a sent event.",238,0,dim);
    }else if(draft.confirming){
        centered(g,"All draft pages reviewed.",187,1);
        centered(g,"This saves to the calendar",216,1);
        centered(g,"and is visible to its users.",245,1,dim);
        pill(g,95,282,132,"Back",dim);pill(g,239,282,132,"Create",mint);
    }else if(draft.ready){
        for(unsigned line=0;line<CalendarReview::perPage;++line){unsigned index=draft.page*CalendarReview::perPage+line;if(index>=draft.count)break;
            g.text(draft.rows[index],233,176+line*26,g.width(draft.rows[index],1)<=324?1:0,line==0?mint:VoiceScene::text);
        }
        pill(g,95,282,132,draft.page?"Previous":"Cancel",dim);
        pill(g,239,282,132,draft.page+1<draft.pages()?"Next":draft.allowed?"Review done":"Close",mint);
    }else centered(g,"Waiting for complete draft...",208,1,dim);
    ControlScene::navigation(g,system);
}
}
