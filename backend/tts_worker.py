"""Resident CPU TTS worker. Local assets only; bounded PCM, no network or audio devices."""
import contextlib
import json
import logging
import os
from pathlib import Path
import socket
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_PCM = 48000*2*90
NETWORK_ATTEMPTS = 0


def block_network(*args, **kwargs):
    global NETWORK_ATTEMPTS
    NETWORK_ATTEMPTS += 1
    raise RuntimeError('Network is disabled in the local speech worker')


def harden_environment():
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      DO_NOT_TRACK='1', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    socket.socket.connect = block_network
    socket.socket.connect_ex = block_network
    socket.create_connection = block_network
    socket.getaddrinfo = block_network
    logging.disable(logging.CRITICAL)


def verify_model(engine):
    sys.path.insert(0,str(ROOT))
    from tools.download_tts_models import verify
    manifest = json.loads((ROOT/'config/tts-models.json').read_text(encoding='utf-8'))
    model = next(m for m in manifest['models'] if m['directory'].startswith(engine+'-'))
    folder = ROOT/'local/models'/model['directory']
    if not all(verify(folder/a['path'],a) for a in model['assets']):
        raise RuntimeError('Local speech asset integrity check failed')
    return folder


class LocalModel:
    def __init__(self, engine):
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        self.engine = engine
        self.folder = verify_model(engine)
        self.voices = {}
        if engine == 'kokoro':
            from kokoro import KModel
            self.model = KModel(repo_id='hexgrad/Kokoro-82M',config=str(self.folder/'config.json'),
                                model=str(self.folder/'kokoro-v1_0.pth')).eval()
            # Require exact compatibility even if upstream's permissive loader succeeds.
            for name,state in torch.load(self.folder/'kokoro-v1_0.pth',map_location='cpu',weights_only=True).items():
                module = getattr(self.model,name)
                if set(state)!=set(module.state_dict()): state={k.removeprefix('module.'):v for k,v in state.items()}
                # Kokoro 0.9.4 adds identity affine parameters for ONNX export;
                # the official checkpoint predates them. Permit only those constants.
                for key in module.state_dict().keys()-state.keys():
                    path,parameter = key.rsplit('.',1)
                    norm = module.get_submodule(path)
                    if not isinstance(norm,torch.nn.InstanceNorm1d) or parameter not in {'weight','bias'}:
                        raise RuntimeError('Unexpected missing Kokoro parameter')
                    value = getattr(norm,parameter)
                    state[key] = torch.ones_like(value) if parameter=='weight' else torch.zeros_like(value)
                module.load_state_dict(state,strict=True)
            self.pipelines = {}
        elif engine == 'pocket':
            from pocket_tts import TTSModel
            import yaml
            from tools.prepare_tts import expected_config
            if yaml.safe_load((ROOT/'local/pocket-english-local.yaml').read_text(encoding='utf-8')) != expected_config(ROOT):
                raise RuntimeError('Run explicit TTS setup to prepare the local model paths')
            self.model = TTSModel.load_model(config=ROOT/'local/pocket-english-local.yaml')
            self.model.has_voice_cloning = False
        else: raise ValueError('Unsupported local speech engine')

    def chunks(self, text, voice, rate):
        import torch
        if self.engine == 'kokoro':
            from kokoro import KPipeline
            allowed = {p.stem for p in (self.folder/'voices').glob('*.pt')}
            if voice not in allowed: raise ValueError('Unsupported voice')
            language = voice[0]
            if language not in self.pipelines:
                import spacy
                if not spacy.util.is_package('en_core_web_sm'):
                    raise RuntimeError('Install the pinned English language package using explicit setup')
                self.pipelines[language] = KPipeline(lang_code=language,repo_id='hexgrad/Kokoro-82M',model=self.model,device='cpu')
            if voice not in self.voices:
                self.voices[voice] = torch.load(self.folder/'voices'/f'{voice}.pt',map_location='cpu',weights_only=True)
            for result in self.pipelines[language](text,voice=self.voices[voice],speed=1+rate*.06):
                if result.audio is not None: yield result.audio.detach().cpu().numpy()
        else:
            from backend.tts_catalog import POCKET_VOICES
            if voice not in POCKET_VOICES or rate != 0: raise ValueError('Unsupported Pocket voice or pace')
            if voice not in self.voices:
                self.voices[voice] = self.model.get_state_for_audio_prompt(self.folder/'languages/english/embeddings'/f'{voice}.safetensors')
            for chunk in self.model.generate_audio_stream(self.voices[voice],text,copy_state=True):
                yield chunk.detach().cpu().numpy()

    def synthesize(self, request):
        import numpy as np
        import soxr
        text,voice,rate = request.get('text'),request.get('voice'),request.get('rate')
        if not isinstance(text,str) or not 1<=len(text.strip())<=1200 or not isinstance(voice,str) or type(rate)!=int or not -5<=rate<=5:
            raise ValueError('Invalid synthesis request')
        started = time.monotonic(); first = None; source = []
        total = 0
        for chunk in self.chunks(text.strip(),voice,rate):
            if first is None: first = time.monotonic()-started
            chunk = np.asarray(chunk,dtype=np.float32).reshape(-1)
            if not np.all(np.isfinite(chunk)): raise ValueError('Nonfinite speech output')
            total += len(chunk)
            if total > 24000*90 or time.monotonic()-started>55: raise ValueError('Speech exceeded bounds')
            source.append(chunk)
        if not source or total<240: raise ValueError('Speech output missing')
        pcm = soxr.resample(np.concatenate(source),24000,48000,quality='HQ')
        peak = float(np.max(np.abs(pcm)))
        if peak>0.95: pcm *= .95/peak
        pcm = np.clip(pcm,-1,1)
        rms = float(np.sqrt(np.mean(pcm*pcm)))
        if rms<.00005: raise ValueError('Speech output is silent')
        return {'ok':True,'engine':self.engine,'sample_rate':48000,'seconds':round(len(pcm)/48000,3),
                'generation_ms':round((time.monotonic()-started)*1000),'first_chunk_ms':round((first or 0)*1000),
                'peak':round(min(peak,.95),4),'rms':round(rms,4),'network_attempts':NETWORK_ATTEMPTS}, (pcm*32767).astype('<i2').tobytes()


