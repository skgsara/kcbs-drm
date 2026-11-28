/*
 * evs_candidate_decoder.c - persistent, exact EVS candidate decoder.
 *
 * Links against the UNMODIFIED 3GPP EVS float reference (TS 26.443, lib_com +
 * lib_dec from work/ref/evs/src/c-code; only lib_dec/decoder.c, which holds the
 * reference main(), is left out).  Build with scripts/build_evs_candidate_decoder.py.
 * Linux/POSIX only (fork, mmap, AF_UNIX SOCK_SEQPACKET, SCM_RIGHTS).
 *
 * PURPOSE
 *   Evaluate many alternative EVS frame sequences ("candidates") from one shared
 *   decoder state, bit-exactly equal to decoding each modified stream from scratch
 *   with 'EVS_dec -q -no_delay_cmp <rate_khz> in.192 out.raw'.  One exception:
 *   EVS_dec writes no samples at all for a stream without any good frame of at
 *   least 2.8 kbps (io_ini_dec()'s read_indices(rew_flag=1) probe reaches EOF and
 *   does not rewind), whereas this harness decodes such a stream as concealment.
 *
 * STATE SNAPSHOTS
 *   A decoder state is a PROCESS.  fork() copies the whole address space
 *   copy-on-write, so Decoder_State and everything hanging off it (CLDFB banks,
 *   FD-CNG handles, function-scope statics, the 'frame' global) are captured
 *   exactly without any deep-copy code.
 *
 *   router  (this main process: owns the protocol, never touches decoder memory)
 *     +-- base       state process holding the committed decoder state
 *     +-- checkpoint state processes, one per named CHECKPOINT (idle copies)
 *   EVAL in a state process:
 *     state --fork--> dispatcher (decodes the candidates' common prefix once)
 *                       --fork--> P workers, each pulling candidate indices from
 *                                 an atomic counter and forking one short-lived
 *                                 child per candidate; children write PCM and
 *                                 diagnostics into a MAP_SHARED|MAP_ANONYMOUS area.
 *   The state process itself never decodes during EVAL, so its state is untouched.
 *   CHECKPOINT/RESTORE clone a state process: the router creates a socketpair,
 *   passes one end to the source process with SCM_RIGHTS and that process
 *   double-forks; the clone is re-parented to the router (PR_SET_CHILD_SUBREAPER).
 *
 * PER-FRAME PROCESSING (mirrors lib_dec/decoder.c main(), G.192 branch)
 *   INIT replays io_ini_dec() (codec_mode=0, Opt_AMR_WB=0, Opt_VOIP=0,
 *   bitstreamformat=G192, amrwb_rfc4867_flag=-1, writeFECoffset=0, output_Fs,
 *   ini_frame=0, read_indices(st, f, rew_flag=1) on a probe frame), then
 *   init_decoder() and reset_indices_dec() exactly like main().  For every frame
 *   the frames are serialised to ITU-T G.192 in memory and read through fmemopen()
 *   by the reference read_indices(st, f, 0) itself (so the G.192 RX-DTX handler,
 *   decoder_selectCodec() and mdct_switching_dec() are the reference code), then:
 *       MODE1: Opt_AMR_WB ? amr_wb_dec() : evs_dec(FRAMEMODE_NORMAL)
 *       MODE2: evs_dec(bfi ? FRAMEMODE_MISSING : FRAMEMODE_NORMAL)
 *       syn_output(); if (ini_frame < MAX_FRAME_COUNTER) ini_frame++; frame++;
 *   PCM is returned per frame without delay compensation (= -no_delay_cmp).
 *   INIT reports dec_delay, the number of leading samples EVS_dec would drop
 *   (and zero-pad at the end) without -no_delay_cmp.
 *   Library printf() output is redirected to stderr; the protocol uses private
 *   duplicates of the original stdin/stdout.
 *
 * PROTOCOL (binary, little-endian, over the original stdin/stdout)
 *   request  : u32 cmd, u32 len, len payload bytes
 *   response : u32 status (0 = OK, 1 = error), u32 len, len payload bytes
 *              (an error payload is a UTF-8 message)
 *   frame record: u8 flag (0 = good: G.192 sync 0x6B21, 1 = bad: sync 0x6B20),
 *                 u8 reserved (0), u16 nbits, ceil(nbits/8) bytes of bits packed
 *                 MSB first.  nbits*50 must be an EVS/AMR-WB-IO G.192 rate
 *                 (0 = NO_DATA).  An erased frame is normally {1,0,0,0}.
 *   FEED and EVAL requests whose reply body would exceed 4 GiB - 1 (the u32 length
 *   field) are rejected with an error before anything is decoded.
 *   1 INIT       payload u32 output_fs (8000/16000/32000/48000),
 *                        u32 first_good_bits (0 = 264; length of the first good
 *                        frame of the stream, only used by the io_ini_dec probe)
 *                reply   u32 version, output_fs, output_frame, dec_delay,
 *                        diag_size, jobs, sizeof(Decoder_State)
 *                Discards the base state and every checkpoint.
 *   2 FEED       payload u32 n, n frame records.  Decodes and COMMITS.
 *                reply   u32 n, u32 output_frame, s16 pcm[n][output_frame],
 *                        diag[n]
 *   3 EVAL       payload u32 K, u32 N, u32 flags (bit0: omit PCM),
 *                        K*N frame records (candidate-major).
 *                Decodes every candidate from the CURRENT base state, which is
 *                left unchanged.
 *                reply   u32 K, u32 N, u32 L (output_frame, 0 if PCM omitted),
 *                        u32 prefix (frames shared by all candidates, decoded once),
 *                        u32 diag_size, s32 status[K] (0 = OK, 0x100|signal,
 *                        0x200|exit code, 0x300 not decoded; a candidate running
 *                        longer than --timeout seconds ends as 0x100|SIGALRM;
 *                        0x2FF = fork failed; if decoding the shared prefix
 *                        itself dies or times out, every candidate stays 0x300
 *                        and the reply is still status 0),
 *                        s16 pcm[K][N][L],
 *                        diag[K][N]
 *   4 CHECKPOINT payload name (1..63 bytes)  snapshot the base state under name
 *   5 RESTORE    payload name                base := copy of the checkpoint
 *                                            (the checkpoint stays available)
 *   6 DROP       payload name                forget a checkpoint
 *   7 INFO       reply   u32 version, initialised, output_fs, jobs,
 *                        u64 frames_committed, u32 n_checkpoints,
 *                        n_checkpoints * 64-byte NUL-padded names
 *   8 QUIT
 *
 * DIAGNOSTICS (struct cd_diag, 48 bytes, one per decoded frame)
 *   bfi_in        st->bfi after read_indices(): sync word, modified by the G.192
 *                 RX-DTX handler (lib_com/bitstream.c read_indices()).
 *   bfi_out       st->bfi after evs_dec() = the value updt_dec_common() stores in
 *                 st->prev_bfi.  1 if the frame was concealed, including good
 *                 frames rejected by the decoder: corrupted signalling in
 *                 lib_dec/decision_matrix_dec.c, MODE2 BER in
 *                 lib_dec/dec_acelp_tcx_main.c, and evs_dec.c's MODE2 tail
 *                 (bfi = m_decodeMode == DEC_CONCEALMENT_EXT).
 *   ber_detect    st->BER_detect after evs_dec().  Set by bit-reader overruns
 *                 (get_next_indice(), get_indice() etc. in lib_com/bitstream.c), the
 *                 arithmetic decoders (lib_dec/ACcontextMapping_dec.c,
 *                 arith_coder_dec.c), and index validity checks (lsf_dec.c,
 *                 avq_dec.c, dec_acelp.c, dec4t64.c, gs_dec.c, gaus_dec.c,
 *                 hq_lr_dec.c, hq_env_dec.c, peak_vq_dec.c, igf_scf_dec.c,
 *                 dec_prm.c, FEC_clas_estim.c, lib_com/tns_base.c, hq_tools.c,
 *                 dec_prm_core()).  The decision-matrix and MODE2 paths reset it
 *                 to 0 after converting the frame to concealment (bfi_out = 1).
 *   codec_mode_in st->codec_mode after read_indices() (decoder_selectCodec() +
 *                 mdct_switching_dec(); 2 = 13.2 kbps TCX20 frame).
 *   codec_mode    st->codec_mode after evs_dec().
 *   core          st->core (0 ACELP, 1 TCX20, 2 TCX10, 3 HQ, 4 AMR-WB).
 *   coder_type    st->prev_coder_type, i.e. evs_dec()'s local coder_type
 *                 (0 INACTIVE, 1 UNVOICED, 2 VOICED, 3 GENERIC, 4 TRANSITION,
 *                 5 AUDIO, 6 LR_MDCT); evs_dec() stores GENERIC for HQ frames.
 *   bwidth        st->bwidth (0 NB, 1 WB, 2 SWB, 3 FB).
 *   extl          st->extl (bandwidth-extension layer, -1 none; see cnst.h).
 *   L_frame       st->L_frame (256 = 12.8 kHz core, 320 = 16 kHz core).
 *   next_bit_pos  st->next_bit_pos after evs_dec(): bits consumed by the parser.
 *   nbits         the frame's G.192 length.  Bits available to get_next_indice()
 *                 are st->total_brate/50; MODE2 get_next_indice_1() also allows
 *                 the 16 arithmetic-coder flush bits.
 *   clas_dec      st->clas_dec (FEC signal class).
 *   hq_core_type  st->last_hq_core_type (0 normal HQ, 1 low-rate HQ, -1 none).
 *                 updt_dec_common() (lib_dec/updt_dec.c) updates it on MODE1
 *                 frames only (-1 for good non-HQ MODE1 frames, the previous
 *                 value for concealed ones); MODE2 frames, e.g. 13.2 kbps TCX20,
 *                 keep the value of the last MODE1 frame.
 *   mdct_sw       st->mdct_sw (1 = MODE1->TCX switching from mdct_switching_dec()).
 *   m_frame_type  st->m_frame_type, an unsigned char in the reference:
 *                 0xF0 (240) ZERO_FRAME, 0xFA (250) SID_FRAME, 0xFF (255)
 *                 ACTIVE_FRAME (lib_com/cnst.h).
 *   clip_count    return value of syn_output() (lib_dec/syn_outp.c, mvr2s()):
 *                 samples saturated to int16 (capped at 32767).
 *   cng           st->CNG (RX-DTX handler CNG state).
 *   total_brate   st->total_brate after evs_dec().
 *   core_brate    st->core_brate after evs_dec().
 *   peak          max |float synthesis| of the frame before int16 conversion.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "options.h"
#include "prot.h"
#include "cnst.h"
#include "rom_com.h"

/* Defined by lib_dec/decoder.c (left out because it holds main()); referenced by
   lib_dec/voip_client.c.  Incremented per decoded frame exactly like main(). */
