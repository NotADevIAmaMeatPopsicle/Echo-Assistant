"""Bounded, request-scoped Pi speech. Audio returns only to the requesting endpoint."""
import base64
from io import BytesIO
from threading import Lock
import wave

from .speech import synthesize_checked
from .speech_jobs import check_cancel, SpeechCancelled
from .whisper import WhisperClient, available as whisper_available

MAX_CAPTURE = 16000*2*8


class DisplayVoiceUnavailable(RuntimeError): pass


def capture_pcm(raw):
    if not 44<=len(raw)<=MAX_CAPTURE+4096:raise ValueError('Record up to eight seconds of mono 16 kHz PCM WAV')
    try:
        with wave.open(BytesIO(raw),'rb') as recording:
            frames=recording.getnframes()
            if recording.getnchannels()!=1 or recording.getsampwidth()!=2 or recording.getframerate()!=16000 or recording.getcomptype()!='NONE' or not 1600<=frames<=128000:
                raise ValueError()
            pcm=recording.readframes(frames)
            if len(pcm)!=frames*2:raise ValueError()
            return pcm
    except (wave.Error,EOFError,ValueError):raise ValueError('Record 0.1–8 seconds of mono 16 kHz, 16-bit PCM WAV') from None


def wave_bytes(pcm,rate):
    buffer=BytesIO()
    with wave.open(buffer,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(pcm)
    return buffer.getvalue()


class DisplayVoice:
    def __init__(self,root,settings,agent,*,transcriber=None,synthesizer=synthesize_checked):
        self.root,self.settings,self.agent=root,settings,agent
        self.worker,self.synthesizer=transcriber,synthesizer
        self.injected=transcriber is not None
        self.lock=Lock()

    def status(self):
        settings=self.settings.snapshot()[0]
        return {'available':bool(self.injected or settings.stt_engine=='whisper' and whisper_available(self.root)),
                'stt':'local_whisper','max_seconds':8,'sample_rate':16000,'channels':1,
                'mode':'push_to_talk','audio_destination':'requesting_display',
                'message':'Select local Whisper and install its runtime in Echo settings before using Pi speech.'}

    def respond(self,pcm,session,allow_home,reply_audio,*,cancel,progress):
        if not self.status()['available']:raise DisplayVoiceUnavailable('Local Whisper is not ready for Pi speech')
        if not self.lock.acquire(blocking=False):raise DisplayVoiceUnavailable('Another display speech request is in progress. Try again shortly.')
        result=None
        try:
            check_cancel(cancel);progress('transcribing')
            if self.worker is None:self.worker=WhisperClient(self.root)
            try:transcript=self.worker.transcribe(pcm)
            except (OSError,RuntimeError):
                self.worker.close();self.worker=None
                raise DisplayVoiceUnavailable('Local transcription stopped. Try again to reload the speech worker.') from None
            check_cancel(cancel)
            if not transcript:return {'status':'unavailable','capability':'conversation','text':'I did not catch that. Please try again.','transcript':''}
            result=self.agent.respond(transcript,session,cancel=cancel,allow_home_actions=allow_home,progress=progress,calendar_review=True)
            check_cancel(cancel)
            result={**result,'transcript':transcript,'audio_destination':'requesting_display'}
            if reply_audio and result.get('status')=='complete' and result.get('text'):
                progress('synthesizing')
                try:
                    pcm_out,metrics=self.synthesizer(result['text'][:1200],settings=self.settings.snapshot()[0],cancel=cancel)
                    check_cancel(cancel)
                    if metrics.get('sample_rate')!=48000 or not pcm_out or len(pcm_out)%2 or len(pcm_out)>48000*2*90:raise ValueError()
                    result['audio']={'format':'wav','data':base64.b64encode(wave_bytes(pcm_out,48000)).decode()}
                except SpeechCancelled:raise
                except (RuntimeError,ValueError,TimeoutError,OSError):result['audio_error']='The answer is ready, but speech could not be generated.'
            return result
        except SpeechCancelled:return {'status':'cancelled','capability':'conversation','text':'Request stopped.',
                                      'home_actions':result.get('home_actions',[]) if isinstance(result,dict) else []}
        except (OSError,RuntimeError) as error:
            if isinstance(error,DisplayVoiceUnavailable):raise
            raise DisplayVoiceUnavailable('Display speech could not complete. Check the local speech runtime.') from None
        finally:self.lock.release()

    def close(self):
        with self.lock:
            if self.worker:self.worker.close();self.worker=None


def install(app,pipeline,authorize,conversations,shutdown,*,enable_home=True,profile_state=None):
    from fastapi import Depends,HTTPException,Request
    from .conversation_activity import ConversationBusy
    from .conversation_request import run_conversation
    app.state.display_voice=pipeline

    @app.get('/v1/display/voice',dependencies=[Depends(authorize)])
    def status(session=Depends(authorize)):
        result=app.state.display_voice.status()
        if profile_state:result={**result,'access_revision':profile_state(session)['profile_revision']}
        return result

    @app.post('/v1/display/voice')
    async def voice(request:Request,allow_home:bool=False,reply_audio:bool=True,capture_id:str|None=None,session=Depends(authorize)):
        import re
        if capture_id is not None and not re.fullmatch(r"[a-f0-9]{32}",capture_id):raise HTTPException(422,"Invalid capture identifier")
        if request.headers.get('content-type','').split(';')[0] not in {'audio/wav','audio/x-wav'}:raise HTTPException(415,'Send PCM WAV audio')
        raw=bytearray()
        async for block in request.stream():
            raw.extend(block)
            if len(raw)>MAX_CAPTURE+4096:raise HTTPException(413,'Recording exceeds eight seconds')
        try:pcm=capture_pcm(bytes(raw))
        except ValueError as error:raise HTTPException(422,str(error)) from None
        try:activity=conversations.begin(session,capture_id=capture_id)
        except ConversationBusy as error:raise HTTPException(409,str(error)) from None
        from functools import partial
        try:
            result=await run_conversation(request,shutdown,partial(app.state.display_voice.respond,progress=activity.progress),
                pcm,session,allow_home and enable_home,reply_audio,activity=activity)
            authorize(request)  # Do not return a reply to an endpoint revoked during generation.
            return result
        except DisplayVoiceUnavailable as error:raise HTTPException(503,str(error)) from None

    @app.post('/v1/display/voice/{capture_id}/stop')
    def stop_capture(capture_id:str,session=Depends(authorize)):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}',capture_id):raise HTTPException(422,'Invalid capture identifier')
        try:return conversations.stop_capture(session,capture_id)
        except ConversationBusy as error:raise HTTPException(409,str(error)) from None

    @app.get('/v1/display/local-voice',dependencies=[Depends(authorize)])
    def native_status():return {'supported':False,'phase':'unavailable'}
