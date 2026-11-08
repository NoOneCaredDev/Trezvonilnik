import os
import unittest
from network.protocol import (Packet, PacketType, encode, decode, split_fragments, parse_fragment)
from network.reassembly import FragmentReassembler


class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self):
        packet = Packet(PacketType.AUDIO, 42, 7, b"hello")
        self.assertEqual(decode(encode(packet, "secret"), "secret"), packet)

    def test_reject_wrong_password(self):
        raw = encode(Packet(PacketType.HEARTBEAT, 1, 1, b""), "right")
        with self.assertRaises(ValueError):
            decode(raw, "wrong")

    def test_new_packet_types_roundtrip(self):
        for kind in (PacketType.CONTROL, PacketType.SFX, PacketType.MUSIC, PacketType.BLOB, PacketType.PONG):
            p = Packet(kind, 5, 9, b"x" * 100)
            self.assertEqual(decode(encode(p, "k"), "k"), p)


class FragmentTests(unittest.TestCase):
    def test_reassemble_out_of_order(self):
        data = os.urandom(50_000)
        frags = split_fragments(7, data)
        self.assertGreater(len(frags), 40)
        self.assertTrue(all(len(f) < 1200 for f in frags))
        asm = FragmentReassembler()
        out = None
        for f in reversed(frags):
            out = asm.feed(1, f) or out
        self.assertEqual(out, data)

    def test_lost_fragment_never_completes(self):
        frags = split_fragments(1, os.urandom(10_000))
        asm = FragmentReassembler()
        self.assertTrue(all(asm.feed(1, f) is None for f in frags[:-1]))

    def test_latest_only_drops_stale_frames(self):
        asm = FragmentReassembler(latest_only=True)
        old, new = split_fragments(1, b"a" * 3000), split_fragments(2, b"b" * 3000)
        for f in new:
            last = asm.feed(9, f)
        self.assertEqual(last, b"b" * 3000)
        self.assertTrue(all(asm.feed(9, f) is None for f in old))   # запоздавший кадр игнорируется

    def test_expired_partial_is_collected(self):
        asm = FragmentReassembler(ttl=1.0)
        frags = split_fragments(1, b"z" * 5000)
        asm.feed(1, frags[0], now=0.0)
        asm.feed(1, split_fragments(2, b"q")[0], now=5.0)
        self.assertNotIn((1, 1), asm._pending)

    def test_bad_header(self):
        with self.assertRaises(ValueError):
            parse_fragment(b"\x00\x01")


if __name__ == "__main__":
    unittest.main()