long frame = 0;

#define CD_VERSION          1u
#define CD_MAX_NAME         63
#define CD_MAX_CHECKPOINTS  256
/* largest reply body the u32 length field can describe; FEED and EVAL requests whose
   reply would be larger are rejected BEFORE decoding (the state stays unchanged) */
#define CD_MAX_RESPONSE     ((size_t)0xFFFFFFFFu)

enum
{
    CD_CMD_INIT = 1, CD_CMD_FEED = 2, CD_CMD_EVAL = 3, CD_CMD_CHECKPOINT = 4,
    CD_CMD_RESTORE = 5, CD_CMD_DROP = 6, CD_CMD_INFO = 7, CD_CMD_QUIT = 8
};

/* router -> state process operations (besides CD_CMD_FEED / CD_CMD_EVAL) */
enum { CD_OP_CLONE = 100, CD_OP_INFO = 101 };

/* state process -> router acknowledgements */
enum { CD_ACK_DONE = 0, CD_ACK_CONSUMED = 1, CD_ACK_FAIL = 2 };

/* EVAL per-candidate status */
#define CD_STATUS_OK        0
#define CD_STATUS_SIGNAL    0x100
#define CD_STATUS_EXIT      0x200
#define CD_STATUS_NOT_RUN   0x300

typedef struct
{
    int16_t bfi_in;
    int16_t bfi_out;
    int16_t ber_detect;
    int16_t codec_mode_in;
    int16_t codec_mode;
    int16_t core;
    int16_t coder_type;
    int16_t bwidth;
    int16_t extl;
    int16_t L_frame;
    int16_t next_bit_pos;
    int16_t nbits;
    int16_t clas_dec;
    int16_t hq_core_type;
    int16_t mdct_sw;
    int16_t m_frame_type;
    int16_t clip_count;
    int16_t cng;
    int32_t total_brate;
    int32_t core_brate;
    float   peak;
} cd_diag;

typedef char cd_diag_size_check[(sizeof(cd_diag) == 48) ? 1 : -1];

typedef struct
{
    const uint8_t *bytes;
    uint16_t nbits;
    uint8_t bad;
    uint32_t rec_len;
} cd_frame;

typedef struct { uint32_t op; uint32_t len; } cd_msg;
typedef struct { int32_t status; int32_t v[7]; } cd_ack;

/* process-wide (inherited by every fork) */
static int cd_in = -1, cd_out = -1;
static int cd_jobs = 1;
static unsigned cd_timeout = 120;   /* seconds per EVAL candidate / prefix; 0 = none */

/* state-process globals */
static Decoder_State *cd_st = NULL;
static int cd_output_frame = 0;
static uint64_t cd_committed = 0;

/*--------------------------------------------------------------------------*
 * small I/O helpers
 *--------------------------------------------------------------------------*/

