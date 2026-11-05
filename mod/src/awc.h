// The game's audio files (AWC) inside its audio archives (x64/audio/sfx/*.rpf), read straight from disk.
// The archives' table of contents is encrypted, but the files themselves are stored plain, one after another: the
// index walks from one "ADAT" header to the next (file end = the furthest chunk end, next file 16-byte aligned) -
// no keys, no names, only headers are read (~1 s for all speech and cutscene archives). Checked against the real
// table of contents: every file found, nothing extra (tools/awc/walk_index.py).
//
// Streams: speech lines are single streams (chunk 0x76 = u32 samples, i32 loop, u16 rate, ..., at +32 the three
// Vorbis headers as u32 size + data; chunk 0x55 = 0x800-byte frames of u16-size-prefixed Vorbis packets).
// Cutscenes are one multi-channel stream (chunk 0x48 = u32 blocks, u32 block size, u32 channels, per channel
// 16 bytes: u32 id, u32 samples, i16 headroom, u16 rate, u8 codec; chunk 0x55 = blocks; each channel's Vorbis
// headers in chunk 0x7F of the stream named by the channel id). Every block restarts each channel's Vorbis stream
// with pre-roll packets; the block header per channel says how many samples to drop.
#pragma once

#include "common.h"

#include <atomic>
#include <string>
#include <unordered_map>
#include <vector>

namespace dsr2::awc {

enum Kind : uint8_t { Speech, Cutscene };

struct Entry {
    uint32_t id = 0;           // stream id (speech) or channel id (cutscene)
    uint16_t archive = 0;
    uint8_t kind = Speech;
    uint8_t stem = 0;          // cutscene: channel number in the file
    uint64_t file = 0;         // where the .awc starts in the archive
    uint32_t fmt_off = 0, fmt_size = 0, data_off = 0, data_size = 0;   // speech: chunk 0x76 / 0x55 (in the .awc)
    uint64_t fingerprint = 0;  // the .awc's header (stream + chunk tables), FNV-1a 64: names the file without its name
};

class Index {
public:
    // walks the archives; any thread (a background one: ~1 s); safe to call once
    void build(const fs::path& game_dir);
    bool ready() const { return ready_; }
    // all entries with this id (a line's id comes from the line's name: GREET_MALE_01 is in hundreds of voices)
    std::vector<Entry> find(uint32_t id, Kind kind) const;
    // the speaker's own recording of a line: the file whose fingerprint belongs to the voice (speech_voices.txt);
    // else the only file with the line (scripted conversations: one file per conversation); false = not sure
    bool find_line(uint32_t id, uint32_t voice, Entry& out) const;
    std::vector<Entry> all(Kind kind) const {
        std::vector<Entry> out;
        for (auto& e : entries_)
            if (e.kind == kind) out.push_back(e);
        return out;
    }
    fs::path archive_path(uint16_t a) const { return a < archives_.size() ? archives_[a] : fs::path(); }
    size_t size() const { return entries_.size(); }

private:
    void walk(uint16_t a, Kind kind);
    std::vector<fs::path> archives_;
    std::vector<Entry> entries_;     // sorted by (id, kind) once built
    std::unordered_map<uint32_t, std::vector<uint64_t>> voices_;   // voice hash -> its files' fingerprints
    std::atomic<bool> ready_{false};
};

Index& index();

// speech line: mono samples at `rate`
bool decode_line(const Index& ix, const Entry& e, std::vector<float>& out, int& rate);
// cutscene file: every channel (decoder order), with its channel id
bool decode_cutscene(const Index& ix, const Entry& e, std::vector<std::vector<float>>& chans, std::vector<uint32_t>& ids,
                     int& rate);

// The stream id of a spoken line: the game keeps the context hash with joaat's last mixing step not done yet
// ("partial"); the recording is joaat continued with "_%02d" % variation, finished, low 29 bits.
uint32_t line_stream_id(uint32_t partial, uint32_t variation);
uint32_t joaat_finish(uint32_t h);

}  // namespace dsr2::awc
