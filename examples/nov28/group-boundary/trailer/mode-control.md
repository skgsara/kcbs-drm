# Does the trailer change when the transmitted EVS mode stays the same?

Use the existing member 3205 kHz archive of complete data units. Validate each unit's CRC and coordinates and require all three phases at each counter. Compare only a counter and its immediate successor. Use the published EVS mode offsets for the 60 slots and the published 30-, 33- and 33-byte trailer slices.

Record trailer differences separately for three conditions: the last mode of one group equals the first mode of the next, all 60 mode octets agree position by position between the groups, and a single mode octet is constant across both groups. For every nonempty condition retain the first counter pair as a reproducible example. Also count distinct 60-octet mode sequences that occur at more than one counter and have more than one trailer value. A repeated mode sequence tests whether that sequence alone determines the complete trailer. It does not establish repeated audio content.

This is a retrospective test on an archive already used to establish trailer cadence. Its inputs are mode octets, physical trailers and received group coordinates. The selector does not use clear-frame labels or a playback score.
