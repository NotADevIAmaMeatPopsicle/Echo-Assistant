/* Real, silent ICE/TCP transport check. Tokens arrive only through stdin. */
'use strict';
const {chromium}=require('playwright');
const fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const crypto=require('node:crypto');
const {isIP}=require('node:net');
const sdkPath=path.join(__dirname,'../web/vendor/livekit-client-2.22.3.umd.js');
const sdk=fs.readFileSync(sdkPath);
if(crypto.createHash('sha256').update(sdk).digest('hex')!=='7fa17e37af5e996d8a25f15a637dcc0620215bc01b394e5d209f726afe7dc04d')throw Error('SDK checksum mismatch');
if(process.argv.includes('--preflight'))process.exit(0);

(async()=>{
 let browser,server,stage='input',exitCode=1,result={};
 const pages=[];
 try{
  const config=JSON.parse(fs.readFileSync(0,'utf8'));
  const provider=new URL(config.url);
  const loopback=provider.protocol==='ws:'&&provider.hostname==='127.0.0.1';
  const label='[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?';
  const tailnetMatch=typeof config.url==='string'&&config.url.match(new RegExp('^wss://('+label+'\\.'+label+'\\.ts\\.net):([0-9]{1,5})$'));
  const tailnet=Boolean(tailnetMatch&&Number(tailnetMatch[2])>=1&&Number(tailnetMatch[2])<=65535&&config.url==='wss://'+tailnetMatch[1]+':'+Number(tailnetMatch[2]));
  const expectedAddress=tailnet?config.expectedTcpAddress:null;
  const addressParts=typeof expectedAddress==='string'?expectedAddress.split('.').map(Number):[];
  if((!loopback&&!tailnet)||!Array.isArray(config.tokens)||config.tokens.length!==2||config.tokens.some(token=>typeof token!=='string'||!token))throw Error('Invalid input');
  if(!Number.isInteger(config.expectedTcpPort)||config.expectedTcpPort<1||config.expectedTcpPort>65535)throw Error('Invalid input');
  if(tailnet&&(config.expectedTcpPort!==7881||typeof expectedAddress!=='string'||isIP(expectedAddress)!==4||addressParts[0]!==100||addressParts[1]<64||addressParts[1]>127))throw Error('Invalid input');
  if(config.previewPort!==undefined&&(!Number.isInteger(config.previewPort)||config.previewPort<1024||config.previewPort>65535))throw Error('Invalid input');
  stage='local-preview';
  server=http.createServer((req,res)=>{
   res.setHeader('Cache-Control','no-store');
   if(req.url==='/sdk.js'){res.setHeader('Content-Type','application/javascript');return res.end(sdk);}
   if(req.url==='/'){res.setHeader('Content-Type','text/html');return res.end('<!doctype html><html><head><meta charset="utf-8"><title>Silent TCP check</title></head><body><script src="/sdk.js"></script></body></html>');}
   res.statusCode=404;res.end();
  });
  await new Promise((resolve,reject)=>{
   server.once('error',reject);
   server.listen(config.previewPort??0,'127.0.0.1',()=>{server.removeListener('error',reject);resolve();});
  });
  const preview='http://127.0.0.1:'+server.address().port;
  const providerHttp=new URL(provider.origin);providerHttp.protocol=provider.protocol==='wss:'?'https:':'http:';
  const allowed=new Set([preview,providerHttp.origin]);
  const blocked=[];
  stage='browser';
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--mute-audio','--disable-background-networking','--disable-component-update','--allow-loopback-in-peer-connection']});
  const context=await browser.newContext({serviceWorkers:'block'});
  await context.clearPermissions();
  await context.route('**/*',route=>{
   if(!allowed.has(new URL(route.request().url()).origin)){blocked.push('http');return route.abort();}
   return route.continue();
  });
  await context.routeWebSocket('**/*',socket=>{
   if(new URL(socket.url()).origin!==provider.origin){blocked.push('websocket');return socket.close();}
   socket.connectToServer();
  });
  await context.addInitScript(()=>{
   window.checkPCs=[];window.checkCaptureCalls=0;window.checkPlayCalls=0;window.checkIceEvents=[];window.checkCandidates=[];
   function candidateSummary(side,candidate){if(candidate)window.checkCandidates.push({side,protocol:candidate.protocol,port:candidate.port,loopback:candidate.address==='127.0.0.1',tcp_type:candidate.tcpType});}
   Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},removeEventListener(){},getUserMedia(){window.checkCaptureCalls++;throw Error('Capture forbidden');},getDisplayMedia(){window.checkCaptureCalls++;throw Error('Capture forbidden');}}});
   HTMLMediaElement.prototype.play=function(){window.checkPlayCalls++;throw Error('Playback forbidden');};
   const OriginalPC=window.RTCPeerConnection;
   window.RTCPeerConnection=class extends OriginalPC{
    constructor(config,...rest){
     if(!config||!Array.isArray(config.iceServers)||config.iceServers.length)throw Error('External ICE configuration forbidden');
     super(config,...rest);window.checkPCs.push(this);
     this.addEventListener('iceconnectionstatechange',()=>window.checkIceEvents.push(this.iceConnectionState));
     this.addEventListener('icecandidate',event=>candidateSummary('local',event.candidate));
    }
    setConfiguration(config){if(!Array.isArray(config.iceServers)||config.iceServers.length)throw Error('External ICE configuration forbidden');return super.setConfiguration(config);}
    addIceCandidate(candidate){if(candidate)candidateSummary('remote',new RTCIceCandidate(candidate));return super.addIceCandidate(candidate);}
   };
  });
  for(const credential of config.tokens){
   const page=await context.newPage();pages.push(page);
   await page.goto(preview,{waitUntil:'load'});
   stage='livekit-connect';
   await page.evaluate(async({url,token})=>{
    LivekitClient.setLogLevel('silent');
    window.checkRoom=new LivekitClient.Room({adaptiveStream:false,dynacast:false});
    await window.checkRoom.connect(url,token,{autoSubscribe:true,rtcConfig:{iceServers:[]},maxRetries:0,peerConnectionTimeout:20000,websocketTimeout:10000});
   },{url:config.url,token:credential});
  }
  stage='selected-ice-tcp';
  const peers=[];
  for(const page of pages){
   const peer=await page.evaluate(async({expectedPort,expectedAddress})=>{
    const until=Date.now()+20000;
    while(Date.now()<until){
     const pairs=[];
     for(const pc of window.checkPCs){
      const stats=await pc.getStats();
      const selected=new Set([...stats.values()].filter(s=>s.type==='transport'&&s.selectedCandidatePairId).map(s=>s.selectedCandidatePairId));
      for(const pair of stats.values()){
       if(pair.type!=='candidate-pair'||pair.state!=='succeeded'||!pair.nominated||!selected.has(pair.id))continue;
       const local=stats.get(pair.localCandidateId),remote=stats.get(pair.remoteCandidateId);
       if(pc.connectionState!=='connected'||pc.iceConnectionState!=='connected'&&pc.iceConnectionState!=='completed')continue;
       if(remote?.port!==expectedPort||remote?.protocol!=='tcp'||local?.protocol!=='tcp')throw Error('Selected transport was not expected TCP endpoint');
       if(expectedAddress!==null&&remote?.address!==expectedAddress)throw Error('Selected transport address did not match expected endpoint');
       if(pc.getSenders().some(s=>s.track)||checkRoom.localParticipant.trackPublications.size)throw Error('Media track was created');
       pairs.push({state:pair.state,nominated:pair.nominated,protocol:remote.protocol,local_protocol:local.protocol,remote_port:remote.port,connection_state:pc.connectionState,
        ...(expectedAddress!==null?{remote_address_verified:true}:{})});
      }
     }
     if(pairs.length){
      if(checkCaptureCalls||checkPlayCalls)throw Error('Capture or playback attempted');
      return {selected_pairs:pairs,capture_calls:checkCaptureCalls,play_calls:checkPlayCalls,local_tracks:checkRoom.localParticipant.trackPublications.size};
     }
     await new Promise(resolve=>setTimeout(resolve,200));
    }
    throw Error('No nominated selected TCP candidate pair');
   },{expectedPort:config.expectedTcpPort,expectedAddress});
   peers.push(peer);
  }
  if(blocked.length)throw Error('An external browser request was attempted');
  stage='disconnect';
  for(const page of pages)await page.evaluate(()=>window.checkRoom.disconnect(true));
  result={ice_tcp_connected:true,participants:peers,client:'2.22.3',media_tracks:false,audio_playback:false,external_requests:0};
  exitCode=0;
 }catch(error){
  const reason=['Capture forbidden','Playback forbidden','External ICE configuration forbidden','timeout','signal connection','pc connection','permission','publish','WebSocket','not a function'].find(value=>String(error.message).toLowerCase().includes(value.toLowerCase()))||'connection rejected';
  const states=[];
  for(const page of pages){
   states.push(await page.evaluate(()=>({capture_calls:window.checkCaptureCalls,play_calls:window.checkPlayCalls,ice_events:window.checkIceEvents,candidates:window.checkCandidates,
    peer_connections:(window.checkPCs||[]).map(pc=>({connection:pc.connectionState,ice:pc.iceConnectionState,signal:pc.signalingState}))})).catch(()=>({unavailable:true})));
  }
  result={ice_tcp_connected:false,stage,reason,states};
 }finally{
  if(browser)await browser.close().catch(()=>{});
  if(server)await new Promise(resolve=>server.close(resolve));
 }
 process.stdout.write(JSON.stringify(result));process.exitCode=exitCode;
})();