static int cd_read_full(int fd, void *buf, size_t n)
{
    uint8_t *p = (uint8_t *)buf;
    while (n)
    {
        ssize_t r = read(fd, p, n);
        if (r < 0 && errno == EINTR)
        {
            continue;
        }
        if (r <= 0)
        {
            return -1;
        }
        p += r;
        n -= (size_t)r;
    }
    return 0;
}

static int cd_write_full(int fd, const void *buf, size_t n)
{
    const uint8_t *p = (const uint8_t *)buf;
    while (n)
    {
        ssize_t r = write(fd, p, n);
        if (r < 0 && errno == EINTR)
        {
            continue;
        }
        if (r <= 0)
        {
            return -1;
        }
        p += r;
        n -= (size_t)r;
    }
    return 0;
}

static int cd_discard(int fd, size_t n)
{
    uint8_t tmp[65536];
    while (n)
    {
        size_t k = n < sizeof(tmp) ? n : sizeof(tmp);
        if (cd_read_full(fd, tmp, k) < 0)
        {
            return -1;
        }
        n -= k;
    }
    return 0;
}

static void cd_die_io(void)
{
    _exit(3);   /* the client went away */
}

static void cd_reply(uint32_t status, const void *a, size_t alen, const void *b, size_t blen)
{
    uint32_t hdr[2];
    hdr[0] = status;
    hdr[1] = (uint32_t)(alen + blen);
    if (cd_write_full(cd_out, hdr, sizeof(hdr)) < 0 ||
            (alen && cd_write_full(cd_out, a, alen) < 0) ||
            (blen && cd_write_full(cd_out, b, blen) < 0))
    {
        cd_die_io();
    }
}

static void cd_reply_error(const char *fmt, ...)
{
    char msg[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);
    cd_reply(1, msg, strlen(msg), NULL, 0);
}

static void *cd_map(size_t n, int shared)
{
    void *p;
    if (n == 0)
    {
        n = 1;
    }
    p = mmap(NULL, n, PROT_READ | PROT_WRITE, (shared ? MAP_SHARED : MAP_PRIVATE) | MAP_ANONYMOUS, -1, 0);
    return p == MAP_FAILED ? NULL : p;
}

static void cd_unmap(void *p, size_t n)
{
    if (p)
    {
        munmap(p, n ? n : 1);
    }
}

static int cd_send(int sock, const cd_msg *m, int fd)
{
    struct msghdr mh;
    struct iovec iov;
    union { char buf[CMSG_SPACE(sizeof(int))]; struct cmsghdr align; } u;
    ssize_t r;

    memset(&mh, 0, sizeof(mh));
    iov.iov_base = (void *)m;
    iov.iov_len = sizeof(*m);
    mh.msg_iov = &iov;
    mh.msg_iovlen = 1;
    if (fd >= 0)
    {
        struct cmsghdr *c;
        memset(&u, 0, sizeof(u));
        mh.msg_control = u.buf;
        mh.msg_controllen = sizeof(u.buf);
        c = CMSG_FIRSTHDR(&mh);
        c->cmsg_level = SOL_SOCKET;
        c->cmsg_type = SCM_RIGHTS;
        c->cmsg_len = CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(c), &fd, sizeof(int));
    }
    do
    {
        r = sendmsg(sock, &mh, MSG_NOSIGNAL);
    }
    while (r < 0 && errno == EINTR);
    return r == (ssize_t)sizeof(*m) ? 0 : -1;
}

static int cd_recv(int sock, cd_msg *m, int *fd)
{
    struct msghdr mh;
    struct iovec iov;
    union { char buf[CMSG_SPACE(sizeof(int))]; struct cmsghdr align; } u;
    struct cmsghdr *c;
    ssize_t r;

    *fd = -1;
    memset(&mh, 0, sizeof(mh));
    iov.iov_base = m;
    iov.iov_len = sizeof(*m);
    mh.msg_iov = &iov;
    mh.msg_iovlen = 1;
    mh.msg_control = u.buf;
    mh.msg_controllen = sizeof(u.buf);
    do
    {
        r = recvmsg(sock, &mh, 0);
    }
    while (r < 0 && errno == EINTR);
    if (r != (ssize_t)sizeof(*m))
    {
        return -1;
    }
    for (c = CMSG_FIRSTHDR(&mh); c; c = CMSG_NXTHDR(&mh, c))
    {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_RIGHTS)
        {
            memcpy(fd, CMSG_DATA(c), sizeof(int));
        }
    }
    return 0;
}

static int cd_send_ack(int sock, int32_t status, const int32_t *v, int nv)
{
    cd_ack a;
    ssize_t r;
    memset(&a, 0, sizeof(a));
    a.status = status;
    if (v && nv > 0)
    {
        memcpy(a.v, v, sizeof(int32_t) * (size_t)(nv > 7 ? 7 : nv));
    }
    do
    {
        r = send(sock, &a, sizeof(a), MSG_NOSIGNAL);
    }
    while (r < 0 && errno == EINTR);
    return r == (ssize_t)sizeof(a) ? 0 : -1;
}

static int cd_recv_ack(int sock, cd_ack *a)
{
    ssize_t r;
    do
    {
        r = recv(sock, a, sizeof(*a), 0);
    }
    while (r < 0 && errno == EINTR);
    return r == (ssize_t)sizeof(*a) ? 0 : -1;
}

/*--------------------------------------------------------------------------*
 * frames
 *--------------------------------------------------------------------------*/

static int cd_valid_bits(unsigned nbits)
{
    /* the rates read_indices() accepts (rate2EVSmode() in lib_com/bitstream.c) */
    static const long rates[] =
    {
        FRAME_NO_DATA, SID_1k75, SID_2k40, PPP_NELP_2k80, ACELP_6k60, ACELP_7k20, ACELP_8k00,
        ACELP_8k85, ACELP_9k60, ACELP_12k65, ACELP_13k20, ACELP_14k25, ACELP_15k85, ACELP_16k40,
        ACELP_18k25, ACELP_19k85, ACELP_23k05, ACELP_23k85, ACELP_24k40, ACELP_32k, ACELP_48k,
        ACELP_64k, HQ_96k, HQ_128k
    };
    size_t i;
    if (nbits > MAX_BITS_PER_FRAME)
    {
        return 0;
    }
    for (i = 0; i < sizeof(rates) / sizeof(rates[0]); i++)
    {
        if ((long)nbits * 50 == rates[i])
        {
            return 1;
        }
    }
    return 0;
}

