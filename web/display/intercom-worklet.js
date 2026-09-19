/* Duplex PCM bridge: microphone -> 16 kHz; remote audio -> native output rate. */
class EchoIntercom extends AudioWorkletProcessor {
  constructor(){
    super();this.capture=false;this.phase=0;this.sum=0;this.samples=0;this.used=0;this.packet=new Int16Array(1600);
    this.ring=new Float32Array(16000);this.head=0;this.count=0;this.playPhase=0;this.started=false;
    this.port.onmessage=event=>{
      if(event.data.type==='capture'){this.capture=event.data.enabled;this.phase=this.sum=this.samples=this.used=0;}
      if(event.data.type==='clear'){this.head=this.count=this.playPhase=0;this.started=false;}
      if(event.data.type==='pcm'){
        const pcm=new Int16Array(event.data.data);
        if(pcm.length>3200)return;
        while(this.count+pcm.length>8000){this.head=(this.head+1)%this.ring.length;this.count--;}
        for(const sample of pcm){this.ring[(this.head+this.count)%this.ring.length]=sample/32768;this.count++;}
      }
    };
  }
  process(inputs,outputs){
    const input=inputs[0]?.[0];
    if(this.capture&&input)for(const sample of input){
      this.sum+=sample;this.samples++;this.phase+=16000;
      if(this.phase>=sampleRate){
        this.phase-=sampleRate;const value=Math.max(-1,Math.min(1,this.sum/this.samples));this.sum=0;this.samples=0;
        this.packet[this.used++]=Math.round(value*(value<0?32768:32767));
        if(this.used===1600){this.port.postMessage({type:'pcm',data:this.packet.buffer},[this.packet.buffer]);this.packet=new Int16Array(1600);this.used=0;}
      }
    }
    const output=outputs[0]?.[0];if(!output)return true;
    if(!this.started&&this.count>=1600)this.started=true;
    for(let i=0;i<output.length;i++){
      if(!this.started||this.count<2){output[i]=0;if(this.started){this.started=false;this.count=0;this.playPhase=0;}continue;}
      const a=this.ring[this.head],b=this.ring[(this.head+1)%this.ring.length];output[i]=a+(b-a)*this.playPhase;
      this.playPhase+=16000/sampleRate;
      while(this.playPhase>=1){this.playPhase--;this.head=(this.head+1)%this.ring.length;this.count--;}
    }
    return true;
  }
}
registerProcessor('echo-intercom',EchoIntercom);
