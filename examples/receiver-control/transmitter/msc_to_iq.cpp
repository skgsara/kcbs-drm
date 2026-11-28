// Offline MSC-to-IQ known-answer control using the Dream transmitter modules.
// Compiled against Dream under the GNU General Public License, version 2 or later.
#include "src/DrmTransmitter.h"
#include <sndfile.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fcntl.h>
#include <fstream>
#include <unistd.h>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

constexpr int stream_bytes = 728;
constexpr int preview_frames = 30;
constexpr int drain_frames = 24;
constexpr int sample_rate = 48000;
using Frame = std::array<unsigned char, stream_bytes>;

// Guard counters live in two reserved ranges outside the scored test groups.
static void append_crc(unsigned char* bytes, size_t n) {
    uint16_t crc = 0xffff;
    for (size_t i = 0; i < n; ++i) {
        crc ^= static_cast<uint16_t>(bytes[i]) << 8;
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021) : static_cast<uint16_t>(crc << 1);
    }
    crc ^= 0xffff;
    bytes[n] = crc >> 8;
    bytes[n+1] = crc & 255;
}

static Frame guard(size_t frame, uint32_t base) {
    std::array<unsigned char, 716> du{};
    const unsigned phase = frame % 3;
    const uint32_t counter = base + frame / 3;
    du[1] = static_cast<unsigned char>(phase << 4);
    for (int j = 0; j < 4; ++j) {
        const unsigned char stamp = (counter >> (24 - 8*j)) & 255;
        if (!phase) du[664+j] = stamp;
        du[668+j] = stamp;
    }
    append_crc(du.data(),714);
    Frame frame_bytes{};
    const unsigned char headers[4] = {0x80, 0x01, 0x02, 0x43};
    for (int q=0; q<4; ++q) {
        auto* packet = frame_bytes.data() + q*182;
        packet[0] = headers[q];
        std::copy_n(du.data() + q*179, 179, packet+1);
        append_crc(packet,180);
    }
    return frame_bytes;
}

class OfflineModulator : public CDRMTransmitter {
public:
    void configure() {
        Parameters.ResetServicesStreams();
        Parameters.iFrameIDTransm = 0;
        Parameters.eTransmitCurrentTime = CParameter::CT_OFF;
        Parameters.InitCellMapTable(RM_ROBUSTNESS_MODE_B, SO_3);
        Parameters.SetServiceID(0, 0xef0201);
        Parameters.SetNumOfServices(0, 1);
        Parameters.SetCurSelDataService(0);
        Parameters.SetAudDataFlag(0, CService::SF_DATA);
        Parameters.Service[0].strLabel = "DRM IQ TEST";
        Parameters.Service[0].iLanguage = 5;
        Parameters.Service[0].iServiceDescr = 0;
        CDataParam data;
        data.iStreamID = 0;
        data.iPacketLen = 179;
        data.iPacketID = 0;
        data.ePacketModInd = CDataParam::PM_PACKET_MODE;
        data.eDataUnitInd = CDataParam::DU_DATA_UNITS;
        data.eAppDomain = CDataParam::AD_DAB_SPEC_APP;
        data.iUserAppIdent = 0;
        Parameters.SetDataParam(0, data);
        Parameters.SetStreamLen(0, 0, stream_bytes);
        Parameters.eSymbolInterlMode = CParameter::SI_LONG;
        Parameters.eMSCCodingScheme = CS_3_SM;
        Parameters.eSDCCodingScheme = CS_2_SM;
        Parameters.MSCPrLe.iPartA = 0;
        Parameters.MSCPrLe.iPartB = 1;
        SetCarOffset(0);
        Parameters.FetchNewSampleRate();
        Parameters.InitCellMapTable(RM_ROBUSTNESS_MODE_B, SO_3);
        OFDMCellMapping.Init(Parameters, CarMapBuf);
        SDCMLCEncoder.Init(Parameters, SDCMapBuf);
        MSCMLCEncoder.Init(Parameters, MLCEncBuf);
        SymbInterleaver.Init(Parameters, IntlBuf);
        GenerateFACData.Init(Parameters, GenFACDataBuf);
        FACMLCEncoder.Init(Parameters, FACMapBuf);
        GenerateSDCData.Init(Parameters, GenSDCDataBuf);
        OFDMModulation.Init(Parameters, OFDMModBuf);
        if (Parameters.GetSigSampleRate() != sample_rate || Parameters.iNumDecodedBitsMSC < stream_bytes*8)
            throw std::runtime_error("unexpected signal rate or insufficient MSC capacity");
        AudSrcBuf.Init(Parameters.iNumDecodedBitsMSC);
    }