/* Parse exactly `count` frame records filling all `len` bytes; 0 = OK, -1 = error (err set). */
static int cd_parse(const uint8_t *p, size_t len, size_t count, cd_frame *out, char *err, size_t errlen)
{
    size_t pos = 0, i;
    for (i = 0; i < count; i++)
    {
        unsigned nbits, nbytes;
        if (len - pos < 4)
        {
            snprintf(err, errlen, "frame %zu: truncated record header", i);
            return -1;
        }
        if (p[pos] > 1 || p[pos + 1] != 0)
        {
            snprintf(err, errlen, "frame %zu: flag must be 0 (good) or 1 (bad)", i);
            return -1;
        }
        nbits = (unsigned)p[pos + 2] | ((unsigned)p[pos + 3] << 8);
        if (!cd_valid_bits(nbits))
        {
            snprintf(err, errlen, "frame %zu: %u bits is not a G.192 EVS/AMR-WB-IO rate", i, nbits);
            return -1;
        }
        nbytes = (nbits + 7) / 8;
        if (len - pos - 4 < nbytes)
        {
            snprintf(err, errlen, "frame %zu: truncated bits", i);
            return -1;
        }
        out[i].bad = p[pos];
        out[i].nbits = (uint16_t)nbits;
        out[i].bytes = p + pos + 4;
        out[i].rec_len = 4 + nbytes;
        pos += 4 + nbytes;
    }
    if (pos != len)
    {
        snprintf(err, errlen, "%zu trailing bytes after %zu frame records", len - pos, count);
        return -1;
    }
    return 0;
}

static int cd_same_frame(const cd_frame *a, const cd_frame *b)
{
    return a->bad == b->bad && a->nbits == b->nbits && memcmp(a->bytes, b->bytes, (a->nbits + 7u) / 8u) == 0;
}

/* Serialise frames to ITU-T G.192 words exactly as EVS_dec would read them. */
static uint16_t *cd_g192(const cd_frame *f, size_t n, size_t *bytes)
{
    size_t words = 0, i;
    uint16_t *buf, *w;
    for (i = 0; i < n; i++)
    {
        words += 2 + f[i].nbits;
    }
    buf = (uint16_t *)malloc(words * sizeof(uint16_t));
    if (!buf)
    {
        return NULL;
    }
    w = buf;
    for (i = 0; i < n; i++)
    {
        unsigned b;
        *w++ = f[i].bad ? SYNC_BAD_FRAME : SYNC_GOOD_FRAME;
        *w++ = f[i].nbits;
        for (b = 0; b < f[i].nbits; b++)
        {
            *w++ = ((f[i].bytes[b >> 3] >> (7 - (b & 7))) & 1) ? G192_BIN1 : G192_BIN0;
        }
    }
    *bytes = words * sizeof(uint16_t);
    return buf;
}

/*--------------------------------------------------------------------------*
 * decoding (mirrors the frame loop of lib_dec/decoder.c main())
 *--------------------------------------------------------------------------*/

/* Decode n frames into the current process's decoder state.  pcm may be NULL.
   Returns 0 on success. */
static int cd_decode(const cd_frame *f, size_t n, int16_t *pcm, cd_diag *diag)
{
    Decoder_State *st = cd_st;
    size_t bytes = 0, i;
    uint16_t *g;
    FILE *fp;

    if (n == 0)
    {
        return 0;
    }
    g = cd_g192(f, n, &bytes);
    if (!g)
    {
        return -1;
    }
    fp = fmemopen(g, bytes, "rb");
    if (!fp)
    {
        free(g);
        return -1;
    }

    for (i = 0; i < n; i++)
    {
        float output[L_FRAME48k];
        short data[L_FRAME48k];
        cd_diag *d = &diag[i];
        unsigned int clipped;
        float peak = 0.0f;
        int k;

        if (!read_indices(st, fp, 0))
        {
            fclose(fp);
            free(g);
            return -1;
        }
        d->bfi_in = st->bfi;
        d->codec_mode_in = st->codec_mode;

        /* run the main decoding routine */
        if (st->codec_mode == MODE1)
        {
            if (st->Opt_AMR_WB)
            {
                amr_wb_dec(st, output);
            }
            else
            {
                evs_dec(st, output, FRAMEMODE_NORMAL);
            }
        }
        else
        {
            if (!st->bfi)
            {
                evs_dec(st, output, FRAMEMODE_NORMAL);
            }
            else
            {
                evs_dec(st, output, FRAMEMODE_MISSING);
            }
        }

        for (k = 0; k < cd_output_frame; k++)
        {
            float a = output[k] < 0.0f ? -output[k] : output[k];
            if (a > peak || a != a)
            {
                peak = a;
            }
        }

        /* convert 'float' output data to 'short' */
        clipped = syn_output(output, (short)cd_output_frame, data);

        /* increase the counter of initialization frames */
        if (st->ini_frame < MAX_FRAME_COUNTER)
        {
            st->ini_frame++;
        }

        if (pcm)
        {
            memcpy(pcm + i * (size_t)cd_output_frame, data, sizeof(short) * (size_t)cd_output_frame);
        }
        d->bfi_out = st->bfi;
        d->ber_detect = st->BER_detect;
        d->codec_mode = st->codec_mode;
        d->core = st->core;
        d->coder_type = st->prev_coder_type;
        d->bwidth = st->bwidth;
        d->extl = st->extl;
        d->L_frame = st->L_frame;
        d->next_bit_pos = st->next_bit_pos;
        d->nbits = (int16_t)f[i].nbits;
        d->clas_dec = st->clas_dec;
        d->hq_core_type = st->last_hq_core_type;
        d->mdct_sw = st->mdct_sw;
        d->m_frame_type = (int16_t)st->m_frame_type;
        d->clip_count = (int16_t)(clipped > 32767 ? 32767 : clipped);
        d->cng = st->CNG;
        d->total_brate = (int32_t)st->total_brate;
        d->core_brate = (int32_t)st->core_brate;
        d->peak = peak;

        frame++;
    }
    fclose(fp);
    free(g);
    return 0;
}

/* Replays main()'s allocation, io_ini_dec() and init_decoder() for G.192 input. */
static int cd_init_state(int output_fs, unsigned first_good_bits, int32_t *dec_delay)
{
    Decoder_State *st;
    cd_frame probe;
    uint8_t zeros[MAX_BITS_PER_FRAME / 8];
    size_t bytes = 0;
    uint16_t *g;
    FILE *fp;

    if ((st = (Decoder_State *)malloc(sizeof(Decoder_State))) == NULL)
    {
        return -1;
    }
    /* main(): set to NULL, to avoid reading of uninitialized memory in case of early abort */
    st->cldfbAna = st->cldfbBPF = st->cldfbSyn = NULL;
    st->hFdCngDec = NULL;

    /* io_ini_dec() for 'EVS_dec [-q] [-no_delay_cmp] fs in.192 out.raw' */
    st->writeFECoffset = 0;
    st->codec_mode = 0;
    st->Opt_AMR_WB = 0;
    st->Opt_VOIP = 0;
    st->bitstreamformat = G192;
    st->amrwb_rfc4867_flag = -1;
    st->output_Fs = output_fs;
    st->ini_frame = 0;

    /* read_indices( st, f_stream, 1 ): only the first good frame's length matters */
    memset(zeros, 0, sizeof(zeros));
    probe.bad = 0;
    probe.nbits = (uint16_t)first_good_bits;
    probe.bytes = zeros;
    probe.rec_len = 0;
    g = cd_g192(&probe, 1, &bytes);
    if (!g || (fp = fmemopen(g, bytes, "rb")) == NULL)
    {
        return -1;
    }
    read_indices(st, fp, 1);
    fclose(fp);
    free(g);

    /* main() */
    init_decoder(st);
    reset_indices_dec(st);

    cd_st = st;
    cd_output_frame = (int)(st->output_Fs / 50);
    cd_committed = 0;
    *dec_delay = NS2SA(st->output_Fs, get_delay(DEC, st->output_Fs) + 0.5f);
    return 0;
}

