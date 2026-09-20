#pragma once
#include "control_scene.h"
#include "member_account.h"
#include "access_profile.h"
namespace MemberScene {
template<class Surface> void render(Surface& g,const ControlScene::Model& m,const MemberAccount& a,const MiniAccess& access){
    using namespace ControlScene;using namespace VoiceScene;
    g.background();header(g,m.system,mint,"ECHO / YOUR SPACE");
    if(access.personal){
        centered(g,access.name,172,2,mint);centered(g,"Personal session",206,1);
        centered(g,"Locks after 15 minutes",231,1,dim);
        pill(g,115,250,236,"Lock my session",mint);pill(g,165,303,136,"Back",dim);
        centered(g,a.pending?"Locking...":a.message,382,0,dim);return;
    }
    if(a.selected<0){
        centered(g,"Who is here?",117,2);
        for(unsigned row=0;row<3&&a.offset+row<a.count;++row){unsigned i=a.offset+row;bool ready=a.received&(1u<<i);pill(g,105,143+int(row)*50,256,ready?a.names[i]:"Loading...",mint,ready&&!a.pending);}
        pill(g,95,307,82,"Prev",dim,a.offset>0);pill(g,183,307,100,"Back",dim);pill(g,289,307,82,"Next",dim,a.offset+3<a.count);
        centered(g,a.message,382,0,dim);return;
    }
    centered(g,a.names[a.selected],106,1,mint);
    char masked[9];memset(masked,'*',a.digits);masked[a.digits]=0;centered(g,masked,137,2);
    const char* keys[]={"1","2","3","4","5","6","7","8","9","Clear","0","Del"};
    for(int i=0;i<12;++i)pill(g,125+(i%3)*74,147+(i/3)*46,68,keys[i],dim,!a.pending);
    pill(g,95,337,132,"Cancel",dim,!a.pending);pill(g,239,337,132,a.pending?"Wait...":"Sign in",mint,!a.pending&&a.digits==8);
    centered(g,a.message,399,0,dim);
}
}
