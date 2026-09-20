import re
import struct
import unittest
import zlib

from backend.timed_speaker import DeviceClock, TimedSpeaker, encode_timed


class TimedSpeakerTests(unittest.TestCase):
    def setUp(self):
        self.now=100.;self.writes=[]
        self.sender=TimedSpeaker(self.writes.append,clock=lambda:self.now)

    def sync(self):
        self.sender.receive('STATUS timed_audio=1');self.sender.focus(True)
        for _ in range(3):
            self.sender.pump();nonce=int(re.search(rb'GROUP_CLOCK (\d+)',self.writes[-1])[1])
            device=round(self.now*1_000_000)+5001000;self.now+=.002
            self.sender.receive(f'EVENT group_clock={nonce} device_us={device}');self.now+=.25
        self.assertTrue(self.sender.device_clock.ready)

    def test_clock_needs_matching_low_latency_samples_and_expires(self):
        self.sync();self.assertEqual(self.sender.device_clock.offset,5000000)
        self.assertEqual(self.sender.device_clock.quality_us,1000)
        self.now+=6;self.assertFalse(self.sender.device_clock.ready)
        clock=DeviceClock(lambda:self.now);probe=clock.probe();nonce=int(probe.split()[1]);self.now+=.1
        clock.receive(f'EVENT group_clock={nonce} device_us=150000000')
        self.assertFalse(clock.ready);self.assertEqual(len(clock.samples),0)

    def test_no_negotiation_or_focus_never_sends_audio(self):
        self.sender.focus(True);self.sender.pump();self.assertEqual(self.writes,[])
        self.sync();self.sender.focus(False);self.sender.append(b'\0'*512,round(self.now*1e6)+300000);self.sender.pump()
        self.assertFalse(self.sender.active);self.assertFalse(any(w.startswith(b'RV1!') for w in self.writes))

    def test_session_timestamp_and_checksum_are_bound_to_each_frame(self):
        self.sync();at=round(self.now*1e6)+350000
        self.sender.append(b'\1\0'*256,at);self.sender.pump();session=self.sender.session
        self.assertTrue(session);self.assertEqual(self.sender.sent,0)
        self.sender.receive(f'EVENT group_ready={session} capacity=256');self.sender.pump()
        packet=self.writes[-1];self.assertEqual(len(packet),539)
        magic,kind,size,sequence=struct.unpack_from('<4sBHI',packet)
        self.assertEqual((magic,kind,size,sequence),(b'RV1!',4,524,0))
        self.assertEqual(struct.unpack_from('<IQ',packet,11),(session,at+5000000))
        self.assertEqual(struct.unpack_from('<I',packet,535)[0],zlib.crc32(packet[:-4]))
        self.sender.receive(f'EVENT group_session={session} received=1 consumed=1 active=1 late=0 missing=0')
        self.assertEqual(self.sender.consumed,1)

    def test_backpressure_late_drop_volume_limit_and_focus_stop(self):
        self.sync();at=round(self.now*1e6)+350000
        self.sender.append(b'\0'*512*200,at);self.sender.pump();session=self.sender.session
        self.sender.receive(f'EVENT group_ready={session} capacity=256')
        for _ in range(10):self.sender.pump()
        self.assertEqual(self.sender.sent,96)
        self.sender.volume(100);self.assertEqual(self.writes[-1],f'GROUP_GAIN {session} 2\n'.encode())
        self.sender.focus(False);self.assertEqual(self.writes[-1],f'GROUP_STOP {session}\n'.encode())
        self.assertFalse(self.sender.queue);self.assertFalse(self.sender.active)
        self.sender.focus(True);self.sender.append(b'\0'*512,round(self.now*1e6)-10000);self.sender.pump()
        self.assertFalse(self.sender.active);self.assertEqual(self.sender.dropped,1)

    def test_invalid_credits_timeout_and_old_session_do_not_continue(self):
        self.sync();self.sender.append(b'\0'*512,round(self.now*1e6)+350000);self.sender.pump();session=self.sender.session
        self.sender.receive(f'EVENT group_ready={session+1} capacity=256');self.assertEqual(self.sender.capacity,0)
        with self.assertRaises(RuntimeError):self.sender.receive(f'EVENT group_session={session} received=5 consumed=0 active=1')
        self.assertFalse(self.sender.active)
        self.sender.append(b'\0'*512,round(self.now*1e6)+350000);self.sender.pump();self.now+=2.1
        with self.assertRaises(RuntimeError):self.sender.pump()
        self.assertFalse(self.sender.active)

    def test_partial_packets_and_disconnect_clear(self):
        self.sync();at=round(self.now*1e6)+350000
        self.sender.append(b'\1\0'*128,at);self.assertEqual(len(self.sender.queue),0)
        self.sender.append(b'\2\0'*128,at+2667);self.assertEqual(len(self.sender.queue),1)
        self.assertEqual(self.sender.queue[0][1],b'\1\0'*128+b'\2\0'*128)
        self.sender.receive('STATUS timed_audio=0');self.assertFalse(self.sender.queue);self.assertFalse(self.sender.allowed)
        with self.assertRaises(ValueError):encode_timed(b'\0'*512,0,0,at)


if __name__=='__main__':unittest.main()
