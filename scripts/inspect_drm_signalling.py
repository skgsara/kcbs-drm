"""Inspect public FAC and SDC blocks from a DRM30 receiver's signalling.bits file.

Field definitions follow ETSI ES 201 980 V4.3.1 sections 6.3 and 6.4.
Counts refer to receiver callbacks in one file, including repeat transmissions.
"""
import argparse
from binascii import crc_hqx
from bisect import bisect_left
from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path


def fac_crc(body):
    state = 0xff
    for octet in body:
        state ^= octet
        for _ in range(8):
            state = ((state << 1) ^ (0x1d if state & 0x80 else 0)) & 0xff
    return state ^ 0xff


def fac_service(bits):
    return dict(service_id=f"{int(bits[20:44], 2):06X}", short_id=int(bits[44:46], 2),
                audio_ca=int(bits[46]), language_code=int(bits[47:51], 2),
                service="data" if bits[51] == "1" else "audio",
                service_descriptor=int(bits[52:57], 2), data_ca=int(bits[57]))


def sdc_entities(data):
    """Read entire byte-aligned entity envelopes before accepting the block."""
    offset = 0
    entities = []
    while offset < len(data):
        if data[offset] == 0 and not any(data[offset:]):
            break
        end = offset + 2 + (data[offset] >> 1)
        if end > len(data):
            raise ValueError("SDC entity extends past data field")
        entities.append(data[offset:end])
        offset = end
    return entities