/*--------------------------------------------------------------------------*
 * state process: FEED / EVAL / CLONE
 *--------------------------------------------------------------------------*/

/* Reads a payload into a private mapping and acknowledges consumption. */
static uint8_t *cd_take_payload(int ctrl, uint32_t len)
{
    uint8_t *buf = (uint8_t *)cd_map(len, 0);
    if (!buf)
    {
        cd_discard(cd_in, len);
    }
    else if (cd_read_full(cd_in, buf, len) < 0)
    {
        cd_die_io();
    }
    if (cd_send_ack(ctrl, CD_ACK_CONSUMED, NULL, 0) < 0)
    {
        _exit(0);
    }
    return buf;
}

static void cd_handle_feed(int ctrl, uint32_t len)
{
    uint8_t *buf = cd_take_payload(ctrl, len);
    char err[256];
    uint32_t n, head[2];
    cd_frame *frames = NULL;
    uint8_t *resp = NULL;
    size_t resp_len = 0, pcm_bytes;

    if (!buf)
    {
        cd_reply_error("FEED: out of memory");
        return;
    }
    if (len < 4)
    {
        cd_reply_error("FEED: payload too short");
        goto done;
    }
    memcpy(&n, buf, 4);
    frames = (cd_frame *)calloc(n ? n : 1, sizeof(cd_frame));
    if (!frames)
    {
        cd_reply_error("FEED: out of memory");
        goto done;
    }
    if (cd_parse(buf + 4, len - 4, n, frames, err, sizeof(err)) < 0)
    {
        cd_reply_error("FEED: %s", err);
        goto done;
    }
    pcm_bytes = (size_t)n * (size_t)cd_output_frame * sizeof(int16_t);
    resp_len = pcm_bytes + (size_t)n * sizeof(cd_diag);
    if (resp_len + 2 * sizeof(uint32_t) > CD_MAX_RESPONSE)
    {
        resp_len = 0;
        cd_reply_error("FEED: %u frames would need a reply over 4 GiB; send fewer frames", n);
        goto done;
    }
    resp = (uint8_t *)cd_map(resp_len, 0);
    if (!resp)
    {
        cd_reply_error("FEED: out of memory");
        goto done;
    }
    if (cd_decode(frames, n, (int16_t *)resp, (cd_diag *)(resp + pcm_bytes)) < 0)
    {
        cd_reply_error("FEED: decoding failed");
        goto done;
    }
    cd_committed += n;
    head[0] = n;
    head[1] = (uint32_t)cd_output_frame;
    cd_reply(0, head, sizeof(head), resp, resp_len);

done:
    cd_unmap(resp, resp_len);
    free(frames);
    cd_unmap(buf, len);
}

typedef struct
{
    uint32_t next;          /* atomic candidate counter */
    uint32_t pad[15];
} cd_shm_head;

static int32_t cd_status_of(int ws)
{
    if (WIFSIGNALED(ws))
    {
        return CD_STATUS_SIGNAL | WTERMSIG(ws);
    }
    if (WIFEXITED(ws) && WEXITSTATUS(ws) != 0)
    {
        return CD_STATUS_EXIT | WEXITSTATUS(ws);
    }
    return CD_STATUS_OK;
}

static void cd_worker(cd_shm_head *head, volatile int32_t *status, int16_t *pcm, cd_diag *diag,
                      const cd_frame *frames, uint32_t K, uint32_t N, uint32_t prefix)
{
    size_t L = (size_t)cd_output_frame;
    for (;;)
    {
        uint32_t k = __atomic_fetch_add(&head->next, 1u, __ATOMIC_SEQ_CST);
        pid_t c;
        int ws;
        if (k >= K)
        {
            _exit(0);
        }
        c = fork();
        if (c == 0)
        {
            size_t base = (size_t)k * N + prefix;
            alarm(cd_timeout);   /* watchdog: a hung candidate ends as 0x100|SIGALRM */
            if (cd_decode(frames + base, N - prefix, pcm ? pcm + base * L : NULL, diag + base) < 0)
            {
                _exit(2);
            }
            status[k] = CD_STATUS_OK;
            _exit(0);
        }
        if (c < 0)
        {
            status[k] = CD_STATUS_EXIT | 0xff;
            continue;
        }
        while (waitpid(c, &ws, 0) < 0 && errno == EINTR)
        {
        }
        if (cd_status_of(ws) != CD_STATUS_OK)
        {
            status[k] = cd_status_of(ws);
        }
    }
}

static void cd_dispatch(cd_shm_head *head, volatile int32_t *status, int16_t *pcm, cd_diag *diag,
                        const cd_frame *frames, uint32_t K, uint32_t N, uint32_t prefix)
{
    size_t L = (size_t)cd_output_frame;
    uint32_t k, w, workers;

    if (prefix)
    {
        alarm(cd_timeout);
        if (cd_decode(frames, prefix, pcm, diag) < 0)
        {
            _exit(2);
        }
        alarm(0);
        for (k = 1; k < K; k++)
        {
            if (pcm)
            {
                memcpy(pcm + (size_t)k * N * L, pcm, prefix * L * sizeof(int16_t));
            }
            memcpy(diag + (size_t)k * N, diag, prefix * sizeof(cd_diag));
        }
    }
    if (prefix == N)
    {
        for (k = 0; k < K; k++)
        {
            status[k] = CD_STATUS_OK;
        }
        _exit(0);
    }
    workers = (uint32_t)cd_jobs < K ? (uint32_t)cd_jobs : K;
    for (w = 0; w < workers; w++)
    {
        pid_t p = fork();
        if (p == 0)
        {
            cd_worker(head, status, pcm, diag, frames, K, N, prefix);
        }
    }
    while (wait(NULL) > 0 || errno == EINTR)
    {
    }
    _exit(0);
}

