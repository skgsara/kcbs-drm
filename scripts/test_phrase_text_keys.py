"""Regression tests for the phrase proposals on a short, non-repeating bulletin."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from phrase_text_keys import recover_records
from tail_fill_audit import crc


class ShortBulletinTests(unittest.TestCase):
    def test_received_checksum_gates_recovery_and_protects_existing_prefix(self):
        # Train only on individual fragments. The target record in its entirety
        # never occurs in the source corpus or twice in the test capture.
        text = ('평양과 청진에서는 비가 내리겠습니다. ' * 3)[:46]
        header_body = b'\x05\x1c' + text.encode('utf-16le')
        raw = header_body + crc(header_body).to_bytes(2,'big') + bytes([0xbb])*16
        keys = np.random.default_rng(51).integers(0,256,(3,16),dtype=np.uint8)
        cipher = np.frombuffer(raw,np.uint8).reshape(7,16) ^ keys[np.arange(7)//3]
        # Two more phases in the last group, beginning the next bulletin.
        cipher = np.vstack([cipher, keys[2] ^ np.frombuffer(header_body[:16],np.uint8),
                            keys[2] ^ np.frombuffer(header_body[16:32],np.uint8)])
        tails = {3*100+i:row for i,row in enumerate(cipher)}
        counters = list(range(100,103))
        known = np.zeros_like(keys, bool)
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            rows = [{'ok':True,'text':text[i:i+11]} for i in range(len(text)-10)]
            (directory/'items_test.json').write_text(json.dumps({'items':[rows]}))
            data = np.zeros_like(keys)
            records, recovered = recover_records(tails,counters,data,known,directory)
            self.assertEqual([r['text'] for r in records], [text])
            for i,c in enumerate(counters):
                np.testing.assert_array_equal(recovered[c],keys[i])
            altered = dict(tails)
            altered[305] = altered[305].copy()
            altered[305][15] ^= 1  # transmitted CRC, no candidate re-ranking allowed
            self.assertEqual(recover_records(altered,counters,data,known,directory),([],{}))
            damaged = dict(tails)
            del damaged[303]
            self.assertEqual(recover_records(damaged,counters,data,known,directory),([],{}))
            known[1,0] = True
            data[1,0] = keys[1,0] ^ 1
            self.assertEqual(recover_records(tails,counters,data,known,directory),([],{}))


if __name__=='__main__':
    unittest.main()
