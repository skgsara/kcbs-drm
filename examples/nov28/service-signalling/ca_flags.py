"""Count declared DRM30 FAC CA flags and SDC type-2 envelopes in receiver callbacks."""
import argparse
from binascii import crc_hqx
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from inspect_drm_signalling import fac_crc, fac_service, sdc_entities


PUBLIC = (
    "standard-service-audit/nov27-3205-360-420.bits",
    "standard-service-audit/1228-yokohama.bits",
    "standard-service-audit/1228-edogawa.bits",
    "standard-service-audit/1232-yokohama.bits",
    "standard-service-audit/1232-edogawa.bits",
    "yokohama-1300/results/primary/signalling.bits",
    "yokohama-1300/results/later/chunk-000.bits",
    "yokohama-1300/results/later/chunk-001.bits",
    "edogawa-audio-branch/signalling/edogawa.bits",
    "edogawa-audio-branch/signalling/yokohama.bits",
)

METRICS = (
    "fac_callbacks", "fac_crc_valid", "fac_crc_failed", "fac_unsupported_rm",
    "fac_both_zero", "fac_audio_set", "fac_data_set", "fac_both_set",
    "fac_nonstandard_toggle_or_rfu", "sdc_callbacks", "sdc_crc_valid", "sdc_crc_failed",
    "sdc_framing_errors", "sdc_parseable_with_type2", "sdc_parseable_without_type2", "sdc_type2_entities",
)


def report(path):
    data = path.read_bytes()
    counts = Counter(dict.fromkeys(METRICS, 0))
    services, scopes = Counter(), Counter()
    for line in data.decode("ascii").splitlines():
        channel, bits = line.split()
        if channel not in ("FAC", "SDC") or not bits or set(bits) - {"0", "1"}:
            raise ValueError(f"{path.name}: unsupported callback format")
        word = int(bits, 2).to_bytes((len(bits) + 7) // 8, "big")
        if channel == "FAC":
            if len(bits) != 72:
                raise ValueError(f"{path.name}: expected a 72-bit DRM30 FAC")
            counts["fac_callbacks"] += 1
            if fac_crc(word[:-1]) != word[-1]:
                counts["fac_crc_failed"] += 1
                continue
            counts["fac_crc_valid"] += 1
            if bits[3] != "0":
                counts["fac_unsupported_rm"] += 1
                continue
            fields = fac_service(bits)
            audio, data_ca = fields["audio_ca"], fields["data_ca"]
            services[(fields["service_id"], fields["short_id"], fields["service"], audio, data_ca)] += 1
            counts["fac_both_zero"] += audio == data_ca == 0
            counts["fac_audio_set"] += audio
            counts["fac_data_set"] += data_ca
            counts["fac_both_set"] += audio == data_ca == 1
            counts["fac_nonstandard_toggle_or_rfu"] += bits[18:20] != "00"
        else:
            if len(bits) < 20 or len(bits) % 8 != 4:
                raise ValueError(f"{path.name}: unexpected SDC callback length")
            counts["sdc_callbacks"] += 1
            if (crc_hqx(word[:-2], 0xffff) ^ 0xffff) != int.from_bytes(word[-2:], "big"):
                counts["sdc_crc_failed"] += 1
                continue
            counts["sdc_crc_valid"] += 1
            try:
                entities = sdc_entities(word[1:-2])
            except ValueError:
                counts["sdc_framing_errors"] += 1
                continue
            type2 = [entity for entity in entities if entity[1] >> 4 == 2]
            counts["sdc_parseable_with_type2" if type2 else "sdc_parseable_without_type2"] += 1
            counts["sdc_type2_entities"] += len(type2)
            for entity in type2:
                # The first body nibble contains service association and component
                # scopes. Any following system-specific bytes are skipped.
                initial = entity[1] & 15
                scopes[(entity[0] & 1, initial >> 2, initial >> 1 & 1, initial & 1)] += 1
    return dict(sha256=sha256(data).hexdigest(), counts=dict(counts),
                fac_states=[dict(id=sid, short_id=short_id, service=service, audio_ca=audio,
                                 data_ca=data_ca, count=n)
                            for (sid, short_id, service, audio, data_ca), n in sorted(services.items())],
                sdc_type2_scopes=[dict(version=v, short_id=sid, audio_scope=audio, data_scope=data_ca, count=n)
                                  for (v, sid, audio, data_ca), n in sorted(scopes.items())])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path,
                        help="FAC/SDC bit ledgers; default is the ten listed public broadcast windows")
    paths = parser.parse_args().files or [HERE.parent / name for name in PUBLIC]
    items = []
    totals = Counter()
    seen = set()
    for path in paths:
        r = report(path)
        if r["sha256"] in seen:
            raise ValueError(f"Repeated bit ledger: {path}")
        seen.add(r["sha256"])
        resolved = path.resolve()
        name = str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else path.name
        items.append(dict(file=name, **r))
        totals.update(r["counts"])
    result = dict(scope="Counts are receiver callback occurrences across the specified files. Repeated broadcasts "
                        "and simultaneous stations can represent the same transmitted block. FAC states use the "
                        "72-bit RM=0 format. SDC presence requires both a valid block CRC and complete envelope "
                        "framing. Other SDC blocks and unevaluated times have no type-2 decision.",
                  fac_bits_zero_based_msb_first=dict(audio_ca=46, data_ca=57),
                  standard="ETSI ES 201 980 V4.3.1, sections 6.3.4 and 6.4.3.3, Tables 23 and 24",
                  total=dict(totals), files=items)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