static void cd_handle_eval(int ctrl, uint32_t len)
{
    uint8_t *buf = cd_take_payload(ctrl, len);
    char err[256];
    uint32_t K, N, flags, prefix = 0, i, k, head5[5];
    size_t total, off_status, off_pcm, off_diag, shm_len = 0;
    cd_frame *frames = NULL;
    uint8_t *shm = NULL;
    volatile int32_t *status;
    int16_t *pcm;
    cd_diag *diag;
    pid_t p;
    int ws;

    if (!buf)
    {
        cd_reply_error("EVAL: out of memory");
        return;
    }
    if (len < 12)
    {
        cd_reply_error("EVAL: payload too short");
        goto done;
    }
    memcpy(&K, buf, 4);
    memcpy(&N, buf + 4, 4);
    memcpy(&flags, buf + 8, 4);
    total = (size_t)K * (size_t)N;
    if (K > (1u << 20) || N > (1u << 20) || total > (1u << 24))
    {
        cd_reply_error("EVAL: K*N too large");
        goto done;
    }
    if (5 * sizeof(uint32_t) + (size_t)K * sizeof(int32_t) + total * sizeof(cd_diag) +
            ((flags & 1) ? 0 : total * (size_t)cd_output_frame * sizeof(int16_t)) > CD_MAX_RESPONSE)
    {
        cd_reply_error("EVAL: the reply would exceed 4 GiB; use fewer candidates/frames or omit PCM");
        goto done;
    }
    frames = (cd_frame *)calloc(total ? total : 1, sizeof(cd_frame));
    if (!frames)
    {
        cd_reply_error("EVAL: out of memory");
        goto done;
    }
    if (cd_parse(buf + 12, len - 12, total, frames, err, sizeof(err)) < 0)
    {
        cd_reply_error("EVAL: %s", err);
        goto done;
    }

    /* frames shared by every candidate are decoded once, by the dispatcher */
    for (i = 0; i < N && K > 0; i++)
    {
        for (k = 1; k < K; k++)
        {
            if (!cd_same_frame(&frames[i], &frames[(size_t)k * N + i]))
            {
                break;
            }
        }
        if (k < K)
        {
            break;
        }
        prefix++;
    }

    off_status = sizeof(cd_shm_head);
    off_pcm = off_status + (((size_t)K * sizeof(int32_t) + 7) & ~(size_t)7);
    off_diag = off_pcm + ((flags & 1) ? 0 : ((total * (size_t)cd_output_frame * sizeof(int16_t) + 7) & ~(size_t)7));
    shm_len = off_diag + total * sizeof(cd_diag);
    shm = (uint8_t *)cd_map(shm_len, 1);
    if (!shm)
    {
        cd_reply_error("EVAL: cannot map %zu bytes of shared memory", shm_len);
        goto done;
    }
    status = (volatile int32_t *)(shm + off_status);
    pcm = (flags & 1) ? NULL : (int16_t *)(shm + off_pcm);
    diag = (cd_diag *)(shm + off_diag);
    for (k = 0; k < K; k++)
    {
        status[k] = CD_STATUS_NOT_RUN;
    }

    if (K > 0 && N > 0)
    {
        p = fork();
        if (p == 0)
        {
            cd_dispatch((cd_shm_head *)shm, status, pcm, diag, frames, K, N, prefix);
        }
        if (p < 0)
        {
            cd_reply_error("EVAL: fork failed: %s", strerror(errno));
            goto done;
        }
        while (waitpid(p, &ws, 0) < 0 && errno == EINTR)
        {
        }
    }
    else
    {
        for (k = 0; k < K; k++)
        {
            status[k] = CD_STATUS_OK;
        }
    }

    head5[0] = K;
    head5[1] = N;
    head5[2] = (flags & 1) ? 0u : (uint32_t)cd_output_frame;
    head5[3] = prefix;
    head5[4] = (uint32_t)sizeof(cd_diag);
    /* send the packed status, pcm and diag blocks straight from the shared area */
    {
        size_t status_bytes = (size_t)K * sizeof(int32_t);
        size_t pcm_bytes = (flags & 1) ? 0 : total * (size_t)cd_output_frame * sizeof(int16_t);
        size_t diag_bytes = total * sizeof(cd_diag);
        uint32_t hdr[2];
        hdr[0] = 0;
        hdr[1] = (uint32_t)(sizeof(head5) + status_bytes + pcm_bytes + diag_bytes);
        if (cd_write_full(cd_out, hdr, sizeof(hdr)) < 0 ||
                cd_write_full(cd_out, head5, sizeof(head5)) < 0 ||
                cd_write_full(cd_out, shm + off_status, status_bytes) < 0 ||
                (pcm_bytes && cd_write_full(cd_out, shm + off_pcm, pcm_bytes) < 0) ||
                cd_write_full(cd_out, shm + off_diag, diag_bytes) < 0)
        {
            cd_die_io();
        }
    }

done:
    cd_unmap(shm, shm_len);
    free(frames);
    cd_unmap(buf, len);
}

static void cd_state_loop(int ctrl)
{
    for (;;)
    {
        cd_msg m;
        int fd = -1;

        if (cd_recv(ctrl, &m, &fd) < 0)
        {
            _exit(0);   /* router dropped this state */
        }
        switch (m.op)
        {
        case CD_CMD_FEED:
            cd_handle_feed(ctrl, m.len);
            cd_send_ack(ctrl, CD_ACK_DONE, NULL, 0);
            break;
        case CD_CMD_EVAL:
            cd_handle_eval(ctrl, m.len);
            cd_send_ack(ctrl, CD_ACK_DONE, NULL, 0);
            break;
        case CD_OP_INFO:
        {
            int32_t v[3];
            v[0] = (int32_t)(cd_committed & 0xffffffffu);
            v[1] = (int32_t)(cd_committed >> 32);
            v[2] = cd_st ? (int32_t)cd_st->output_Fs : 0;
            cd_send_ack(ctrl, CD_ACK_DONE, v, 3);
            break;
        }
        case CD_OP_CLONE:
        {
            pid_t p1;
            int ws = 0;
            if (fd < 0)
            {
                cd_send_ack(ctrl, CD_ACK_FAIL, NULL, 0);
                break;
            }
            p1 = fork();
            if (p1 == 0)
            {
                pid_t p2 = fork();
                if (p2 == 0)
                {
                    /* the clone: same memory image, new control channel */
                    int32_t v[1];
                    close(ctrl);
                    ctrl = fd;
                    v[0] = (int32_t)getpid();
                    if (cd_send_ack(ctrl, CD_ACK_DONE, v, 1) < 0)
                    {
                        _exit(0);
                    }
                    continue;
                }
                _exit(p2 < 0 ? 1 : 0);
            }
            close(fd);
            if (p1 > 0)
            {
                while (waitpid(p1, &ws, 0) < 0 && errno == EINTR)
                {
                }
            }
            cd_send_ack(ctrl, (p1 > 0 && WIFEXITED(ws) && WEXITSTATUS(ws) == 0) ? CD_ACK_DONE : CD_ACK_FAIL, NULL, 0);
            break;
        }
        default:
            cd_send_ack(ctrl, CD_ACK_FAIL, NULL, 0);
            break;
        }
    }
}

/*--------------------------------------------------------------------------*
 * router
 *--------------------------------------------------------------------------*/

typedef struct
{
    char name[CD_MAX_NAME + 1];
    int fd;
    pid_t pid;
} cd_proc;

