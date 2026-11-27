# KCBS receiver integration roadmap

1. **KiwiSDR, starting next session.** Fork KiwiSDR, check out the fork locally, and add KCBS decoding to its DRM receiver. Test with recorded KCBS IQ and submit a pull request to the upstream project. [KiwiSDR upstream](https://github.com/jks-prv/KiwiSDR)
2. **Dream, after KiwiSDR.** Fork the Dream DRM receiver from SourceForge. Once the project owner creates the GitHub repository, bring the fork there and add KCBS decoding. [Dream upstream](https://sourceforge.net/projects/drm/)
3. **DecDRM.** Add KCBS decoding to DecDRM, verify it against the recorded samples, and submit a pull request to its upstream project. [DecDRM upstream](https://github.com/CasualArclamp/DecDRM)

For each receiver, report the service ID, text checksum results, and number of received EVS frames supplied to the audio decoder. The existing November examples provide reference packets, frame counts, and audio for comparison. [Reference decodes](november-2026.md)
