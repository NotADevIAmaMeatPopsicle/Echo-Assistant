"""Bounded framing for the local USB microphone stream, interleaved with status lines."""
import struct
import zlib

MAGIC = b"RV1!"
HEADER = struct.Struct("<4sBHI")


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0
        self.gaps = 0
        self.last_sequence = None
        self.header_errors = self.checksum_errors = self.noise_errors = self.console_frames = 0
        self.references = []

    def feed(self, data):
        self.buffer.extend(data)
        packets, lines = [], []
        self.references = []
        while self.buffer:
            if self.buffer.startswith(MAGIC):
                if len(self.buffer) < HEADER.size:
                    break
                _, kind, size, sequence = HEADER.unpack_from(self.buffer)
                if not ((kind == 1 and 0 < size <= 512 and size % 2 == 0) or (kind == 3 and size == 1024)):
                    self.header_errors += 1
                    del self.buffer[0]; self.errors += 1; continue
                total = HEADER.size + size + 4
                if len(self.buffer) < total:
                    break
                expected, = struct.unpack_from("<I", self.buffer, total-4)
                if zlib.crc32(self.buffer[:total-4]) != expected:
                    self.checksum_errors += 1
                    # Classify known firmware-log interference without keeping
                    # any corrupt bytes, which can contain microphone samples.
                    fragment = self.buffer[:total]
                    if any(marker in fragment for marker in (b'ssl_client', b'esp-tls', b'mbedtls', b'Guru Meditation')):
                        self.console_frames += 1
                    del self.buffer[0]; self.errors += 1; continue
                if self.last_sequence is not None and sequence != (self.last_sequence+1) & 0xffffffff:
                    self.gaps += 1
                self.last_sequence = sequence
                end = HEADER.size+(512 if kind == 3 else size)
                packets.append(bytes(self.buffer[HEADER.size:end]))
                self.references.append(bytes(self.buffer[end:total-4]) if kind == 3 else None)
                del self.buffer[:total]
            else:
                magic = self.buffer.find(MAGIC)
                newline = self.buffer.find(b"\n")
                if newline >= 0 and (magic < 0 or newline < magic):
                    line = bytes(self.buffer[:newline]).decode("utf-8", errors="replace").strip()
                    if line.startswith(("STATUS ", "EVENT ", "DEVICE ", "ERROR ", "NETWORK ", "USB ", "UI ", "RENDER ", "BUTTON ")):
                        lines.append(line)
                    del self.buffer[:newline+1]
                elif magic >= 0:
                    del self.buffer[:magic]
                else:
                    if len(self.buffer) > 2048:
                        self.noise_errors += 1
                        del self.buffer[:-3]; self.errors += 1
                    break
        return packets, lines


def encode_pcm(pcm, sequence, kind=1):
    if not 0 < len(pcm) <= 512 or len(pcm) % 2:
        raise ValueError("Invalid PCM frame length")
    if kind not in {1, 2}: raise ValueError("Invalid frame type")
    data = HEADER.pack(MAGIC, kind, len(pcm), sequence) + pcm
    return data + struct.pack("<I", zlib.crc32(data))
