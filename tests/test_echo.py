from pathlib import Path
import struct
import unittest
import zlib
from backend.cable import Decoder, HEADER, encode_pcm
from backend.echo import EchoCleaner, ROOT
from backend.runtime_paths import worker_python


class DuplexFramingTests(unittest.TestCase):
    def test_fragmented_duplex_keeps_mic_reference_pairs_and_legacy_audio(self):
        mic, ref = b'\x01\x02'*256, b'\x03\x04'*256
        body = HEADER.pack(b'RV1!',3,1024,1)+mic+ref
        stream = encode_pcm(mic,0)+b'STATUS duplex=1\n'+body+struct.pack('<I',zlib.crc32(body))
        decoder = Decoder(); packets = []; references = []
        for offset in range(0,len(stream),7):
            audio,_ = decoder.feed(stream[offset:offset+7]); packets.extend(audio); references.extend(decoder.references)
        self.assertEqual(packets,[mic,mic]);self.assertEqual(references,[None,ref])
        self.assertEqual((decoder.errors,decoder.gaps),(0,0))

    def test_corrupt_reference_rejects_the_entire_pair(self):
        body = HEADER.pack(b'RV1!',3,1024,0)+bytes(1024)
        stream = bytearray(body+struct.pack('<I',zlib.crc32(body)));stream[800]=1
        decoder=Decoder();self.assertEqual(decoder.feed(stream)[0],[])
        self.assertEqual(decoder.references,[]);self.assertEqual(decoder.checksum_errors,1)


@unittest.skipUnless(worker_python(ROOT,'aec').exists(), 'Explicit local AEC setup required')
class NativeEchoTests(unittest.TestCase):
    def test_quiet_speaker_needs_reference_before_volume_attenuation(self):
        import numpy as np
        rng = np.random.default_rng(7); count = 16000*6
        attenuated = rng.normal(0,32,count).astype('<i2')
        mic = np.zeros(count,dtype='<i2'); mic[800:] = (attenuated[:-800].astype(float)*60).astype('<i2')
        reductions = []
        for gain in (1,100):
            cleaner = EchoCleaner(); output = []
            try:
                reference = (attenuated.astype(float)*gain).clip(-32768,32767).astype('<i2')
                for offset in range(0,count-255,256):
                    output.append(cleaner.process_frame(mic[offset:offset+256].tobytes(), reference[offset:offset+256].tobytes()))
            finally: cleaner.close()
            cleaned = np.frombuffer(b''.join(output),dtype='<i2').astype(float)
            reductions.append(10*np.log10(np.mean(mic[48000:len(cleaned)].astype(float)**2)/max(1.,np.mean(cleaned[48000:]**2))))
        self.assertGreater(reductions[1], 10)
        self.assertGreater(reductions[1]-reductions[0], 10)

    def test_delayed_echo_is_suppressed_in_real_native_processor(self):
        import numpy as np
        rng=np.random.default_rng(7);count=16000*6
        far=rng.normal(0,3000,count).astype('<i2')
        near=np.zeros(count,dtype='<i2');near[800:]=(far[:-800]*.45).astype('<i2')
        cleaner=EchoCleaner();self.addCleanup(cleaner.close);clean=[]
        for offset in range(0,count-255,256):
            clean.append(cleaner.process_frame(near[offset:offset+256].tobytes(),far[offset:offset+256].tobytes()))
        output=np.frombuffer(b''.join(clean),dtype='<i2').astype(float)
        original=near[:len(output)].astype(float);start=16000*3
        reduction=10*np.log10(np.mean(original[start:]**2)/max(1.,np.mean(output[start:]**2)))
        self.assertGreater(reduction,10)
        cleaner.reset()
        self.assertEqual(len(cleaner.process_frame(bytes(512),bytes(512))),320)

    def test_dead_worker_and_invalid_frame_fail_without_hanging(self):
        cleaner=EchoCleaner();self.addCleanup(cleaner.close)
        with self.assertRaises(ValueError):cleaner.process_frame(bytes(100),bytes(512))
        cleaner.process.terminate();cleaner.process.wait(timeout=2)
        with self.assertRaises(RuntimeError):cleaner.process_frame(bytes(512),bytes(512))


if __name__ == '__main__': unittest.main()
