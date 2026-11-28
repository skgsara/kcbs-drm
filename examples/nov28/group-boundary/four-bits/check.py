"""Replay two native phase-zero records; compare only published, directly carried field checks."""
import argparse
from binascii import crc_hqx
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory

import numpy as np


HERE = Path(__file__).resolve().parent
COUNTER = 43908300
SLOT = 8
HEADERS = (0x80, 0x01, 0x02, 0x43)
SOURCES = {
    "3205": (1120, "963c60f81ba65d2149e856e9d26e8684bd7bdf527b014d4223027c2ac0ad3477",
             "6b13ab140ec357f717585de45f3a0ce4868c66279ecf47e0c5422dedb34cb71f"),
    "6140": (434, "fea03f5d0276dd3f754731d3f05ac6b595ef0aa051672463ba5b08fdfc9179fe",
             "abcbee7e5df39d6847ddd99104d6d8839cc9533cf8d1222038a7d71401fcdd7f"),
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def crc(data):
    return crc_hqx(data, 0xffff) ^ 0xffff


def original_record(path, ordinal, expected_hash):
    data = path.read_bytes()
    require(sha256(data).hexdigest() == expected_hash, "full MSC source hash mismatch")
    offset = 0
    for index in range(ordinal+1):
        require(offset+4 <= len(data), "truncated native record length")
        size, = struct.unpack_from("<I", data, offset)
        end = offset+4+size
        require(0 < size <= 1024*1024 and end <= len(data), "invalid native record length")
        if index == ordinal:
            return data[offset:end]
        offset = end


def read_record(carrier, complete_source):
    index, full_hash, excerpt_hash = SOURCES[carrier]
    raw = (HERE / f"{carrier}-phase0.msc.bin").read_bytes()
    require(sha256(raw).hexdigest() == excerpt_hash, f"{carrier} excerpt hash mismatch")
    require(len(raw) == 732 and struct.unpack_from("<I",raw)[0] == 728, "expected one native MSC record")
    if complete_source is not None:
        require(raw == original_record(complete_source,index,full_hash), f"{carrier} native slice differs")
    packets = [raw[4+182*q:4+182*(q+1)] for q in range(4)]
    report = []
    for q, packet in enumerate(packets):
        computed = crc(packet[:180])
        sent = int.from_bytes(packet[180:], "big")
        if computed == sent:
            require(packet[0] == HEADERS[q], f"unexpected packet header {q}")
        report.append(dict(ordinal=q, header_hex=f"{packet[0]:02x}", sent_crc=f"{sent:04x}",
                           calculated_crc=f"{computed:04x}", received=(computed == sent)))
    flags = [p["received"] for p in report]
    require(flags == ([True,False,True,True] if carrier=="3205" else [True]*4), "unexpected flags")
    body = b"".join(p[1:180] for p in packets)
    require((body[1] >> 4, int.from_bytes(body[664:668],"big")) == (0,COUNTER), "counter or phase mismatch")
    du_crc = crc(body[:714])
    sent_du_crc = int.from_bytes(body[714:], "big")
    require((du_crc == sent_du_crc) == all(flags), "unexpected DU CRC")
    return body, flags, dict(source_record=index, source_msc_sha256=full_hash, excerpt_sha256=excerpt_hash,
                              packets=report, sent_du_crc=f"{sent_du_crc:04x}", calculated_du_crc=f"{du_crc:04x}")


def project(body, flags, temp, poison=0):
    from evs_evidence import bit_evidence, field_sections
    from project_evs_group import project_group
    packets = np.frombuffer(body, dtype=np.uint8).reshape(1,4,179).copy()
    packets[0,~np.asarray(flags,dtype=bool),:] = poison
    np.savez(temp,ticks=np.array([3*COUNTER]),packets=packets,packet_ok=np.array([flags]))
    projection = project_group(temp, COUNTER, packets=True)
    projection.update(field_sections(projection["slots"]))
    row = bit_evidence(projection)["slots"][SLOT]
    require((row["phase"],row["cycle"],row["position"]) == (0,2,1), "unexpected target coordinates")
    return row


def predicates(row):
    return {event["check"]: {key:event[key] for key in ("word_bits","inputs","allowed_values","fixed_bits")}
            for event in row["events"]}


def audit(source_3205, source_6140):
    member, member_flags, member_info = read_record("3205", source_3205)
    with TemporaryDirectory() as directory:
        temp = Path(directory)/"phase.npz"
        source = project(member,member_flags,temp)
        require(all(e["observation"]=="no_receipt" and e["observed"] is None for e in source["events"]),
                "3205 target must be absent from both direct checks")
        require(source == project(member,member_flags,temp,poison=255),
                "unobserved packet storage changed source evidence")
        frozen = predicates(source)
        require(set(frozen) == {"inactive_nibble","swb_gsc_inactive"}, "unexpected target rule set")
        require(frozen["inactive_nibble"]["inputs"] == [dict(slot=SLOT,word_bits=[0,6],observed=29,role="condition")],
                "unexpected upper-nibble sources")
        require(frozen["swb_gsc_inactive"]["inputs"] == [dict(slot=SLOT,word_bits=[0,5],observed=14,role="condition")],
                "unexpected lower-nibble sources")
        peer, peer_flags, peer_info = read_record("6140", source_6140)
        # Hide the peer target packet and use its remaining received octets to repeat the conditions.
        blocked = project(peer,member_flags,temp)
        require(predicates(blocked)==frozen, "peer target was needed to derive a field restriction")
        require(all(e["observed"] is None for e in blocked["events"]), "peer blind control retained target")
        missing_mode_flags = [False,False,True,True]
        require(not project(member,missing_mode_flags,temp)["events"], "rule fired without its source mode")
        opened = project(peer,peer_flags,temp)
        require(predicates(opened)==frozen and all(e["outcome"]=="match" for e in opened["events"]),
                "published rules or peer observations differ")
    require(member[4] == peer[4] == 0x74, "mode disagrees")
    require(peer[273] == 0xc1, "peer target octet differs")
    delta = [i for i,(a,b) in enumerate(zip(member,peer,strict=True)) if a!=b]
    require(delta==[211] and (member[211]^peer[211]).bit_count()==4, "raw discrepancy changed")
    source_hex = json.dumps(frozen,sort_keys=True,separators=(",",":")).encode()
    return dict(counter=COUNTER,slot=SLOT,phase=0,cycle=2,position=1,
                source_target_word_erased=source["word_erased"], peer_target_word_erased=opened["word_erased"],
                source_3205=member_info,peer_6140=peer_info,domain_sha256=sha256(source_hex).hexdigest(),
                source_mode=dict(du_byte=4, packet=0, hex="74"),
                peer_target=dict(payload_octet=4, du_byte=273,packet=1,packet_body_offset=94, hex="c1"),
                rules={e["check"]: frozen[e["check"]] | dict(peer_value=e["observed"],peer_outcome=e["outcome"])
                       for e in opened["events"]},
                absent_packet_zero_vs_ff_same=True,peer_target_packet_withheld_same=True,
                missing_source_packet_abstains=True,raw_unaccepted_3205_target_happens_to_equal_peer=member[273]==peer[273],
                native_du_differing_octets=delta,native_du_differing_bits=4)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts",type=Path,required=True,help="public KCBS repository scripts directory")
    parser.add_argument("--original-3205",type=Path,help="optional complete, hash-checked 3205 MSC")
    parser.add_argument("--original-6140",type=Path,help="optional complete, hash-checked 6140 MSC")
    args=parser.parse_args()
    sys.path.insert(0,str(args.scripts.resolve()))
    print(json.dumps(audit(args.original_3205,args.original_6140),indent=2))
