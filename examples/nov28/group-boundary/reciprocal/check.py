"""Reproduce the reciprocal, CRC-gated within-group checks for 119 shared counters."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import check_dual_rf as dual
from evs_evidence import bit_evidence, field_sections
from project_evs_group import project_group
from salvage_msc_packets import PACKET_HEADERS
from tail_fill_audit import crc

FREEZE = '05e4272223a4bfb5a4b1844fd55f6cf0ab5ff6f378b359aa8acf5b32d693847e'
WINDOWS = {'6140': [(35, 42), (77, 81)], '3205': [(721, 728), (763, 767)]}


def as_json(obj):
    return json.dumps(obj, sort_keys=True, indent=2) + '\n'


def forecast(counter_ids, source_packets, archive):
    candidates = []
    totals = Counter()
    by_position = {position: Counter() for position in range(1, 5)}
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / 'packets.npz'
        dual.packet_snapshot(source_packets, path)
        for counter in sorted(counter_ids):
            group = project_group(path, counter, packets=True)
            evidence = bit_evidence(group | field_sections(group['slots']))
            for slot in evidence['slots']:
                index, phase = slot['slot'], slot['phase']
                tick = 3 * counter + phase
                received = [ordinal for ordinal in range(4) if (tick, ordinal) in source_packets]
                offsets = dual.wire_offsets(index)
                for event in slot['events']:
                    if event['kind'] != 'direct_check':
                        continue
                    totals['applicable_direct_events'] += 1
                    by_position[slot['position']]['applicable_direct_events'] += 1
                    first, stop = event['word_bits']
                    target_packets = {offsets[bit // 8] // 179 for bit in range(first, stop)}
                    if target_packets.intersection(received):
                        totals['target_available_on_6140'] += 1
                        continue
                    dual.require(event['observed'] is None, 'expected an unavailable target')
                    dual.require(first // 8 == (stop - 1) // 8, 'target crosses an octet boundary')
                    for condition in event['inputs']:
                        if condition['slot'] == index:
                            begin, end = condition['word_bits']
                            dual.require(end <= first or stop <= begin, 'input overlaps held-out target')
                    candidates.append(dict(
                        counter=counter, slot=index, phase=phase, cycle=slot['cycle'], position=slot['position'],
                        field=event['check'], target_bits=[first, stop], target_du_offset=offsets[first // 8],
                        allowed=event['allowed_values'], fixed=event['fixed_bits'], inputs=event['inputs'],
                        source_receipt_ordinals=received,
                        source_native_rows=sorted({source_packets[tick, ordinal][1] for ordinal in received}),
                    ))
    candidates.sort(key=lambda row: (row['counter'], row['slot'], row['target_bits'][0], row['field']))
    primary = next((index for index, row in enumerate(candidates) if row['fixed']), None)
    frozen = dict(
        protocol_sha256=dual.digest(HERE / 'protocol.md'), member_data_read=False,
        known_cohort=len(counter_ids), source_sha256=dual.digest(archive),
        primary_case_index=primary, eligible=totals, cases=candidates,
    )
    dual.require(sha256(as_json(frozen).encode()).hexdigest() == FREEZE, '6140-only prediction digest differs')
    return candidates, primary, totals, by_position


def raw_excerpt(side, original, expected_digest):
    ranges = WINDOWS[side]
    indexes = [index for first, stop in ranges for index in range(first, stop)]
    raw = (HERE / (side + '.msc.bin')).read_bytes()
    if original:
        original_bytes = original.read_bytes()
        dual.require(sha256(original_bytes).hexdigest() == expected_digest, 'wrong original native source')
        extracted = b''.join(original_bytes[first*732:stop*732] for first, stop in ranges)
        dual.require(extracted == raw, 'excerpt differs from original')
    rows = {}
    for index, (length, payload) in zip(indexes, struct.iter_unpack('<I728s', raw), strict=True):
        dual.require(length == 728, 'bad native record length')
        rows[index] = [payload[offset:offset+182] for offset in range(0, 728, 182)]
    return rows


def crc_pair(wire):
    return [f'{int.from_bytes(wire[-2:], "big"):04X}', f'{crc(wire[:-2]):04X}']


def check_native(rows, target_index, counter, phase):
    """Verify the target's phase and counter in the original receiver chronology."""
    first_index = target_index - phase
    # Nonzero phases must lie between two successive phase-zero counters.
    needed = [first_index] if phase == 0 else range(first_index, first_index + 4)
    for index in needed:
        expected_phase = (index - first_index) % 3
        phase_packet = rows[index][0]
        sent_crc, computed_crc = crc_pair(phase_packet)
        dual.require(phase_packet[0] == PACKET_HEADERS[0], 'bad phase packet header')
        dual.require(sent_crc == computed_crc, 'bad phase packet CRC')
        dual.require(phase_packet[2] >> 4 == expected_phase, 'bad phase in native chronology')
        if expected_phase == 0:
            counter_packet = rows[index][3]
            sent_crc, computed_crc = crc_pair(counter_packet)
            dual.require(counter_packet[0] == PACKET_HEADERS[3], 'bad counter packet header')
            dual.require(sent_crc == computed_crc, 'bad counter packet CRC')
            observed_counter = int.from_bytes(counter_packet[128:132], 'big')
            expected_counter = counter if index == first_index else counter + 1
            dual.require(observed_counter == expected_counter, 'bad counter in native anchor')
    return rows[target_index]


