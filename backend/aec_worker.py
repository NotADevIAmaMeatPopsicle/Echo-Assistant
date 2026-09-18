"""Private binary-pipe WebRTC worker. No network, files, recording, or transcript output."""
import struct
import sys
from aec_audio_processing import AudioProcessor


def processor():
    result = AudioProcessor(enable_aec=True, enable_ns=False, enable_agc=False, enable_vad=False)
    result.set_stream_format(16000, 1)
    result.set_reverse_stream_format(16000, 1)
    result.set_stream_delay(50)
    return result


def read_exact(size):
    data = bytearray()
    while len(data) < size:
        part = sys.stdin.buffer.read(size-len(data))
        if not part: return None
        data.extend(part)
    return bytes(data)


def main():
    audio = processor(); microphone = bytearray(); reference = bytearray()
    while True:
        header = read_exact(4)
        if header is None: return
        size, = struct.unpack('<I', header)
        if size == 0:
            audio = processor(); microphone.clear(); reference.clear(); output = b''
        elif size == 1024:
            data = read_exact(size)
            if data is None: return
            microphone.extend(data[:512]); reference.extend(data[512:])
            output = bytearray()
            while len(microphone) >= 320:
                audio.process_reverse_stream(bytes(reference[:320]))
                audio.set_stream_delay(50)
                cleaned = audio.process_stream(bytes(microphone[:320]))
                if len(cleaned) != 320: raise RuntimeError('Invalid processing frame')
                output.extend(cleaned)
                del microphone[:320]; del reference[:320]
        else:
            raise ValueError('Invalid private audio frame')
        sys.stdout.buffer.write(struct.pack('<I', len(output))+output)
        sys.stdout.buffer.flush()


if __name__ == '__main__': main()
