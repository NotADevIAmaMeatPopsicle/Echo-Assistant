/* Only a native, revocable lease may load this official provider player. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id),lease=location.hash.slice(1),validID=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{11}$/.test(value);
  let active=true,generation=0,videoID='',player=null,timer=null,pulsing=false,apiScript=null,apiTimer=null,stopSent=false;
  // The lease remains in this document's memory and never enters provider URLs.
  history.replaceState(null,'',location.pathname);
  const errors={5:'YouTube could not play this video in this browser (error 5).',100:'This video is missing or private on YouTube (error 100).',101:'The uploader does not allow this video to be embedded (error 101).',150:'The uploader does not allow this video to be embedded (error 150).',153:'YouTube did not receive the required client identification (error 153).'};
  function message(text){$('video-player-status').textContent=text;}
  function destroy(){clearTimeout(apiTimer);apiTimer=null;try{player?.destroy();}catch{}player=null;$('video-player-mount').replaceChildren();$('video-player-mount').hidden=true;apiScript?.remove();apiScript=null;window.onYouTubeIframeAPIReady=undefined;}
  async function request(action,keepalive=false){const response=await fetch('/v1/display/video/player',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Echo-Request':'1'},body:JSON.stringify({lease,action}),signal:AbortSignal.timeout(1800),keepalive});if(!response.ok)throw Error('lease');return response.json();}
  function notifyStop(){if(stopSent||!(/^[a-f0-9]{32}$/.test(lease)))return;stopSent=true;void request('stop',true).catch(()=>{});}
  function stop(text,notify=true){if(!active)return;active=false;generation++;clearInterval(timer);timer=null;destroy();$('video-player-placeholder').hidden=false;$('video-player-placeholder').querySelector('p').textContent='Video stopped.';message(text);$('video-player-stop').textContent='Back to Echo';if(notify)notifyStop();}
  function providerError(code){const text=errors[code]||'YouTube could not load this video. Continue on your phone.';stop(text+' Use the phone address below.');}
  function loadProvider(){
    if(!active||!validID(videoID))return;const version=generation;
    const url=new URL('https://www.youtube-nocookie.com/embed/'+videoID);
    for(const [key,value] of Object.entries({enablejsapi:'1',autoplay:'0',playsinline:'1',controls:'1',mute:'1',origin:location.origin}))url.searchParams.set(key,value);
    const frame=document.createElement('iframe');frame.id='video-player-frame';frame.title='YouTube video player';frame.referrerPolicy='strict-origin-when-cross-origin';frame.allow='encrypted-media; picture-in-picture; fullscreen';frame.allowFullscreen=true;frame.src=url.href;
    $('video-player-mount').replaceChildren(frame);$('video-player-mount').hidden=false;$('video-player-placeholder').hidden=true;
    message('Loading YouTube. Starts muted; tap Play in the provider controls.');
    const setup=()=>{if(!active||version!==generation)return;clearTimeout(apiTimer);try{player=new YT.Player(frame,{events:{onReady:event=>{if(!active||version!==generation){try{event.target.destroy();}catch{}return;}event.target.mute();message('Ready · muted. Tap Play and use YouTube’s own controls.');},onStateChange:event=>{if(!active||version!==generation)return;const words={0:'Video ended. Stop & back returns to Echo.',1:'Playing · use YouTube’s controls for volume and captions.',2:'Paused · use YouTube’s controls to continue.',3:'YouTube is buffering…',5:'Ready · tap Play in YouTube’s controls.'};if(words[event.data])message(words[event.data]);},onError:event=>{if(active&&version===generation)providerError(Number(event.data));},onAutoplayBlocked:()=>{if(active&&version===generation)message('Tap Play in YouTube’s controls to begin.');}}});}catch{stop('YouTube’s player could not start. Continue on your phone.');}};
    window.onYouTubeIframeAPIReady=setup;
    apiScript=document.createElement('script');apiScript.src='https://www.youtube.com/iframe_api';apiScript.referrerPolicy='strict-origin-when-cross-origin';apiScript.onerror=()=>{if(active&&version===generation)stop('YouTube’s player could not load. Continue on your phone.');};
    apiTimer=setTimeout(()=>{if(active&&version===generation)stop('YouTube did not finish loading. Continue on your phone.');},12000);
    document.head.append(apiScript);
  }
  async function pulse(){
    if(!active||pulsing)return;const version=generation;pulsing=true;
    try{const value=await request('pulse');if(!active||version!==generation)return;
      if(value.active!==true||!validID(value.video_id)||(videoID&&value.video_id!==videoID))throw Error('lease');
      if(!videoID){videoID=value.video_id;$('video-player-url').value='https://www.youtube.com/watch?v='+videoID;$('video-player-handoff').hidden=false;loadProvider();}
    }catch{if(active&&version===generation){$('video-player-url').value='';$('video-player-handoff').hidden=true;stop('Video stopped because this display’s permission or connection changed. Return to Echo and load it again.');}}
    finally{pulsing=false;}
  }
  $('video-player-stop').onclick=()=>{if(active)stop('Video stopped. Returning to Echo…');else notifyStop();};
  $('video-player-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('video-player-url').value);$('video-player-copy-status').textContent='Link copied. Open it on your phone.';}catch{$('video-player-url').select();$('video-player-copy-status').textContent='Select and copy the address to your phone.';}};
  window.addEventListener('pagehide',()=>stop('Video closed.'));
  window.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();stop('Video stopped. Returning to Echo…');}});
  if(!/^[a-f0-9]{32}$/.test(lease)){stop('No active video permission. Return to Echo and choose Load selected video.',false);return;}
  timer=setInterval(()=>void pulse(),2000);void pulse();
})();
