/* DSP checks run in a VM. No audio device is opened. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
for(const rate of [16000,48000]){
  let Processor;const packets=[];
  const context={sampleRate:rate,AudioWorkletProcessor:class{constructor(){this.port={postMessage:p=>packets.push(p)};}},registerProcessor:(name,type)=>Processor=type};
  vm.runInNewContext(fs.readFileSync('web/display/intercom-worklet.js','utf8'),context);
  const processor=new Processor(),input=new Float32Array(128).fill(.5),output=new Float32Array(128);
  processor.process([[input]],[[output]]);assert.equal(packets.length,0);assert.ok(output.every(v=>v===0));
  processor.port.onmessage({data:{type:'capture',enabled:true}});
  for(let n=0;n<rate/128;n++)processor.process([[input]],[[output]]);
  assert.equal(packets.length,10);assert.equal(new Int16Array(packets[0].data)[0],16384);assert.ok(output.every(v=>v===0));
  processor.port.onmessage({data:{type:'capture',enabled:false}});
  processor.port.onmessage({data:{type:'pcm',data:new Int16Array(1600).fill(4096).buffer}});
  processor.process([[input]],[[output]]);assert.equal(packets.length,10);assert.ok(output.every(v=>v===.125));
  for(let n=0;n<30;n++)processor.port.onmessage({data:{type:'pcm',data:new Int16Array(3200).buffer}});
  assert.ok(processor.count<=8000);
  processor.port.onmessage({data:{type:'clear'}});processor.process([[]],[[output]]);assert.ok(output.every(v=>v===0));
}
console.log('Duplex worklet: capture opt-in, 16/48 kHz conversion, remote-only output, mute and bounded jitter buffer passed. No audio devices.');
