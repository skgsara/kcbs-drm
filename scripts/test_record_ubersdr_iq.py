from contextlib import nullcontext, redirect_stderr, redirect_stdout
import csv
from email.message import Message
from hashlib import sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import record_ubersdr_iq as recorder
from demod_iq_window import input_info


class UberSDRRecordingTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.output = Path(tmp.name) / "capture.wav"

    def run_capture(self, packets, chunks, code, *, packet_timing=False, output=None):
        output = self.output if output is None else output
        args = ["https://example.org", "--frequency-hz", "3205000", "--seconds", "1",
                "--ubersdr-source", ".", "--out", str(output)]
        if packet_timing:
            args.append("--packet-timing")
        websocket = Mock()
        websocket.recv.side_effect = packets
        decoder = Mock()
        decoder.decode_packet_le.side_effect = chunks
        out = StringIO()
        with patch.object(recorder, "upstream_decoder", return_value=decoder), \
                patch.object(recorder, "open_stream", return_value=nullcontext(websocket)), redirect_stdout(out):
            status = recorder.main(args)
        self.assertEqual(status, code)
        report = json.loads(out.getvalue())
        with wave.open(str(output)) as stream:
            self.assertEqual((stream.getnchannels(), stream.getframerate(), stream.getsampwidth()), (2, 48000, 2))
            self.assertEqual(stream.getnframes(), report["sample_pairs"])
            pcm = stream.readframes(stream.getnframes())
        return report, pcm

    @staticmethod
    def packet(samples, timestamp, rate=48000, iq_pair=b"\x01\x00\xff\xff"):
        return (iq_pair * samples,
                SimpleNamespace(sample_rate=rate, channels=2, shift=0, sample_count=samples*2,
                                timestamp_nanos=timestamp))

    def test_grant_requires_explicit_iq48_and_uses_one_public_json_request(self):
        headers = Message()
        headers["Content-Type"] = "application/json; charset=utf-8"
        for body, accepted in (({"allowed": True, "allowed_iq_modes": ["iq48"]}, True),
                               ({"allowed": True, "allowed_iq_modes": ["iq96"]}, False),
                               ({"allowed": False, "allowed_iq_modes": ["iq48"]}, False)):
            with self.subTest(body=body), patch.object(recorder, "build_opener") as factory:
                reply = BytesIO(json.dumps(body).encode())
                reply.status, reply.headers = 200, headers
                opener = factory.return_value.open
                opener.return_value = reply
                context = nullcontext() if accepted else self.assertRaises(ValueError)
                with context:
                    recorder.grant("https://example.org", "abc", None)
                opener.assert_called_once()
                req = opener.call_args.args[0]
                self.assertEqual((req.full_url, req.get_method()), ("https://example.org/connection", "POST"))
                self.assertEqual(json.loads(req.data), {"user_session_id": "abc"})

    def test_early_disconnect_preserves_partial_wav_and_existing_output(self):
        chunk = self.packet(123, 1_000_000_000)
        report, pcm = self.run_capture([b"A", TimeoutError("idle")], [chunk], 1)
        self.assertFalse(report["sample_target_reached"])
        self.assertEqual((report["sample_pairs"], report["sample_seconds"], pcm), (123, 123/48000, chunk[0]))
        with patch.object(recorder, "open_stream") as network, self.assertRaises(FileExistsError):
            recorder.record("https://example.org", 3205000, 1, self.output, Mock())
        network.assert_not_called()

    def test_denial_yields_no_samples(self):
        report, pcm = self.run_capture(['{"type":"denied"}'], [], 1)
        self.assertFalse(report["sample_target_reached"])
        self.assertEqual((report["sample_pairs"], pcm), (0, b""))

    def test_exact_length_and_discontinuity_are_independent(self):
        for jump_ns, expected_code in ((0, 0), (2_000_000, 1)):
            with self.subTest(jump_ns=jump_ns):
                chunks = [self.packet(24000, 1_000_000_000), self.packet(24010, 1_500_000_000 + jump_ns)]
                report, pcm = self.run_capture([b"A", b"B"], chunks, expected_code)
                self.assertTrue(report["sample_target_reached"])
                self.assertEqual(input_info(self.output, None), (48000, 48000))
                self.assertEqual(len(pcm), 48000*4)
                self.assertEqual(report["timestamp_jumps_over_one_sample"], int(bool(jump_ns)))
                self.assertEqual(report["max_abs_timestamp_jump_ns"], jump_ns)
                self.output.unlink()

    def test_packet_timing_records_original_anchors_and_clipped_sample_counts(self):
        chunks = [
            self.packet(4800, 0, iq_pair=b"\x01\x00\x02\x00"),
            self.packet(12000, 2_000_000_000, iq_pair=b"\x03\x00\x04\x00"),
            self.packet(4800, 2_253_000_000, iq_pair=b"\x05\x00\x06\x00"),
            self.packet(30000, 2_351_000_000, iq_pair=b"\x07\x00\x08\x00"),
        ]
        messages = [b"A", b"B", b"C", b"D"]
        plain_wav = self.output.with_name("plain.wav")
        plain, plain_pcm = self.run_capture(messages, chunks, 1, output=plain_wav)
        self.assertFalse(plain_wav.with_name("plain.wav.timing.csv").exists())
        timed, timed_pcm = self.run_capture(messages, chunks, 1, packet_timing=True)
        with self.output.with_name("capture.wav.timing.csv").open(newline="") as fp:
            self.assertEqual(list(csv.reader(fp)), [
                ["sample_offset", "sample_pairs", "receiver_unix_ns"],
                ["0", "4800", ""],
                ["4800", "12000", "2000000000"],
                ["16800", "4800", "2253000000"],
                ["21600", "26400", "2351000000"],
            ])
        for receipt in (plain, timed):
            self.assertTrue(receipt["sample_target_reached"])
            self.assertEqual(receipt["timestamped_packets"], 3)
            self.assertEqual(receipt["timestamp_jumps_over_one_sample"], 2)
            self.assertEqual(receipt["max_abs_timestamp_jump_ns"], 3_000_000)
        expected = b"".join(pcm for pcm, _ in chunks)[:48000 * 4]
        self.assertEqual(timed_pcm, expected)
        self.assertEqual(plain_pcm, timed_pcm)
        self.assertEqual(plain["iq_pcm_sha256"], sha256(expected).hexdigest())
        self.assertEqual(timed["iq_pcm_sha256"], plain["iq_pcm_sha256"])

    def test_packet_timing_disconnect_preserves_only_recorded_samples(self):
        chunk = self.packet(123, 8_765_432_109)
        messages = [b"A", '{"type":"disconnect"}']
        report, pcm = self.run_capture(messages, [chunk], 1, packet_timing=True)
        self.assertFalse(report["sample_target_reached"])
        self.assertEqual(pcm, chunk[0])
        self.assertEqual(report["iq_pcm_sha256"], sha256(pcm).hexdigest())
        with self.output.with_name("capture.wav.timing.csv").open(newline="") as fp:
            self.assertEqual(list(csv.reader(fp)), [
                ["sample_offset", "sample_pairs", "receiver_unix_ns"],
                ["0", "123", "8765432109"],
            ])

    def test_packet_timing_collision_preserves_prior_file_before_connection(self):
        sidecar = self.output.with_name("capture.wav.timing.csv")
        sidecar.write_bytes(b"existing packet timing\n")
        args = ["https://example.org", "--frequency-hz", "3205000", "--seconds", "1",
                "--ubersdr-source", ".", "--out", str(self.output), "--packet-timing"]
        with patch.object(recorder, "upstream_decoder"), patch.object(recorder, "open_stream") as network, \
                redirect_stderr(StringIO()):
            self.assertNotEqual(recorder.main(args), 0)
        network.assert_not_called()
        self.assertEqual(sidecar.read_bytes(), b"existing packet timing\n")


if __name__ == "__main__":
    unittest.main()
