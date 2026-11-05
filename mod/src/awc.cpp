#include "awc.h"

#include "log.h"

#include <map>

#define STB_VORBIS_NO_STDIO
#define STB_VORBIS_NO_INTEGER_CONVERSION
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-value"
#pragma GCC diagnostic ignored "-Wunused-function"
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#pragma GCC diagnostic ignored "-Wmaybe-uninitialized"
#pragma GCC diagnostic ignored "-Wsign-compare"
#endif
#include "../third_party/stb/stb_vorbis.c"
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

namespace dsr2::awc {

namespace {

// archives with spoken lines (townsfolk, story characters, scripted conversations, random events) and cutscenes;
// not S_VOFX (grunts, breaths) or ANIMALS_* (animal voices go through the speech system too)
const char* const kSpeechArchives[] = {"PEDS_00", "PEDS_01", "PEDS_02", "PEDS_03", "PEDS_04", "PEDS_05", "PEDS_06",
                                       "PEDS_07", "PEDS_08", "PEDS_09", "PEDS_10", "S_MISC", "S_RE", "SS_AM", "SS_NZ"};
const char* const kCutsceneArchive = "CUTSCENE_MASTERED_ONLY";

class File {
public:
    explicit File(const fs::path& p) {
        h_ = CreateFileW(p.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                         OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        LARGE_INTEGER s{};
        if (ok() && GetFileSizeEx(h_, &s)) size_ = uint64_t(s.QuadPart);
    }
    ~File() { if (ok()) CloseHandle(h_); }
    File(const File&) = delete;
    File& operator=(const File&) = delete;
    bool ok() const { return h_ != INVALID_HANDLE_VALUE; }
    uint64_t size() const { return size_; }
    // reads up to n bytes at `off`; returns how many
    size_t read(uint64_t off, void* dst, size_t n) const {
        size_t got = 0;
        while (got < n) {
            OVERLAPPED ov{};
            ov.Offset = DWORD((off + got) & 0xFFFFFFFF);
            ov.OffsetHigh = DWORD((off + got) >> 32);
            DWORD r = 0, want = DWORD(std::min<size_t>(n - got, 1 << 24));
            if (!ReadFile(h_, static_cast<uint8_t*>(dst) + got, want, &r, &ov) || r == 0) break;
            got += r;
        }
        return got;
    }
    bool read_exact(uint64_t off, std::vector<uint8_t>& out, size_t n) const {
        out.resize(n);
        return read(off, out.data(), n) == n;
    }

private:
    HANDLE h_ = INVALID_HANDLE_VALUE;
    uint64_t size_ = 0;
};

template <class T> T rd(const uint8_t* p) { T v; std::memcpy(&v, p, sizeof v); return v; }

struct Chunk { uint8_t tag; uint32_t off, size; };
struct Stream { uint32_t id; std::vector<Chunk> chunks; };

// parses an AWC header (the bytes from the start of the file, at least the header size); false = not an AWC
bool parse_header(const std::vector<uint8_t>& h, std::vector<Stream>& out, uint64_t* file_end) {
    if (h.size() < 16 || std::memcmp(h.data(), "ADAT", 4)) return false;
    uint16_t flags = rd<uint16_t>(&h[6]);
    uint32_t count = rd<uint32_t>(&h[8]), hsize = rd<uint32_t>(&h[12]);
    if (count == 0 || count > 100000) return false;
    size_t off = 16 + ((flags & 1) ? 2 * size_t(count) : 0);
    if (off + 4 * size_t(count) > h.size()) return false;
    std::vector<uint32_t> infos(count);
    for (uint32_t i = 0; i < count; ++i) infos[i] = rd<uint32_t>(&h[off + 4 * i]);
    off += 4 * size_t(count);
    uint64_t end = hsize;
    out.clear();
    out.reserve(count);
    for (uint32_t info : infos) {
        Stream s{info & 0x1FFFFFFF, {}};
        for (uint32_t c = 0; c < (info >> 29); ++c) {
            if (off + 8 > h.size()) return false;
            uint64_t v = rd<uint64_t>(&h[off]);
            off += 8;
            Chunk ch{uint8_t(v >> 56), uint32_t(v & 0x0FFFFFFF), uint32_t((v >> 28) & 0x0FFFFFFF)};
            end = std::max<uint64_t>(end, uint64_t(ch.off) + ch.size);
            s.chunks.push_back(ch);
        }
        out.push_back(std::move(s));
    }
    if (end < 32 || end > (1ull << 31)) return false;
    if (file_end) *file_end = end;
    return true;
}

const Chunk* find_chunk(const Stream& s, uint8_t tag) {
    for (auto& c : s.chunks)
        if (c.tag == tag) return &c;
    return nullptr;
}

// FNV-1a 64 of the stream-info table and the chunk table: the same in tools/awc/build_voice_table.py
uint64_t header_fingerprint(const std::vector<uint8_t>& h) {
    uint16_t flags = rd<uint16_t>(&h[6]);
    uint32_t count = rd<uint32_t>(&h[8]);
    size_t off = 16 + ((flags & 1) ? 2 * size_t(count) : 0), chunks = 0;
    for (uint32_t i = 0; i < count && off + 4 * (i + 1) <= h.size(); ++i) chunks += rd<uint32_t>(&h[off + 4 * i]) >> 29;
    size_t end = std::min(h.size(), off + 4 * size_t(count) + 8 * chunks);
    uint64_t x = 0xCBF29CE484222325ull;
    for (size_t i = off; i < end; ++i) {
        x ^= h[i];
        x *= 0x100000001B3ull;
    }
    return x;
}

// reads an AWC's header from the archive (header size from the first 16 bytes)
bool read_header(const File& f, uint64_t file, std::vector<uint8_t>& h) {
    if (!f.read_exact(file, h, 16) || std::memcmp(h.data(), "ADAT", 4)) return false;
    uint32_t count = rd<uint32_t>(&h[8]), hsize = rd<uint32_t>(&h[12]);
    size_t n = std::max<size_t>(hsize, 16 + 6 * size_t(count) + 64 * size_t(count));   // hsize can be 0 in odd files
    n = std::min<size_t>(n, 64u << 20);
    if (!f.read_exact(file, h, n)) {
        h.resize(f.read(file, h.data(), n));
        return h.size() >= 16;
    }
    return true;
}

// ---------------------------------------------------------------- Ogg wrapping for stb_vorbis
uint32_t g_crc[256];
void crc_init() {
    for (uint32_t i = 0; i < 256; ++i) {
        uint32_t r = i << 24;
        for (int k = 0; k < 8; ++k) r = (r & 0x80000000u) ? (r << 1) ^ 0x04C11DB7u : r << 1;
        g_crc[i] = r;
    }
}

void ogg_page(std::vector<uint8_t>& o, const std::vector<std::pair<const uint8_t*, size_t>>& pk, int64_t granule,
              uint32_t seq, uint8_t flags) {
    std::vector<uint8_t> lace;
    for (auto& [p, n] : pk) {
        for (size_t k = n; ; k -= 255) {
            if (k < 255) { lace.push_back(uint8_t(k)); break; }
            lace.push_back(255);
        }
    }
    size_t start = o.size();
    const uint8_t head[] = {'O', 'g', 'g', 'S', 0, flags};
    o.insert(o.end(), head, head + 6);
    for (int i = 0; i < 8; ++i) o.push_back(uint8_t(uint64_t(granule) >> (8 * i)));
    const uint32_t serial = 0x5EED;
    for (uint32_t v : {serial, seq, 0u})
        for (int i = 0; i < 4; ++i) o.push_back(uint8_t(v >> (8 * i)));
    o.push_back(uint8_t(lace.size()));
    o.insert(o.end(), lace.begin(), lace.end());
    for (auto& [p, n] : pk) o.insert(o.end(), p, p + n);
    uint32_t c = 0;
    for (size_t i = start; i < o.size(); ++i) c = (c << 8) ^ g_crc[((c >> 24) ^ o[i]) & 0xFF];
    std::memcpy(&o[start + 22], &c, 4);
}

// an Ogg Vorbis stream from three headers and the packets of 0x800-byte frames; pages hold whole frames
struct Packets {
    std::vector<std::pair<const uint8_t*, size_t>> list;
    std::vector<size_t> frame_end;   // index into list where each frame ends
};

void split_frames(const uint8_t* d, size_t size, Packets& out) {
    for (size_t f = 0; f + 0x800 <= size + 0x7FF && f < size; f += 0x800) {
        size_t lim = std::min<size_t>(0x800, size - f);
        size_t i = 0;
        while (i + 2 <= lim) {
            uint16_t s = rd<uint16_t>(d + f + i);
            if (s == 0 || i + 2 + s > lim) break;
            out.list.push_back({d + f + i + 2, s});
            i += 2 + s;
        }
        out.frame_end.push_back(out.list.size());
    }
}

// decodes; `last_granule` (the sample count) goes on the last page
bool vorbis_decode(const std::vector<std::vector<uint8_t>>& heads, const Packets& pk, int64_t last_granule,
                   std::vector<float>& out, int& rate) {
    static std::once_flag once;
    std::call_once(once, crc_init);
    if (heads.size() != 3 || pk.list.empty()) return false;
    std::vector<uint8_t> ogg;
    ogg.reserve(pk.list.size() * 300 + 8192);
    uint32_t seq = 0;
    ogg_page(ogg, {{heads[0].data(), heads[0].size()}}, 0, seq++, 2);
    ogg_page(ogg, {{heads[1].data(), heads[1].size()}, {heads[2].data(), heads[2].size()}}, 0, seq++, 0);
    size_t from = 0;
    for (size_t f = 0; f < pk.frame_end.size(); ++f) {
        size_t to = pk.frame_end[f];
        bool last = f + 1 == pk.frame_end.size();
        // a page holds at most 255 lacing values: split big frames
        while (from < to) {
            std::vector<std::pair<const uint8_t*, size_t>> page;
            size_t lacing = 0, k = from;
            for (; k < to; ++k) {
                size_t l = pk.list[k].second / 255 + 1;
                if (lacing + l > 255) break;
                lacing += l;
                page.push_back(pk.list[k]);
            }
            if (page.empty()) return false;
            from = k;
            bool end = last && from == to;
            ogg_page(ogg, page, end ? last_granule : -1, seq++, end ? 4 : 0);
        }
    }
    int err = 0;
    stb_vorbis* v = stb_vorbis_open_memory(ogg.data(), int(ogg.size()), &err, nullptr);
    if (!v) {
        LOGD("vorbis: open failed, error %d (%zu packets, first %zu bytes)", err, pk.list.size(), pk.list[0].second);
        return false;
    }
    stb_vorbis_info info = stb_vorbis_get_info(v);
    rate = int(info.sample_rate);
    out.clear();
    float** pcm = nullptr;
    int ch = 0, n;
    int frames = 0;
    // 0 means the end of the stream - or a frame with nothing to output yet (a stream that starts on a long packet
    // followed by short ones): only stop after a few zeros in a row
    for (int zeros = 0; zeros < 4;) {
        n = stb_vorbis_get_frame_float(v, &ch, &pcm);
        if (n <= 0) { ++zeros; continue; }
        zeros = 0;
        out.insert(out.end(), pcm[0], pcm[0] + n);
        ++frames;
    }
    int e = stb_vorbis_get_error(v);
    if (e && e != VORBIS__no_error && out.empty())
        LOGD("vorbis: decode stopped after %d frames, error %d (%zu packets, sizes %zu %zu %zu)", frames, e, pk.list.size(),
             pk.list[0].second, pk.list.size() > 1 ? pk.list[1].second : 0, pk.list.size() > 2 ? pk.list[2].second : 0);
    stb_vorbis_close(v);
    return !out.empty();
}

bool three_headers(const uint8_t* p, size_t size, std::vector<std::vector<uint8_t>>& heads) {
    heads.clear();
    size_t i = 0;
    for (int k = 0; k < 3; ++k) {
        if (i + 4 > size) return false;
        uint32_t n = rd<uint32_t>(p + i);
        if (n == 0 || i + 4 + n > size) return false;
        heads.emplace_back(p + i + 4, p + i + 4 + n);
        i += 4 + n;
    }
    return heads[0].size() > 7 && heads[0][0] == 1 && !std::memcmp(&heads[0][1], "vorbis", 6);
}

}  // namespace

uint32_t joaat_finish(uint32_t h) {
    h += h << 3;
    h ^= h >> 11;
    h += h << 15;
    return h;
}

uint32_t line_stream_id(uint32_t partial, uint32_t variation) {
    char sfx[16];
    snprintf(sfx, sizeof sfx, "_%02u", variation);
    uint32_t h = partial;
    for (const char* c = sfx; *c; ++c) {
        h += uint8_t(*c);
        h += h << 10;
        h ^= h >> 6;
    }
    return joaat_finish(h) & 0x1FFFFFFF;
}

Index& index() {
    static Index ix;
    return ix;
}

void Index::walk(uint16_t a, Kind kind) {
    File f(archives_[a]);
    if (!f.ok()) {
        LOGW("audio index: cannot open %s", archives_[a].filename().string().c_str());
        return;
    }
    std::vector<uint8_t> h;
    if (!f.read_exact(0, h, 16) || rd<uint32_t>(h.data()) != 0x52504638) return;   // "8FPR"
    int32_t count = rd<int32_t>(&h[4]);
    uint64_t pos = 16 + 0x100 + uint64_t(std::max(0, count)) * 24;
    std::vector<Stream> streams;
    std::vector<uint8_t> blk;
    size_t files = 0;
    while (pos + 16 <= f.size()) {
        uint64_t end = 0;
        if (read_header(f, pos, h) && parse_header(h, streams, &end)) {
            ++files;
            const uint64_t fp = header_fingerprint(h);
            for (auto& s : streams) {
                Entry e;
                e.id = s.id;
                e.archive = a;
                e.kind = kind;
                e.file = pos;
                e.fingerprint = fp;
                if (kind == Speech) {
                    const Chunk* fm = find_chunk(s, 0x76);
                    const Chunk* da = find_chunk(s, 0x55);
                    if (!fm || !da) continue;
                    e.fmt_off = fm->off; e.fmt_size = fm->size; e.data_off = da->off; e.data_size = da->size;
                    entries_.push_back(e);
                } else if (find_chunk(s, 0x7F)) {
                    entries_.push_back(e);
                }
            }
            pos = (pos + end + 15) & ~uint64_t(15);
            continue;
        }
        // not a header here: search forward for the next 16-byte aligned "ADAT"
        uint64_t found = 0;
        bool eof = false;
        uint64_t p = pos + 16;
        blk.resize(1 << 20);
        while (!found && !eof) {
            size_t n = f.read(p, blk.data(), blk.size());
            if (n < 16) { eof = true; break; }
            for (size_t i = (16 - p % 16) % 16; i + 4 <= n; i += 16)
                if (!std::memcmp(&blk[i], "ADAT", 4)) { found = p + i; break; }
            if (n < blk.size()) eof = !found;
            p += n - (n % 16);
        }
        if (!found) break;
        pos = found;
    }
    LOGD("audio index: %s %zu files", archives_[a].filename().string().c_str(), files);
}

void Index::build(const fs::path& game_dir) {
    if (ready_) return;
    double t0 = now_s();
    fs::path sfx = game_dir / "x64" / "audio" / "sfx";
    archives_.clear();
    entries_.clear();
    for (const char* n : kSpeechArchives) archives_.push_back(sfx / (std::string(n) + ".rpf"));
    archives_.push_back(sfx / (std::string(kCutsceneArchive) + ".rpf"));
    for (size_t a = 0; a + 1 < archives_.size(); ++a) walk(uint16_t(a), Speech);
    // which files are whose voice (built with names by tools/awc/build_voice_table.py; metadata only)
    voices_.clear();
    if (FILE* vf = _wfopen((data_dir() / "speech_voices.txt").c_str(), L"r")) {
        char line[1024];
        while (fgets(line, sizeof line, vf)) {
            if (line[0] == '#') continue;
            char* p = line;
            uint64_t fp = strtoull(p, &p, 16);
            for (;;) {
                char* q = p;
                unsigned long v = strtoul(p, &q, 16);
                if (q == p) break;
                voices_[uint32_t(v)].push_back(fp);
                p = q;
            }
        }
        fclose(vf);
    }
    if (voices_.empty()) LOGW("audio index: speech_voices.txt missing - spoken lines only where the line is in one file");
    walk(uint16_t(archives_.size() - 1), Cutscene);
    std::sort(entries_.begin(), entries_.end(),
              [](const Entry& x, const Entry& y) { return x.id != y.id ? x.id < y.id : x.kind < y.kind; });
    size_t cuts = std::count_if(entries_.begin(), entries_.end(), [](const Entry& e) { return e.kind == Cutscene; });
    LOGI("audio index: %zu spoken lines, %zu cutscene stems, %zu voices in %.2f s", entries_.size() - cuts, cuts, voices_.size(),
         now_s() - t0);
    ready_ = true;
}

bool Index::find_line(uint32_t id, uint32_t voice, Entry& out) const {
    std::vector<Entry> c = find(id, Speech);
    if (c.empty()) return false;
    auto v = voices_.find(voice);
    if (v != voices_.end())
        for (const Entry& e : c)
            if (std::find(v->second.begin(), v->second.end(), e.fingerprint) != v->second.end()) {
                out = e;
                return true;
            }
    if (c.size() == 1) {
        out = c[0];
        return true;
    }
    return false;
}

std::vector<Entry> Index::find(uint32_t id, Kind kind) const {
    std::vector<Entry> out;
    if (!ready_) return out;
    auto it = std::lower_bound(entries_.begin(), entries_.end(), id, [](const Entry& e, uint32_t v) { return e.id < v; });
    for (; it != entries_.end() && it->id == id; ++it)
        if (it->kind == kind) out.push_back(*it);
    return out;
}

bool decode_line(const Index& ix, const Entry& e, std::vector<float>& out, int& rate) {
    File f(ix.archive_path(e.archive));
    std::vector<uint8_t> fmt, data;
    if (!f.ok() || e.fmt_size < 40 || !f.read_exact(e.file + e.fmt_off, fmt, e.fmt_size) ||
        !f.read_exact(e.file + e.data_off, data, e.data_size))
        return false;
    uint32_t samples = rd<uint32_t>(&fmt[0]);
    std::vector<std::vector<uint8_t>> heads;
    if (!three_headers(&fmt[32], fmt.size() - 32, heads)) return false;
    Packets pk;
    split_frames(data.data(), data.size(), pk);
    if (!vorbis_decode(heads, pk, samples, out, rate)) return false;
    if (out.size() > samples) out.resize(samples);
    return true;
}

bool decode_cutscene(const Index& ix, const Entry& e, std::vector<std::vector<float>>& chans, std::vector<uint32_t>& ids,
                     int& rate) {
    File f(ix.archive_path(e.archive));
    std::vector<uint8_t> h;
    std::vector<Stream> streams;
    if (!f.ok() || !read_header(f, e.file, h) || !parse_header(h, streams, nullptr)) return false;
    const Stream* main = nullptr;
    std::map<uint32_t, const Stream*> by_id;
    for (auto& s : streams) {
        by_id[s.id] = &s;
        if (s.id == 0) main = &s;
    }
    const Chunk* sf = main ? find_chunk(*main, 0x48) : nullptr;
    const Chunk* sd = main ? find_chunk(*main, 0x55) : nullptr;
    if (!sf || !sd) return false;
    std::vector<uint8_t> fmt, data;
    if (!f.read_exact(e.file + sf->off, fmt, sf->size) || fmt.size() < 12) return false;
    uint32_t blocks = rd<uint32_t>(&fmt[0]), bsize = rd<uint32_t>(&fmt[4]), nch = rd<uint32_t>(&fmt[8]);
    if (!nch || nch > 16 || fmt.size() < 12 + 16 * nch || !bsize) return false;
    std::vector<uint32_t> total(nch);
    std::vector<std::vector<std::vector<uint8_t>>> heads(nch);
    ids.assign(nch, 0);
    rate = 48000;
    for (uint32_t c = 0; c < nch; ++c) {
        ids[c] = rd<uint32_t>(&fmt[12 + 16 * c]);
        total[c] = rd<uint32_t>(&fmt[12 + 16 * c + 4]);
        rate = rd<uint16_t>(&fmt[12 + 16 * c + 10]);
        auto it = by_id.find(ids[c]);
        const Chunk* vh = it != by_id.end() ? find_chunk(*it->second, 0x7F) : nullptr;
        std::vector<uint8_t> raw;
        if (!vh || !f.read_exact(e.file + vh->off, raw, vh->size) || !three_headers(raw.data(), raw.size(), heads[c]))
            return false;
    }
    if (!f.read_exact(e.file + sd->off, data, sd->size)) return false;
    chans.assign(nch, {});
    for (uint32_t b = 0; b < blocks; ++b) {
        size_t bo = size_t(b) * bsize;
        if (bo + 0x18 * nch > data.size()) break;
        std::vector<uint32_t> frames(nch), skip(nch), count(nch);
        for (uint32_t c = 0; c < nch; ++c) {
            frames[c] = rd<uint32_t>(&data[bo + 0x18 * c + 4]);
            skip[c] = rd<uint32_t>(&data[bo + 0x18 * c + 8]);
            count[c] = rd<uint32_t>(&data[bo + 0x18 * c + 12]);
        }
        size_t p = bo + 0x18 * nch;
        for (uint32_t c = 0; c < nch; ++c) p += 4 * size_t(frames[c]);     // seek tables
        p = bo + ((p - bo + 0x7FF) & ~size_t(0x7FF));
        for (uint32_t c = 0; c < nch; ++c) {
            size_t len = size_t(frames[c]) * 0x800;
            if (p + len > data.size()) { LOGD("cutscene decode: block %u ch %u past the data", b, c); return false; }
            Packets pk;
            split_frames(&data[p], len, pk);
            p += len;
            std::vector<float> x;
            int r = 0;
            // the block decodes to `count` samples (the last page's granule says so, like libvorbis); its first
            // `skip` repeat the end of the previous block (pre-roll)
            if (!vorbis_decode(heads[c], pk, count[c], x, r)) {
                if (pk.list.empty()) continue;            // an empty block for this channel
                LOGD("cutscene decode: block %u ch %u: vorbis failed (%zu packets)", b, c, pk.list.size());
                return false;
            }
            if (getenv("DSR2_AWC_DEBUG"))
                LOGD("block %u ch %u: decoded %zu, count %u, skip %u", b, c, x.size(), count[c], skip[c]);
            // stb_vorbis does not trim to the granule: more than `count` = extra at the END (post-roll packets);
            // less = it spent the block's first packet on priming: up to half a long window (1024) is missing at the
            // START, anything beyond that at the end.
            // Checked against two loopback recordings of the game (constant offset across every block).
            if (x.size() > count[c]) x.resize(count[c]);
            else if (x.size() < count[c]) {
                size_t miss = count[c] - x.size(), front = std::min<size_t>(miss, 1024);
                x.insert(x.begin(), front, 0.0f);
                x.insert(x.end(), miss - front, 0.0f);
            }
            chans[c].insert(chans[c].end(), x.begin() + std::min<long>(long(skip[c]), long(x.size())), x.end());
        }
    }
    for (uint32_t c = 0; c < nch; ++c)
        if (chans[c].size() > total[c]) chans[c].resize(total[c]);
    return true;
}

}  // namespace dsr2::awc