static cd_proc cd_base = { "", -1, 0 };
static cd_proc cd_ckpt[CD_MAX_CHECKPOINTS];
static int cd_output_fs = 0;

static void cd_reap(void)
{
    while (waitpid(-1, NULL, WNOHANG) > 0)
    {
    }
}

static void cd_drop(cd_proc *p)
{
    if (p->fd >= 0)
    {
        close(p->fd);   /* the state process exits when it reads EOF */
    }
    p->fd = -1;
    p->pid = 0;
    p->name[0] = 0;
}

static void cd_drop_all(void)
{
    int i;
    cd_drop(&cd_base);
    for (i = 0; i < CD_MAX_CHECKPOINTS; i++)
    {
        cd_drop(&cd_ckpt[i]);
    }
    cd_output_fs = 0;
}

/* Clone state process src into dst. */
static int cd_clone(cd_proc *src, cd_proc *dst)
{
    int sv[2];
    cd_msg m;
    cd_ack a, hello;

    if (socketpair(AF_UNIX, SOCK_SEQPACKET, 0, sv) < 0)
    {
        return -1;
    }
    m.op = CD_OP_CLONE;
    m.len = 0;
    if (cd_send(src->fd, &m, sv[1]) < 0)
    {
        close(sv[0]);
        close(sv[1]);
        return -1;
    }
    close(sv[1]);
    if (cd_recv_ack(src->fd, &a) < 0 || a.status != CD_ACK_DONE || cd_recv_ack(sv[0], &hello) < 0)
    {
        close(sv[0]);
        return -1;
    }
    dst->fd = sv[0];
    dst->pid = hello.v[0];
    return 0;
}

static int cd_read_name(uint32_t len, char *name)
{
    if (len == 0 || len > CD_MAX_NAME)
    {
        if (cd_discard(cd_in, len) < 0)
        {
            cd_die_io();
        }
        cd_reply_error("checkpoint names must be 1..%d bytes", CD_MAX_NAME);
        return -1;
    }
    memset(name, 0, CD_MAX_NAME + 1);
    if (cd_read_full(cd_in, name, len) < 0)
    {
        cd_die_io();
    }
    return 0;
}

static cd_proc *cd_find(const char *name)
{
    int i;
    for (i = 0; i < CD_MAX_CHECKPOINTS; i++)
    {
        if (cd_ckpt[i].fd >= 0 && strcmp(cd_ckpt[i].name, name) == 0)
        {
            return &cd_ckpt[i];
        }
    }
    return NULL;
}

static void cd_router_init(uint32_t len)
{
    uint32_t pl[16];
    int sv[2];
    pid_t p;
    cd_ack a;
    uint32_t fs, first;

    if (len < 8 || len > sizeof(pl))
    {
        if (cd_discard(cd_in, len) < 0)
        {
            cd_die_io();
        }
        cd_reply_error("INIT: payload must be 8..%zu bytes", sizeof(pl));
        return;
    }
    if (cd_read_full(cd_in, pl, len) < 0)
    {
        cd_die_io();
    }
    fs = pl[0];
    first = pl[1] ? pl[1] : 264;
    if (fs != 8000 && fs != 16000 && fs != 32000 && fs != 48000)
    {
        cd_reply_error("INIT: output rate %u is not 8000/16000/32000/48000", fs);
        return;
    }
    if (!cd_valid_bits(first) || first * 50 < 2800)
    {
        cd_reply_error("INIT: first_good_bits %u is not a speech frame length", first);
        return;
    }
    cd_drop_all();
    cd_reap();
    if (socketpair(AF_UNIX, SOCK_SEQPACKET, 0, sv) < 0)
    {
        cd_reply_error("INIT: socketpair failed: %s", strerror(errno));
        return;
    }
    p = fork();
    if (p == 0)
    {
        int32_t v[4], dec_delay = 0;
        close(sv[0]);
        if (cd_init_state((int)fs, first, &dec_delay) < 0)
        {
            cd_send_ack(sv[1], CD_ACK_FAIL, NULL, 0);
            _exit(1);
        }
        v[0] = cd_output_frame;
        v[1] = dec_delay;
        v[2] = (int32_t)sizeof(Decoder_State);
        v[3] = (int32_t)getpid();
        cd_send_ack(sv[1], CD_ACK_DONE, v, 4);
        cd_state_loop(sv[1]);
        _exit(0);
    }
    close(sv[1]);
    if (p < 0 || cd_recv_ack(sv[0], &a) < 0 || a.status != CD_ACK_DONE)
    {
        close(sv[0]);
        cd_reply_error("INIT: decoder initialisation failed");
        return;
    }
    cd_base.fd = sv[0];
    cd_base.pid = p;
    cd_output_fs = (int)fs;
    {
        uint32_t r[7];
        r[0] = CD_VERSION;
        r[1] = fs;
        r[2] = (uint32_t)a.v[0];
        r[3] = (uint32_t)a.v[1];
        r[4] = (uint32_t)sizeof(cd_diag);
        r[5] = (uint32_t)cd_jobs;
        r[6] = (uint32_t)a.v[2];
        cd_reply(0, r, sizeof(r), NULL, 0);
    }
}

static void cd_router_forward(uint32_t cmd, uint32_t len)
{
    cd_msg m;
    cd_ack a;
    int consumed = 0;

    if (cd_base.fd < 0)
    {
        if (cd_discard(cd_in, len) < 0)
        {
            cd_die_io();
        }
        cd_reply_error("no decoder state: send INIT (or RESTORE a checkpoint) first");
        return;
    }
    m.op = cmd;
    m.len = len;
    if (cd_send(cd_base.fd, &m, -1) == 0 && cd_recv_ack(cd_base.fd, &a) == 0 && a.status == CD_ACK_CONSUMED)
    {
        consumed = 1;
        if (cd_recv_ack(cd_base.fd, &a) == 0 && a.status == CD_ACK_DONE)
        {
            return;   /* the state process wrote the response */
        }
    }
    /* the base process died: keep the stream in sync and report it */
    if (!consumed && cd_discard(cd_in, len) < 0)
    {
        cd_die_io();
    }
    cd_drop(&cd_base);
    cd_reap();
    cd_reply_error("decoder process died while decoding; base state lost (RESTORE a checkpoint or INIT)");
}

