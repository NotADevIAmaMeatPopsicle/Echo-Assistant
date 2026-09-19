/* Synthetic microphone data only; never opens an audio device. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
for(const rate of [16000,48000]){
  const packets=[];let Processor;
  const context={sampleRate:rate,AudioWorkletProcessor:class{constructor(){this.port={postMessage:value=>packets.push(value)};}},registerProcessor:(name,type)=>Processor=type};
  vm.runInNewContext(fs.readFileSync('web/display/capture-worklet.js','utf8'),context);
  const processor=new Processor();let active=true,frames=0;
  while(active && frames<rate*9){const input=new Float32Array(128).fill(.5);active=processor.process([[input]]);frames+=128;}
  const pcm=packets.filter(p=>p.type==='pcm');
  assert.equal(pcm.reduce((sum,p)=>sum+p.data.byteLength,0),256000);
  assert.equal(new Int16Array(pcm[0].data)[0],16384);
  assert.equal(packets.filter(p=>p.type==='done').length,1);assert.equal(active,false);
}
console.log('Passed: 16/48 kHz synthetic input, mono PCM scaling, exact eight-second bound. No microphone or playback.');
