/* Browser checks must target the separate synthetic preview, never a live home. */
async function previewBase() {
  const url=new URL(process.env.ECHO_PREVIEW_URL || 'http://127.0.0.1:8788');
  if(url.protocol!=='http:' || url.hostname!=='127.0.0.1' || url.username || url.password || url.pathname!=='/' || url.search || url.hash)
    throw Error('UI checks require a loopback synthetic preview origin.');
  const response=await fetch(url.origin+'/health',{redirect:'error',signal:AbortSignal.timeout(5000)});
  if(!response.ok || (await response.json()).display_demo!==true)
    throw Error('Refusing UI checks: this server is not the synthetic Echo preview.');
  return url.origin;
}
module.exports={previewBase};