static void cd_router_named(uint32_t cmd, uint32_t len)
{
    char name[CD_MAX_NAME + 1];
    cd_proc *p;
    int i;

    if (cd_read_name(len, name) < 0)
    {
        return;
    }
    if (cmd == CD_CMD_DROP)
    {
        if ((p = cd_find(name)) == NULL)
        {
            cd_reply_error("DROP: no checkpoint '%s'", name);
            return;
        }
        cd_drop(p);
        cd_reply(0, NULL, 0, NULL, 0);
        return;
    }
    if (cmd == CD_CMD_CHECKPOINT)
    {
        cd_proc fresh;
        if (cd_base.fd < 0)
        {
            cd_reply_error("CHECKPOINT: no decoder state");
            return;
        }
        if (cd_clone(&cd_base, &fresh) < 0)
        {
            cd_reply_error("CHECKPOINT: clone failed");
            return;
        }
        if ((p = cd_find(name)) != NULL)
        {
            cd_drop(p);
        }
        for (i = 0; i < CD_MAX_CHECKPOINTS && cd_ckpt[i].fd >= 0; i++)
        {
        }
        if (i == CD_MAX_CHECKPOINTS)
        {
            cd_drop(&fresh);
            cd_reply_error("CHECKPOINT: too many checkpoints (max %d)", CD_MAX_CHECKPOINTS);
            return;
        }
        cd_ckpt[i] = fresh;
        memcpy(cd_ckpt[i].name, name, sizeof(name));
        cd_reply(0, NULL, 0, NULL, 0);
        return;
    }
    /* RESTORE */
    {
        cd_proc fresh;
        cd_msg m;
        cd_ack a;
        if ((p = cd_find(name)) == NULL)
        {
            cd_reply_error("RESTORE: no checkpoint '%s'", name);
            return;
        }
        if (cd_clone(p, &fresh) < 0)
        {
            cd_reply_error("RESTORE: clone failed");
            return;
        }
        cd_drop(&cd_base);
        cd_base = fresh;
        cd_base.name[0] = 0;
        m.op = CD_OP_INFO;
        m.len = 0;
        if (cd_send(cd_base.fd, &m, -1) == 0 && cd_recv_ack(cd_base.fd, &a) == 0)
        {
            cd_output_fs = a.v[2];
        }
        cd_reply(0, NULL, 0, NULL, 0);
    }
}

static void cd_router_info(uint32_t len)
{
    uint32_t r[7];
    uint64_t committed = 0;
    char names[CD_MAX_CHECKPOINTS][64];
    uint32_t n = 0;
    int i;

    if (cd_discard(cd_in, len) < 0)
    {
        cd_die_io();
    }
    if (cd_base.fd >= 0)
    {
        cd_msg m;
        cd_ack a;
        m.op = CD_OP_INFO;
        m.len = 0;
        if (cd_send(cd_base.fd, &m, -1) == 0 && cd_recv_ack(cd_base.fd, &a) == 0)
        {
            committed = (uint64_t)(uint32_t)a.v[0] | ((uint64_t)(uint32_t)a.v[1] << 32);
        }
    }
    memset(names, 0, sizeof(names));
    for (i = 0; i < CD_MAX_CHECKPOINTS; i++)
    {
        if (cd_ckpt[i].fd >= 0)
        {
            memcpy(names[n++], cd_ckpt[i].name, CD_MAX_NAME + 1);
        }
    }
    r[0] = CD_VERSION;
    r[1] = cd_base.fd >= 0;
    r[2] = (uint32_t)cd_output_fs;
    r[3] = (uint32_t)cd_jobs;
    memcpy(&r[4], &committed, sizeof(committed));
    r[6] = n;
    cd_reply(0, r, sizeof(r), names, (size_t)n * 64);
}

static int cd_default_jobs(void)
{
    cpu_set_t set;
    long n;
    if (sched_getaffinity(0, sizeof(set), &set) == 0 && CPU_COUNT(&set) > 0)
    {
        return CPU_COUNT(&set);
    }
    n = sysconf(_SC_NPROCESSORS_ONLN);
    return n > 0 ? (int)n : 1;
}

static void cd_usage(const char *argv0)
{
    fprintf(stderr,
            "usage: %s [--jobs N] [--timeout SEC]\n"
            "Persistent exact EVS candidate decoder speaking a binary protocol on\n"
            "stdin/stdout (see the header of scripts/evs_candidate_decoder.c).\n"
            "--jobs N       parallel candidate decoders for EVAL (default: CPUs available)\n"
            "--timeout SEC  watchdog per EVAL candidate (default 120, 0 = none)\n",
            argv0);
}

int main(int argc, char *argv[])
{
    int i, devnull;

    cd_jobs = cd_default_jobs();
    for (i = 1; i < argc; i++)
    {
        if ((strcmp(argv[i], "--jobs") == 0 || strcmp(argv[i], "-j") == 0) && i + 1 < argc)
        {
            cd_jobs = atoi(argv[++i]);
            if (cd_jobs < 1)
            {
                cd_jobs = 1;
            }
        }
        else if (strcmp(argv[i], "--timeout") == 0 && i + 1 < argc)
        {
            int t = atoi(argv[++i]);
            cd_timeout = t > 0 ? (unsigned)t : 0;
        }
        else
        {
            cd_usage(argv[0]);
            return strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0 ? 0 : 2;
        }
    }
    for (i = 0; i < CD_MAX_CHECKPOINTS; i++)
    {
        cd_ckpt[i].fd = -1;
    }

    /* private protocol channels; the reference library's printf()s go to stderr */
    cd_in = dup(0);
    cd_out = dup(1);
    if (cd_in < 0 || cd_out < 0)
    {
        perror("dup");
        return 1;
    }
    devnull = open("/dev/null", O_RDONLY);
    if (devnull >= 0)
    {
        dup2(devnull, 0);
        close(devnull);
    }
    dup2(2, 1);
    setvbuf(stdout, NULL, _IONBF, 0);
    signal(SIGPIPE, SIG_DFL);
    {
        /* candidates that crash (e.g. reference assert()s on corrupted bits) must not dump core */
        struct rlimit nocore;
        nocore.rlim_cur = nocore.rlim_max = 0;
        setrlimit(RLIMIT_CORE, &nocore);
    }
    prctl(PR_SET_CHILD_SUBREAPER, 1);

    for (;;)
    {
        uint32_t hdr[2];
        cd_reap();
        if (cd_read_full(cd_in, hdr, sizeof(hdr)) < 0)
        {
            break;   /* client closed stdin */
        }
        switch (hdr[0])
        {
        case CD_CMD_INIT:
            cd_router_init(hdr[1]);
            break;
        case CD_CMD_FEED:
        case CD_CMD_EVAL:
            cd_router_forward(hdr[0], hdr[1]);
            break;
        case CD_CMD_CHECKPOINT:
        case CD_CMD_RESTORE:
        case CD_CMD_DROP:
            cd_router_named(hdr[0], hdr[1]);
            break;
        case CD_CMD_INFO:
            cd_router_info(hdr[1]);
            break;
        case CD_CMD_QUIT:
            cd_discard(cd_in, hdr[1]);
            cd_drop_all();
            cd_reply(0, NULL, 0, NULL, 0);
            cd_reap();
            return 0;
        default:
            if (cd_discard(cd_in, hdr[1]) < 0)
            {
                cd_die_io();
            }
            cd_reply_error("unknown command %u", hdr[0]);
            break;
        }
    }
    cd_drop_all();
    cd_reap();
    return 0;
}
