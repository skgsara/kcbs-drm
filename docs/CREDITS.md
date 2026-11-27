# Credits and sources

## KCBS-2 receiver research

**KoryoFront** published the KCBS-2 decoder that this repository builds on. Its work identified the broadcast counter, the 1.2-second grouping and the selectively masked audio bytes. It also proposed reading each mode byte and its 32-byte payload as a 264-bit EVS frame. [KoryoFront/kcbs2-drm-decode](https://github.com/KoryoFront/kcbs2-drm-decode) · [Contemporaneous attribution](https://github.com/martynw/KCBSDRM/blob/0b3e75fcb642d17d79c72f8f628cb4424273c06c/FINDINGS_SUMMARY_2026-11-26.md#L17)

**Martyn (GitHub account `martynw`)** published the companion KCBSDRM study. He contributed the variable-length Korean text record parser, six November 25–26 capture datasets and the March EVS comparison against a time-aligned satellite recording. His contribution is preserved in `contrib/kcbsdrm`. [martynw/KCBSDRM](https://github.com/martynw/KCBSDRM) · [Merged contribution](https://github.com/KoryoFront/kcbs2-drm-decode/pull/1) · [Contributor’s notes](../contrib/kcbsdrm/README.md)

## Recordings

- Martyn bundled the three adjacent March 16, 2026, recordings from the HL5NTR KiwiSDR in Daegu on 3,205 kHz. [Capture commit](https://github.com/KoryoFront/kcbs2-drm-decode/commit/91cd9ec6704edb74050ccc52bf25c4ddcf82515c)
- The listening group shared the November 19 signed 8-bit I/Q recordings at 6,140 kHz. These include the two files labelled 17:00:52 and 17:09:40 and a member’s longer 17:31:39 recording. A group member also supplied the simultaneous November 27 I/Q WAVs from 6,140 and 3,205 kHz, receiver metadata and a CRC-checked MSC file. The November 27 capture began at 06:17:22 UTC.
- The November 19 KCBS-2 and Pyongyang FM recordings used for programme identification are preserved by the Internet Archive. Both archive entries credit 조선중앙방송위원회 (Korean Central Broadcasting Committee) and identify KoryoFront as the feed source. [KCBS-2 broadcast](https://archive.org/details/kcbs2.2026-11-19) · [Pyongyang FM broadcast](https://archive.org/details/pyongyang-fm.2026-11-19)
- The identified musical performances are by the Moranbong Band and the Wangjaesan Light Music Band. The Wangjaesan recording is track 1 of the band’s 1991 CD, catalogue WJS-C-101. [Longing Is My Happiness](https://archive.org/details/moranbong-band-longing-is-my-happiness) · [Mother’s Voice](https://archive.org/details/moranbong-band-mothers-voice) · [My Happy Country](https://archive.org/details/wangjaesangyongumaktan-che1chip)

## Software and standards

- Dream supplies the DRM receiver. The build uses the `mmjee/dream-patched` source tree. KiwiSDR recordings can be made with `kiwirecorder.py` from `jks-prv/kiwiclient`. [Dream project](https://sourceforge.net/projects/drm/) · [Build source](https://github.com/mmjee/dream-patched) · [kiwiclient](https://github.com/jks-prv/kiwiclient)
- ETSI ES 201 980 specifies the DRM system. The project uses the 3GPP floating-point EVS reference decoder distributed with TS 26.443. [ETSI DRM specification](https://www.etsi.org/deliver/etsi_es/201900_201999/201980/) · [3GPP EVS reference software](https://www.3gpp.org/ftp/Specs/archive/26_series/26.443/)
- The Dream and FAAD2 patches carry their original notices. The `contrib/kcbsdrm` package declares GPL-3.0 and includes a verbatim copy of the upstream licence. [Third-party notices](NOTICE.md) · [FAAD2 licence](COPYING.FAAD2) · [Contribution’s licensing statement](../contrib/kcbsdrm/README.md) · [Contributed package licence](../contrib/kcbsdrm/LICENSE)