def read_exact(stream,size):
    data = bytearray()
    while len(data)<size:
        chunk = stream.read(size-len(data))
        if not chunk: return None
        data.extend(chunk)
    return data


def send(stream, metadata, pcm=b''):
    data = json.dumps(metadata).encode('utf-8')
    stream.write(struct.pack('<II',len(data),len(pcm))+data+pcm); stream.flush()


def main():
    wire = sys.stdout.buffer
    harden_environment()
    with open(os.devnull,'w') as silent, contextlib.redirect_stdout(silent), contextlib.redirect_stderr(silent):
        try: model = LocalModel(sys.argv[1])
        except Exception:
            send(wire,{'ok':False,'error':'load_failed','network_attempts':NETWORK_ATTEMPTS}); return
        send(wire,{'ok':True,'ready':True,'engine':model.engine,'network_attempts':NETWORK_ATTEMPTS})
        while True:
            header = read_exact(sys.stdin.buffer,4)
            if header is None: return
            size, = struct.unpack('<I',header)
            if not 1<=size<=12000: return
            raw = read_exact(sys.stdin.buffer,size)
            if raw is None: return
            try: metadata,pcm = model.synthesize(json.loads(raw))
            except Exception:
                send(wire,{'ok':False,'error':'synthesis_failed','network_attempts':NETWORK_ATTEMPTS}); continue
            send(wire,metadata,pcm)
            del raw,pcm,metadata


if __name__ == '__main__': main()