def describe_entity(entity):
    kind = entity[1] >> 4
    initial = entity[1] & 15
    payload = entity[2:]
    length = len(payload)
    if kind == 0:
        if length not in (3, 6, 9, 12):
            raise ValueError("invalid multiplex description length")
        streams = []
        for i in range(0, length, 3):
            pair = int.from_bytes(payload[i:i + 3], "big")
            streams.append(dict(stream_id=i // 3, part_a_bytes=pair >> 12, part_b_bytes=pair & 0xfff))
        return dict(protection_level_a=initial >> 2, protection_level_b=initial & 3, streams=streams)
    if kind == 1:
        if not 1 <= length <= 64 or initial & 3:
            raise ValueError("unsupported label length or reserved bits")
        return dict(short_id=initial >> 2, label=payload.decode("utf-8"))
    if kind == 2:
        return dict(short_id=initial >> 2, audio_ca_scope=(initial >> 1) & 1, data_ca_scope=initial & 1)
    if kind == 5:
        if not payload:
            raise ValueError("application descriptor missing")
        descriptor = payload[0]
        packet = bool(descriptor & 0x80)
        domain = descriptor & 7
        fields = dict(short_id=initial >> 2, stream_id=initial & 3, packet_mode=packet,
                      enhancement_flag=(descriptor >> 3) & 1, application_domain=domain)
        if packet:
            if length < 2:
                raise ValueError("packet data length missing")
            fields.update(data_unit_indicator=(descriptor >> 6) & 1, packet_id=(descriptor >> 4) & 3,
                          packet_data_bytes=payload[1])
            if domain == 1:
                if length < 4:
                    raise ValueError("DAB user application type missing")
                fields["dab_user_application_type"] = int.from_bytes(payload[2:4], "big") & 0x7ff
        return fields
    if kind == 8:
        if length not in (3, 4):
            raise ValueError("invalid time entity length")
        encoded = (initial << 24) | int.from_bytes(payload[:3], "big")
        mjd, hour, minute = encoded >> 11, (encoded >> 6) & 31, encoded & 63
        if hour > 23 or minute > 59:
            raise ValueError("invalid time of day")
        day = date(1858, 11, 17) + timedelta(days=mjd)
        offset = None
        if length == 4:
            if payload[3] & 0xc0:
                raise ValueError("reserved bits in time offset")
            magnitude = (payload[3] & 31) * 30
            offset = -magnitude if payload[3] & 32 else magnitude
        return dict(mjd=mjd, signalled_utc_minute=f"{day.isoformat()}T{hour:02d}:{minute:02d}Z",
                    local_offset_minutes=offset)
    if kind == 9:
        if length < 2:
            raise ValueError("audio parameters missing")
        return dict(short_id=initial >> 2, stream_id=initial & 3, audio_coding=payload[0] >> 6)
    if kind == 12:
        if length != 5 or initial & 3:
            raise ValueError("unsupported language and country length or reserved bits")
        return dict(short_id=initial >> 2, language=payload[:3].decode("latin-1"),
                    country=payload[3:].decode("latin-1"))
    return {}


def service_counts(code):
    """Decode the FAC number-of-services field (ETSI ES 201 980 V4.3.1, §6.3.3)."""
    if code in (0xb, 0xe):
        return None
    if code == 0:
        return 4, 0
    if code == 0xf:
        return 0, 4
    return divmod(code, 4)


def component_version(envelopes, version):
    allocations, descriptors = [], []
    for raw in envelopes:
        if raw[0] & 1 != version:
            continue
        kind = raw[1] >> 4
        item = dict(type=kind, raw_hex=raw.hex())
        try:
            item.update(describe_entity(raw))
        except ValueError as error:
            item["field_error"] = str(error)
        if kind == 0:
            allocations.append(item)
        else:
            descriptors.append(item)

    # A repeated identical allocation supplies the same evidence. Two distinct
    # type-0 envelopes cannot both describe a single unambiguous multiplex.
    distinct_allocations = {item["raw_hex"] for item in allocations}
    for descriptor in descriptors:
        if "field_error" in descriptor:
            status = "malformed_descriptor"
        elif not allocations:
            status = "missing_allocation"
        elif len(distinct_allocations) > 1:
            status = "ambiguous_allocation"
        elif "field_error" in allocations[0]:
            status = "malformed_allocation"
        else:
            stream = next((s for s in allocations[0]["streams"] if s["stream_id"] == descriptor["stream_id"]), None)
            if stream is None:
                status = "stream_absent"
            else:
                status = "stream_allocated" if stream["part_a_bytes"] or stream["part_b_bytes"] else "stream_zero_length"
                descriptor["stream"] = stream
                descriptor["allocation_raw_hex"] = allocations[0]["raw_hex"]
        descriptor["allocation_status"] = status
    return dict(version_flag=version, configuration="next" if version else "current",
                allocations=allocations, descriptors=descriptors,
                missing_types=sorted({0, 5, 9} - {item["type"] for item in allocations + descriptors}))


def component_report(fac_events, sdc_events):
    states, block_sets = {}, {}
    service_occurrences = Counter(event["service_id"] for event in fac_events)
    for event in fac_events:
        state = event["state"]
        key = tuple(state.items())
        if key not in states:
            code = state["number_of_services_code"]
            counts = service_counts(code)
            format_flags = []
            if state["rm_flag"]:
                format_flags.append("rm1_in_72_bit_fac")
            elif state["toggle"]:
                format_flags.append("nonzero_toggle_for_rm0")
            if state["rfu"]:
                format_flags.append("nonzero_rfu")
            fields = dict(audio=None, data=None, service_class_consistency="reserved_count_code")
            if counts is not None:
                audio, data = counts
                count = data if state["service"] == "data" else audio
                fields = dict(audio=audio, data=data, service_class_consistency="permitted" if count else "contradicted")
            states[key] = dict(**state, **fields, format_flags=format_flags, count=0, first=event["at"])
        states[key]["count"] += 1
        states[key]["last"] = event["at"]
    for event in sdc_events:
        if "framing_error" in event:
            continue
        envelopes = event["envelopes"]
        if envelopes not in block_sets:
            block_sets[envelopes] = dict(envelopes=[raw.hex() for raw in envelopes],
                                         configurations=[component_version(envelopes, v) for v in (0, 1)],
                                         count=0, first=event["at"])
        block_sets[envelopes]["count"] += 1
        block_sets[envelopes]["last"] = event["at"]

    def nearby_sdc(event):
        if "framing_error" in event:
            return dict(at=event["at"], framing_error=event["framing_error"])
        return dict(at=event["at"], envelopes=[raw.hex() for raw in event["envelopes"]])

    singletons = []
    sdc_lines = [event["at"]["line"] for event in sdc_events]
    for i, event in enumerate(fac_events):
        if service_occurrences[event["service_id"]] != 1:
            continue
        j = bisect_left(sdc_lines, event["at"]["line"])
        singletons.append(dict(fac=event, previous_fac=fac_events[i - 1] if i else None,
                               following_fac=fac_events[i + 1] if i + 1 < len(fac_events) else None,
                               previous_sdc=nearby_sdc(sdc_events[j - 1]) if j else None,
                               following_sdc=nearby_sdc(sdc_events[j]) if j < len(sdc_events) else None))
    return dict(position_units="One-based file line and zero-based channel callback ordinal, including CRC failures.",
                scope="Nearest CRC-valid callbacks give receiver file order. FAC class consistency uses the current "
                      "72-bit format. A set RFU bit calls the interpretation of the entire FAC into question "
                      "(ES 201 980 §6.3.3). "
                      "Stream links require a type-0 allocation "
                      "and a type-5 or type-9 descriptor in the same SDC block and configuration version.",
                fac_joint_states=list(states.values()), singleton_fac_services=singletons,
                sdc_crc_valid_blocks=len(sdc_events), sdc_parseable_blocks=sum(x["count"] for x in block_sets.values()),
                sdc_component_sets=list(block_sets.values()))


def inspect_file(path, *, components=False):
    path = Path(path)
    input_hash = sha256()
    totals = {ch: dict(observed=0, crc_passed=0, crc_failed=0) for ch in ("FAC", "SDC")}
    fac_words, entities, structural_errors = Counter(), Counter(), Counter()
    clock_occurrences = []
    fac_events, sdc_events = [], []
    with path.open("rb") as source:
        for line_no, line in enumerate(source, 1):
            input_hash.update(line)
            parts = line.split()
            if len(parts) != 2 or parts[0] not in (b"FAC", b"SDC") or parts[1].strip(b"01"):
                raise ValueError(f"{path}:{line_no}: expected FAC or SDC followed by binary digits")
            ch = parts[0].decode("ascii")
            bits = parts[1]
            if ((ch == "FAC" and len(bits) != 72)
                    or (ch == "SDC" and (len(bits) < 20 or len(bits) % 8 != 4))):
                raise ValueError(f"{path}:{line_no}: unexpected {ch} bit count {len(bits)}")
            word = int(bits, 2).to_bytes((len(bits) + 7) // 8, "big")
            stats = totals[ch]
            stats["observed"] += 1
            valid = (fac_crc(word[:-1]) == word[-1] if ch == "FAC" else
                     (crc_hqx(word[:-2], 0xffff) ^ 0xffff) == int.from_bytes(word[-2:], "big"))
            if not valid:
                stats["crc_failed"] += 1
                continue
            stats["crc_passed"] += 1
            if components:
                at = dict(line=line_no, channel_ordinal=stats["observed"] - 1)
            if ch == "FAC":
                fac_words[word] += 1
                if components:
                    fields = fac_service(bits.decode("ascii"))
                    fields.update(number_of_services_code=int(bits[11:15], 2), reconfiguration_index=int(bits[15:18], 2),
                                  rm_flag=int(bits[3:4]), toggle=int(bits[18:19]), rfu=int(bits[19:20]))
                    fac_events.append(dict(at=at, raw_hex=word.hex(), service_id=fields["service_id"], state=fields))
            else:
                try:
                    envelopes = sdc_entities(word[1:-2])
                except ValueError as error:
                    structural_errors[str(error)] += 1
                    if components:
                        sdc_events.append(dict(at=at, framing_error=str(error)))
                    continue
                if components:
                    selected = tuple(sorted(raw for raw in envelopes if raw[1] >> 4 in (0, 5, 9)))
                    sdc_events.append(dict(at=at, envelopes=selected))
                entities.update(envelopes)
                for entity in envelopes:
                    if entity[1] >> 4 == 8:
                        clock_occurrences.append(dict(sdc_block_index=stats["observed"] - 1, raw_hex=entity.hex()))
    entity_counts = Counter()
    descriptions = []
    for raw, count in sorted(entities.items()):
        kind = raw[1] >> 4
        entity_counts[kind] += count
        item = dict(type=kind, version_flag=raw[0] & 1, raw_hex=raw.hex(), count=count)
        try:
            item.update(describe_entity(raw))
        except ValueError as error:
            item["field_error"] = str(error)
        descriptions.append(item)
    services, channel_parameters, frame_ids = Counter(), Counter(), Counter()
    for word, count in sorted(fac_words.items()):
        bits = f"{int.from_bytes(word, 'big'):072b}"
        services[tuple(fac_service(bits).items())] += count
        fields = dict(base_enhancement=int(bits[0]), rm_flag=int(bits[3]), spectrum_occupancy=int(bits[4:7], 2),
                      interleaver_depth_flag=int(bits[7]), msc_mode=int(bits[8:10], 2), sdc_mode=int(bits[10]),
                      number_of_services_code=int(bits[11:15], 2))
        channel_parameters[tuple(fields.items())] += count
        frame_ids[int(bits[1:3], 2)] += count
    result = dict(source_sha256=input_hash.hexdigest(), blocks=totals,
                fac_services=[dict(fields, count=n) for fields, n in services.items()],
                fac_channel_parameters=[dict(fields, count=n) for fields, n in channel_parameters.items()],
                fac_identities=dict(sorted(frame_ids.items())),
                sdc_crc_passed_with_framing_error=dict(structural_errors),
                sdc_entity_counts=dict(sorted(entity_counts.items())), sdc_entities=descriptions,
                time_entity_occurrences=clock_occurrences)
    if components:
        result["components"] = component_report(fac_events, sdc_events)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bits", type=Path, help="one receiver pass's signalling.bits")
    parser.add_argument("--components", action="store_true",
                        help="report joint FAC states, isolated service IDs and same-block stream allocations")
    args = parser.parse_args()
    try:
        result = inspect_file(args.bits, components=args.components)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
