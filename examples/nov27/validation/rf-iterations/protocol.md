# Testing two MLC iteration settings on the same IQ

The signal at 22:27 UTC in Edogawa supplied complete data units. Increasing Dream's multi-level channel decoder setting from one to four raised the number of intact packet observations in development. On the first 90 seconds of the weak 22:41 reception, neither setting yielded a valid packet. The development gate for applying a replacement setting to the remaining 90 seconds failed. Leave those 90 seconds out of the iteration test.

Use the separate November 27 21:26 UTC simultaneous recordings at JL1EDU Yokohama (primary) and 7L4IOU Edogawa (peer). Their 180-second IQ WAV SHA-256 digests are `ec2e54504d26f9e1cc98abef11c52be7263ff2a1cf8457efe3ca38451c5007e3` and `d96c3f22638c45ef1ef966a022f03afb29032b0fbb70d9e116783b415d40c8d0`. An earlier project checked ordinary transport on this pair. It was held out of the new iteration-setting experiment.

Run Dream on the same samples with one and four iterations. Use the normal acquisition window, ordinary metrics, Wiener time/frequency interpolation and energy timing. For each station, run the existing CRC-checked transport receiver on each dump alone and both dumps together. Count distinct packet coordinates, complete data units and three-phase groups. Compare every overlapping byte and report gains and losses. Keep any conflicts. Check whether gains agree with the peer's independently received bytes.

For an EVS coverage example, take the lowest counter acquired as a complete group with both primary dumps which the primary one-iteration dump missed. If there is none, apply the same rule to the peer and identify its station. If neither station gained a group, report that outcome. Use only transport coordinates for this selection. Run the previously frozen HQ rule from revision `ef05302` on that group's mode bytes. A CRC-good packet establishes reception of transmitted bytes and supplies no absolute score of its masked audio bits.

The detailed RF experiment plan was recorded before the dual-station scoring, SHA-256 `2db0efd852948d9ec3bad26f0edab615655bd324f61af0fb2c98ff8240351ddd`.
