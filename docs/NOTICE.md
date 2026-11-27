# Third-party notices

## Dream DRM receiver and MMJEE’s build fork

Dream was originally written by Volker Fischer and Alexander Kurpiers. Its upstream notices credit Technische Universität Darmstadt, Fraunhofer IIS, the British Broadcasting Corporation and the individual contributors identified in Dream’s source headers and `AUTHORS`. The Dream source files used here license their code under the GNU General Public License, version 2 or, at the recipient’s option, any later version. [Dream DRM receiver](https://sourceforge.net/projects/drm/) · [Upstream notices and author list in the build fork](https://github.com/mmjee/dream-patched/tree/895658c567d2fd47d6006065e75abf0c3157783f)

The build fetches the `mmjee/dream-patched` fork maintained by MMJEE and applies this project’s MSC dump, station-information and offline input changes to it. The checkout also carries modified Dream source files from the earlier receiver investigation under `patches/dream/`. Preserve the copyright, license and warranty notices in those files and in any redistributed source or binaries, and meet the applicable GPL source-distribution requirements. The downloaded Dream tree includes its own `COPYING` file. [Build instructions](../build/README.md) · [Included Dream source files](../patches/dream/) · [Dream’s license text](https://github.com/mmjee/dream-patched/blob/895658c567d2fd47d6006065e75abf0c3157783f/COPYING)

## FAAD2 AAC decoder

The FAAD2 2.8.8 files used in the earlier DRM AAC investigation credit M. Bakker and Nero AG, copyright 2003–2005. Their headers grant the GNU General Public License, version 2 or, at the recipient’s option, any later version. They specify the following attribution for the appropriate copyright message in section 2(c) of GPLv2.

> Code from FAAD2 is copyright (c) Nero AG, www.nero.com

The project retains the pristine `syntax.c.pristine`, the applied `syntax.c.diff`, and the modified `syntax.c`, `drm_dec.c`, `lt_predict.c` and `decoder.c`. The historical AAC investigation also used DLLs named `faad2_drm.dll` and `faad2_stock.dll`. The distributed files here are the source and patch files. When redistributing these files or binaries derived from FAAD2, retain the copyright notices and accompanying license text and meet the GPL’s applicable source obligations. The upstream notice provides contact details for separate commercial licensing. [Included FAAD2 files](../patches/faad2/) · [Supplied FAAD2 notice and GPLv2 license](COPYING.FAAD2) · [FAAD2 upstream](https://github.com/knik0/faad2)

## 3GPP Enhanced Voice Services reference codec

Audio reconstruction uses the floating-point EVS ANSI C reference implementation specified in **3GPP TS 26.443**, published by ETSI as **TS 126 443**. The reference code in the tested release identifies its 4 November 2021 version as 12.14.0 / 13.10.0 / 14.6.0 / 15.4.0 / 16.3.0. The 3GPP Organizational Partners and contributing rights holders retain their rights. The project supplies a GCC build script. Users obtain the reference source separately from the standards publication and retain its notices and applicable terms. [3GPP specification record](https://www.3gpp.org/dynareport/26443.htm) · [ETSI archive containing the reference code](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip) · [Build script](../scripts/build_evs_gcc_independent.py)
