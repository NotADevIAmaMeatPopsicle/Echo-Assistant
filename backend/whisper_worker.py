"""Isolated offline Whisper worker. Fixed local assets, framed RAM-only PCM, no downloads."""
import json
import logging
from pathlib import Path
import socket
import struct
import sys


def block_network(*args, **kwargs):
    raise RuntimeError('Network is disabled in the local recognition worker')


def read_exact(size):
    buffer = bytearray()
    while len(buffer) < size:
        data = sys.stdin.buffer.read(size-len(buffer))
        if not data: return None
        buffer.extend(data)
    return buffer


def send(value):
    data = json.dumps(value).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('<I', len(data))+data)
    sys.stdout.buffer.flush()


def main():
    logging.disable(logging.CRITICAL)
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = block_network
    import numpy as np
    from faster_whisper import WhisperModel
    root = Path(__file__).resolve().parents[1]
    model = WhisperModel(str(root/'local/models/faster-whisper-base.en'), device='cpu', compute_type='int8',
                         cpu_threads=2, num_workers=1, local_files_only=True)
    send({'ready': True})
    while True:
        header = read_exact(4)
        if header is None: return
        size, = struct.unpack('<I', header)
        if not 0 < size <= 16000*2*8 or size % 2: return
        data = read_exact(size)
        if data is None: return
        samples = np.frombuffer(data, dtype='<i2').astype(np.float32)/32768
        segments, _ = model.transcribe(samples, language='en', beam_size=5, condition_on_previous_text=False,
                                       vad_filter=False)
        send({'segments': [{'text': s.text, 'no_speech_prob': s.no_speech_prob, 'avg_logprob': s.avg_logprob,
                            'compression_ratio': s.compression_ratio} for s in segments]})
        del data, samples, segments


if __name__ == '__main__': main()