def checked_member_du_crc(packets):
    """Check all four original packets and then the independent checksum in their joined bodies."""
    for ordinal, packet in enumerate(packets):
        sent_crc, computed_crc = crc_pair(packet)
        dual.require(packet[0] == PACKET_HEADERS[ordinal], 'member packet header differs')
        dual.require(sent_crc == computed_crc, 'member packet CRC failed')
    unit = b''.join(packet[1:-2] for packet in packets)
    computed_crc = crc(unit[:-2])
    dual.require(computed_crc == int.from_bytes(unit[-2:], 'big'), 'member data-unit CRC failed')
    return f'{computed_crc:04X}'


def score_slot(events, source_packets, member_packets, source_rows, member_rows):
    """Read the missing 6140 target once and score every forecast for this slot against 3205."""
    case = events[0]
    counter, phase, slot = case['counter'], case['phase'], case['slot']
    tick = 3 * counter + phase
    target_offset = case['target_du_offset']
    ordinal, body_offset = divmod(target_offset, 179)
    coordinate = (tick, ordinal)
    dual.require(coordinate not in source_packets, 'target packet already accepted on 6140')
    dual.require(coordinate in member_packets, 'target packet missing on 3205')

    source_index, = case['source_native_rows']
    member_body, member_index = member_packets[coordinate]
    source_row = check_native(source_rows, source_index, counter, phase)
    member_row = check_native(member_rows, member_index, counter, phase)
    member_du_crc = checked_member_du_crc(member_row)

    mode_offset = dual.wire_offsets(slot)[0]
    dual.require(mode_offset < 179, 'expected a position-one mode in packet zero')
    accepted_mode_body = source_packets[tick, 0][0]
    dual.require(source_row[0][1:-2] == accepted_mode_body, '6140 mode packet differs from receipt')
    dual.require(member_row[0][1:-2] == accepted_mode_body, '3205 mode packet differs from 6140')

    rejected_packet = source_row[ordinal]
    accepted_packet = member_row[ordinal]
    rejected_crc = crc_pair(rejected_packet)
    accepted_crc = crc_pair(accepted_packet)
    dual.require(rejected_crc[0] != rejected_crc[1], 'expected a rejected 6140 target packet')
    dual.require(accepted_packet[1:-2] == member_body, '3205 native target differs from receipt')

    # A one-byte packet header precedes the 179-byte body.
    wire_offset = 1 + body_offset
    rejected_octet = rejected_packet[wire_offset]
    accepted_octet = accepted_packet[wire_offset]
    domains = {}
    field_matches = 0
    fixed_scores = {}
    for event in events:
        dual.require(event['target_du_offset'] == target_offset, 'expected both nibbles of one target octet')
        first_bit, stop_bit = event['target_bits']
        shift = 7 - (stop_bit - 1) % 8
        field_mask = (1 << (stop_bit - first_bit)) - 1
        observed_field = (accepted_octet >> shift) & field_mask
        allowed = event['allowed']
        domains[event['field']] = [min(allowed), max(allowed)]
        field_matches += observed_field in allowed

        for bit, predicted in event['fixed'].items():
            bit = int(bit)
            shift = 7 - bit % 8
            reference_bit = (accepted_octet >> shift) & 1
            rejected_bit = (rejected_octet >> shift) & 1
            fixed_scores[bit] = (predicted, reference_bit, rejected_bit)

    receipt = dict(
        counter=counter, phase=phase, cycle=case['cycle'], slot=slot, position=case['position'],
        mode=f'{accepted_mode_body[mode_offset]:02X}', mode_du_offset=mode_offset,
        mode_q0_transmitted_crc=crc_pair(source_row[0])[0],
        source_6140_row=source_index, source_6140_accepted_ordinals=case['source_receipt_ordinals'],
        member_3205_row=member_index, member_du_crc=member_du_crc,
        target_q=ordinal, target_du_offset=target_offset, domains=domains,
        source_rejected_octet=f'{rejected_octet:02X}', member_accepted_octet=f'{accepted_octet:02X}',
        source_rejected_packet_header=f'{rejected_packet[0]:02X}',
        member_accepted_packet_header=f'{accepted_packet[0]:02X}',
        source_target_crc_transmitted_computed=rejected_crc,
        member_target_crc_transmitted_computed=accepted_crc,
    )
    if rejected_octet != accepted_octet and fixed_scores:
        # Change only the target octet in a copy of the good packet, preserving its transmitted CRC.
        mutation = bytearray(accepted_packet)
        mutation[wire_offset] = rejected_octet
        substitution_crc = crc_pair(mutation)
        dual.require(substitution_crc[0] != substitution_crc[1], 'corrupt target packet unexpectedly accepted')
        receipt['target_substitution_control_crc_transmitted_computed'] = substitution_crc
    return receipt, field_matches, fixed_scores.values()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--member-msc', type=Path, help='optional original 3205 member window 0 native dump')
    parser.add_argument('--edogawa-msc', type=Path, help='optional original 6140 Edogawa native dump')
    parser.add_argument('--out', type=Path, help='write the result here, default stdout')
    args = parser.parse_args()
    member_case = HERE.parents[1] / 'member-3205-20min'
    prior = json.loads((member_case / 'cross-frequency.json').read_text())
    sources = prior['sources']
    counter_ids = set(prior['historical_exposure']['member_historical_counter_ids'])
    source_msc_hash = sources['raw_msc_sha256']['edogawa_6140']
    member_msc_hash = sources['raw_msc_sha256']['member_3205_mlc1_window0']

    source_archive = HERE.parent / 'dual-6140.npz'
    source_dus = HERE.parents[3] / sources['edogawa_6140_du_archive']
    source_packets, _ = dual.packets(source_archive, source_dus, counter_ids, None, source_msc_hash)
    candidates, primary, totals, by_position = forecast(counter_ids, source_packets, source_archive)

    # The accepted member reference and the rejected Edogawa packets first enter after the forecast digest check.
    member_archive = HERE.parent / 'dual-3205.npz'
    member_dus = member_case / 'member-dus.npz'
    member_packets, _ = dual.packets(member_archive, member_dus, counter_ids, None, member_msc_hash)
    source_rows = raw_excerpt('6140', args.edogawa_msc, source_msc_hash)
    member_rows = raw_excerpt('3205', args.member_msc, member_msc_hash)
    events_by_slot = defaultdict(list)
    for event in candidates:
        events_by_slot[event['counter'], event['slot']].append(event)

    receipts = []
    for events in events_by_slot.values():
        receipt, field_matches, fixed_bits = score_slot(events, source_packets, member_packets, source_rows, member_rows)
        receipts.append(receipt)
        totals['scored_fields'] += len(events)
        totals['field_matches'] += field_matches
        for predicted, reference_bit, rejected_bit in fixed_bits:
            totals['fixed_bits'] += 1
            totals['fixed_bits_matching'] += predicted == reference_bit
            totals['fixed_bits_differing_in_failed_source'] += predicted != rejected_bit
    totals.update(
        shared_counters=len(counter_ids), slots_before_selection=60 * len(counter_ids),
        source_missing_events=len(candidates), distinct_target_slots=len(receipts),
        distinct_counters=len({row['counter'] for row in receipts}), lower_nibble_alternates_excluded=5,
    )
    for position, counts in by_position.items():
        counts.update(
            slots=15 * len(counter_ids),
            selected_events=sum(event['position'] == position for event in candidates),
            selected_slots=sum(row['position'] == position for row in receipts),
        )
    first = candidates[primary]
    result = dict(
        totals=totals, by_position=by_position, slots=receipts,
        primary={name: first[name] for name in ('counter', 'slot', 'position', 'field')},
        source_only_prediction_sha256=FREEZE, protocol_sha256=dual.digest(HERE / 'protocol.md'),
        native_ranges_half_open=WINDOWS,
        inputs_sha256=dict(
            iq_6140=sources['edogawa_6140_flac_sha256'], iq_3205=sources['member_iq_sha256'],
            native_6140=source_msc_hash, native_3205=member_msc_hash,
            accepted_6140=dual.digest(source_archive), accepted_3205=dual.digest(member_archive),
            excerpt_6140=dual.digest(HERE / '6140.msc.bin'), excerpt_3205=dual.digest(HERE / '3205.msc.bin'),
        ),
    )
    if args.out:
        args.out.write_text(as_json(result))
    else:
        print(as_json(result), end='')


if __name__ == '__main__':
    main()
