#pragma once
// Use the existing, attributed GFX font bitmaps at optical sizes suited to 466px.
// Four coverage samples soften the small labels and headlines; no extra font asset.
#include <math.h>
namespace UiType {
inline const GFXfont& font(unsigned size){return size>=2?FreeSans18pt7b:FreeSans9pt7b;}
inline float scale(unsigned size){return size==0?.70f:size==2?.90f:size==3?1.30f:1.0f;}
inline int width(const char* s,unsigned size,int* offset=nullptr) {
    const auto& f=font(size);int cursor=0,left=32767,right=-32768;
    for(;*s;++s){unsigned c=(unsigned char)*s;if(c<f.first || c>f.last)continue;const auto& g=f.glyph[c-f.first];
        if(g.width && g.height){int lo=cursor+g.xOffset,hi=lo+g.width-1;if(lo<left)left=lo;if(hi>right)right=hi;}cursor+=g.xAdvance;}
    if(right<left){if(offset)*offset=0;return 0;}
    int l=int(floorf(left*scale(size))),r=int(ceilf((right+1)*scale(size)));
    if(offset)*offset=l;return r-l;
}
template<class Surface> void draw(Surface& surface,const char* s,int cx,int baseline,unsigned size,uint16_t color) {
    int offset=0,w=width(s,size,&offset),origin=cx-w/2-offset,cursor=0;
    const auto& f=font(size);float factor=scale(size),inverse=1/factor;
    for(;*s;++s){unsigned c=(unsigned char)*s;if(c<f.first || c>f.last)continue;const auto& g=f.glyph[c-f.first];
        int gx=cursor+g.xOffset;
        if(size==1) {
            // At native font size every pixel has full or zero coverage.
            // Avoid four redundant floating-point samples for body text.
            for(int y=0;y<g.height;++y)for(int x=0;x<g.width;++x){int bit=y*g.width+x;
                if(f.bitmap[g.bitmapOffset+bit/8]&(0x80>>(bit%8)))surface.pixel(origin+gx+x,baseline+g.yOffset+y,color);}
            cursor+=g.xAdvance;continue;
        }
        int left=int(floorf(gx*factor)),right=int(ceilf((gx+g.width)*factor));
        int top=int(floorf(g.yOffset*factor)),bottom=int(ceilf((g.yOffset+g.height)*factor));
        int xs[64][2];
        for(int x=left;x<right;++x)for(int sx=0;sx<2;++sx)xs[x-left][sx]=int(floorf((x+.25f+.5f*sx)*inverse))-gx;
        for(int y=top;y<bottom;++y){int ys[2]={int(floorf((y+.25f)*inverse))-g.yOffset,int(floorf((y+.75f)*inverse))-g.yOffset};
          for(int x=left;x<right;++x){int coverage=0;
            for(int sy=0;sy<2;++sy)for(int sx=0;sx<2;++sx){
                int sourceX=xs[x-left][sx],sourceY=ys[sy];
                if(sourceX>=0 && sourceX<g.width && sourceY>=0 && sourceY<g.height){int bit=sourceY*g.width+sourceX;
                    if(f.bitmap[g.bitmapOffset+bit/8]&(0x80>>(bit%8)))++coverage;}}
            if(coverage)surface.alphaPixel(origin+x,baseline+y,color,coverage==4?255:coverage*64);}}

        cursor+=g.xAdvance;
    }
}
}
