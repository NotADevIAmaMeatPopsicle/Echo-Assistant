/* Mono speech capture. Resample to 16 kHz and stop after eight seconds. */
class EchoCapture extends AudioWorkletProcessor {
  constructor(){super();this.phase=0;this.sum=0;this.count=0;this.total=0;this.buffer=new Int16Array(320);this.used=0;}
  process(inputs){
    const input=inputs[0]?.[0];if(!input)return true;
    for(const sample of input){
      this.sum+=sample;this.count++;this.phase+=16000;
      if(this.phase>=sampleRate){
        this.phase-=sampleRate;
        const value=Math.max(-1,Math.min(1,this.sum/this.count));this.sum=0;this.count=0;
        this.buffer[this.used++]=Math.round(value*(value<0?32768:32767));this.total++;
        if(this.used===this.buffer.length){this.port.postMessage({type:'pcm',data:this.buffer.buffer},[this.buffer.buffer]);this.buffer=new Int16Array(320);this.used=0;}
        if(this.total>=128000){this.port.postMessage({type:'done'});return false;}
      }
    }
    return true;
  }
}
registerProcessor('echo-capture',EchoCapture);
