// Compile against Dream's GPL-2.0-or-later MSC channel decoder. No radio device I/O.
#include "src/mlc/MLC.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

// File format is little-endian int32 and binary64. Each header is followed by
// n_cells triples (real, imaginary, channel magnitude). stdout is MSB-first bits.
using Header = std::array<int32_t, 15>;
using Cell = std::array<double, 3>;

class MSCDecoder : public CMSCMLCDecoder {
public:
    void decode(CParameter& parameters, CVectorEx<CEquSig>& cells, int output_bits, int iterations) {
        SetNumIterations(iterations);
        InitInternal(parameters);
        if (cells.Size() != iInputBlockSize || output_bits != iOutputBlockSize)
            throw std::runtime_error("incompatible native MLC block sizes");

        CVectorEx<_BINARY> bits;
        bits.Init(iOutputBlockSize, 0);
        pvecInputData = &cells;
        pvecOutputData = &bits;
        ProcessDataInternal(parameters);
        std::vector<uint8_t> packed((output_bits + 7) / 8, 0);
        for (int i = 0; i < output_bits; ++i)
            packed[i / 8] |= (bits[i] & 1) << (7 - i % 8);
        std::cout.write(reinterpret_cast<const char*>(packed.data()), packed.size());
        if (!std::cout) throw std::runtime_error("writing native decoder output failed");
    }
};

void read_block(const Header& header) {
    const int cells = header[0], bits = header[1], iterations = header[6];
    if (cells <= 0 || cells > 100000 || bits <= 0 || bits > 1000000 ||
        header[2] < 0 || header[2] > 3 || header[3] < 0 || header[3] > 5 ||
        header[4] < 0 || header[4] > 1 || header[5] < 0 || header[5] > 1 ||
        iterations < 0 || iterations > 10)
        throw std::runtime_error("unsupported MSC parameters");

    CParameter params;
    params.ResetServicesStreams();
    params.FetchNewSampleRate();
    params.InitCellMapTable(static_cast<ERobMode>(header[2]), static_cast<ESpecOcc>(header[3]));
    params.eMSCCodingScheme = CS_2_SM;
    params.MSCPrLe.iPartA = header[4];
    params.MSCPrLe.iPartB = header[5];
    for (int i = 0; i < 4; ++i) {
        // ETSI ES 201 980 SDC type 0 carries each length as an unsigned 12-bit field.
        if (header[7 + 2*i] < 0 || header[7 + 2*i] > 4095 ||
            header[8 + 2*i] < 0 || header[8 + 2*i] > 4095)
            throw std::runtime_error("invalid SDC part A/B length");
        params.SetStreamLen(i, header[7 + 2*i], header[8 + 2*i]);
    }

    std::vector<Cell> input(cells);
    if (!std::cin.read(reinterpret_cast<char*>(input.data()), cells * sizeof(Cell)))
        throw std::runtime_error("truncated cell vector");
    CVectorEx<CEquSig> symbols;
    symbols.Init(cells);
    for (int i = 0; i < cells; ++i) {
        symbols[i].cSig = _COMPLEX(input[i][0], input[i][1]);
        symbols[i].rChan = input[i][2];
    }
    MSCDecoder decoder;
    decoder.decode(params, symbols, bits, iterations);
}

int main() {
    static_assert(sizeof(int32_t) == 4 && sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
                  "the observer requires IEEE binary64");
    try {
        const uint32_t endian_probe = 1;
        if (*reinterpret_cast<const unsigned char*>(&endian_probe) != 1)
            throw std::runtime_error("the observer requires little-endian input on a little-endian host");
        Header header;
        while (std::cin.read(reinterpret_cast<char*>(header.data()), sizeof(header)))
            read_block(header);
        if (!std::cin.eof() || std::cin.gcount()) throw std::runtime_error("truncated block header");
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