    void render(const std::vector<Frame>& frames, SNDFILE* output) {
        const int per_frame = Parameters.CellMappingTable.iNumSymPerFrame;
        const std::size_t total_frames = preview_frames + frames.size() + drain_frames;
        std::vector<short> stereo(2 * Parameters.CellMappingTable.iSymbolBlockSize);
        std::size_t consumed = 0, symbols = 0;
        unsigned idle = 0;
        double peak = 0;
        while (symbols < total_frames * per_frame) {
            if (AudSrcBuf.GetRequestFlag()) {
                auto* bits = AudSrcBuf.QueryWriteBuffer();
                bits->Reset(0);
                Frame frame;
                if (consumed < preview_frames)
                    frame = guard(consumed, 0x0f800000);
                else if (consumed < preview_frames + frames.size())
                    frame = frames[consumed-preview_frames];
                else
                    frame = guard(consumed-preview_frames-frames.size(), 0x0f810000);
                bits->ResetBitAccess();
                for (auto octet : frame) bits->Enqueue(octet, 8);
                AudSrcBuf.Put(Parameters.iNumDecodedBitsMSC);
                AudSrcBuf.SetRequestFlag(false);
                ++consumed;
            }
            MSCMLCEncoder.ProcessData(Parameters, AudSrcBuf, MLCEncBuf);
            SymbInterleaver.ProcessData(Parameters, MLCEncBuf, IntlBuf);
            GenerateFACData.ReadData(Parameters, GenFACDataBuf);
            FACMLCEncoder.ProcessData(Parameters, GenFACDataBuf, FACMapBuf);
            GenerateSDCData.ReadData(Parameters, GenSDCDataBuf);
            SDCMLCEncoder.ProcessData(Parameters, GenSDCDataBuf, SDCMapBuf);
            OFDMCellMapping.ProcessData(Parameters, IntlBuf, FACMapBuf, SDCMapBuf, CarMapBuf);
            OFDMModulation.ProcessData(Parameters, CarMapBuf, OFDMModBuf);

            const int n = OFDMModBuf.GetFillLevel();
            if (n) {
                if (2*n != static_cast<int>(stereo.size()))
                    throw std::runtime_error("invalid OFDM symbol size");
                const auto* wave = OFDMModBuf.Get(n);
                for (int i=0; i<n; ++i) {
                    const auto value = (*wave)[i];
                    const double ri[2] = {value.real(), value.imag()};
                    for (int k=0; k<2; ++k) {
                        const double sample = 350 * ri[k];
                        peak = std::max(peak, std::abs(sample));
                        if (!std::isfinite(sample) || std::abs(sample) > 32767)
                            throw std::runtime_error("IQ PCM exceeds the fixed conversion range");
                        stereo[2*i+k] = static_cast<short>(std::lround(sample));
                    }
                }
                if (sf_writef_short(output, stereo.data(), n) != n)
                    throw std::runtime_error("IQ write failed");
                ++symbols;
                idle = 0;
            } else if (++idle > 1000)
                throw std::runtime_error("Dream TX module chain stalled");
            OFDMModBuf.SetRequestFlag(true);
        }
        if (consumed < frames.size()+preview_frames)
            throw std::runtime_error("some scored input frames did not reach MLC");
        std::cout << "input_rows=" << frames.size() << " msc_capacity_bits=" << Parameters.iNumDecodedBitsMSC
                  << " pre_guard=" << preview_frames << " tail_guard=" << drain_frames
                  << " emitted_frames=" << total_frames << " symbols=" << symbols
                  << " pcm_peak=" << peak << " service_id=0xEF0201 service_label=DRM_IQ_TEST\n";
    }
};

int main(int argc, char** argv) {
    if (argc != 3) { std::cerr << "usage: msc_to_iq INPUT-728-BYTE-ROWS OUTPUT.wav\n"; return 2; }
    try {
        if (!std::filesystem::is_regular_file(argv[1]))
            throw std::runtime_error("input must be a regular file");
        std::ifstream in(argv[1], std::ios::binary | std::ios::ate);
        const auto bytes = in.tellg();
        if (!in || bytes <= 0 || bytes % stream_bytes)
            throw std::runtime_error("expected a positive whole number of 728-byte frames");
        std::vector<Frame> frames(static_cast<std::size_t>(bytes) / stream_bytes);
        in.seekg(0);
        if (!in.read(reinterpret_cast<char*>(frames.data()), bytes))
            throw std::runtime_error("MSC read failed");
        // Use the DSP blocks directly. No Dream audio device or socket is opened.
        OfflineModulator tx;
        tx.configure();
        SF_INFO format{};
        format.channels = 2; format.samplerate = sample_rate; format.format = SF_FORMAT_WAV | SF_FORMAT_PCM_16;
        const int fd = open(argv[2], O_CREAT | O_EXCL | O_WRONLY, 0644);
        if (fd < 0) throw std::runtime_error("provide a new output WAV path");
        std::unique_ptr<SNDFILE, decltype(&sf_close)> file(sf_open_fd(fd, SFM_WRITE, &format, SF_TRUE), &sf_close);
        if (!file) {
            close(fd);
            throw std::runtime_error("cannot create IQ WAV");
        }
        tx.render(frames, file.get());
        if (sf_close(file.release())) throw std::runtime_error("closing IQ WAV failed");
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
