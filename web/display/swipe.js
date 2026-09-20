/* English glide decoding. Gesture samples and draft text never leave this browser. */
'use strict';
class EchoSwipeLexicon {
  constructor() { this.words=[]; this.shapes=new Map(); this.loading=null; }
  async load() {
    if (!this.loading) this.loading=fetch('/assets/display/keyboard-words.json', {credentials:'same-origin'})
      .then(response=>{if(!response.ok)throw Error('Dictionary unavailable');return response.json();})
      .then(value=>{this.words=value.words.filter(word=>/^[a-z]{1,20}$/.test(word));})
      .catch(error=>{this.loading=null;throw error;});
    return this.loading;
  }
  static centers() {
    const result={};
    ['qwertyuiop','asdfghjkl','zxcvbnm'].forEach((row,y)=>{
      [...row].forEach((letter,x)=>result[letter]=[x+[0,.5,1.5][y],y]);
    });
    return result;
  }
  static resample(points, count=32) {
    const lengths=[0];
    for(let i=1;i<points.length;i++)lengths.push(lengths[i-1]+Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]));
    const total=lengths.at(-1),result=[];let at=1;
    if(!total)return Array.from({length:count},()=>points[0]);
    for(let i=0;i<count;i++){
      const distance=total*i/(count-1);
      while(at<lengths.length-1&&lengths[at]<distance)at++;
      const span=lengths[at]-lengths[at-1],t=span?(distance-lengths[at-1])/span:0;
      result.push([points[at-1][0]+t*(points[at][0]-points[at-1][0]),points[at-1][1]+t*(points[at][1]-points[at-1][1])]);
    }
    return result;
  }
  decode(points) {
    if(points.length<2||!this.words.length)return [];
    const centers=EchoSwipeLexicon.centers(),sample=EchoSwipeLexicon.resample(points),ranked=[];
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    for(let rank=0;rank<this.words.length;rank++){
      const word=this.words[rank];if(word.length<2)continue;
      const start=distance(points[0],centers[word[0]]),end=distance(points.at(-1),centers[word.at(-1)]);
      if(start>.8||end>.8)continue;
      let shape=this.shapes.get(word);
      if(!shape){shape=EchoSwipeLexicon.resample([...word.replace(/(.)\1+/g,'$1')].map(letter=>centers[letter]));this.shapes.set(word,shape);}
      const error=sample.reduce((sum,p,i)=>sum+distance(p,shape[i]),0)/sample.length;
      if(error>1.15)continue;
      ranked.push({word,score:error+(start+end)*.3+Math.log1p(rank)*.012});
    }
    return ranked.sort((a,b)=>a.score-b.score).slice(0,3).map(item=>item.word);
  }
  complete(prefix) {
    if(!prefix)return [];
    return this.words.filter(word=>word.startsWith(prefix.toLowerCase())&&word.length>=prefix.length).slice(0,3);
  }
}
if(typeof module!=='undefined')module.exports={EchoSwipeLexicon};
