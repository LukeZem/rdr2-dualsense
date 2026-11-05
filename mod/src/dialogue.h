// Dialogue haptics (Experimental): every spoken line felt as the speaker's voice, from the exact recording the game
// plays - nothing is guessed from sound:
//  - Gameplay: the game's speech requests say which recording a ped is saying (voice + line + variation); it is
//    decoded from the game's archives (awc) and becomes a haptic voice from the speaker's side (speech_haptic).
//  - Cutscenes: the game's sound pool says which cutscene dialogue file plays and where (gamemem); its audible stem
//    is decoded the same way and played on the game's own clock.
// Off by default (like "speech to vibrations" in other games, an accessibility option).
// Decoding and the cutscene clock run on our own thread; the script thread only hands over who is near and talking.
#pragma once

#include "awc.h"
#include "common.h"

#include <condition_variable>
#include <deque>
#include <map>
#include <memory>
#include <set>
#include <thread>
#include <unordered_set>

namespace dsr2 {

class AudioEngine;

class Dialogue {
public:
    struct Talker {
        const void* obj = nullptr;   // the ped's game object (script handle base address)
        int ped = 0;
        float pan = 0, dist = 0;
        bool player = false;
    };
    void configure();                                        // settings: any time
    void start(const fs::path& game_dir, AudioEngine* audio); // once, in game
    void stop();
    bool speech_wanted() const { return speech_gain_ > 0 && !cutscenes_only_ && running_; }
    // script thread, every frame: who is near (only read when speech vibration is on). native_player_line = the
    // game's _GET_LAST_PLAYED_SPEECH_FOR_PED for the player, to check the memory layout against the game itself.
    void game_tick(const std::vector<Talker>& talkers, uint32_t native_player_line);

private:
    void worker();
    void cutscene_poll(double now);
    void cutscene_scan(double now);
    void prepare_cutscene(const awc::Entry& e);
    void stop_cutscene();
    void prepare_line(uint64_t key, const awc::Entry& e, double t_start, float gl, float gr);

    struct LineJob { uint64_t key; awc::Entry e; double t_start; float gl, gr; };
    struct Cut {
        awc::Entry entry;
        std::vector<uint32_t> ids;                   // channel ids in the file (decoder order)
        std::map<int, std::shared_ptr<const std::vector<float>>> speech;   // per stem set: its dialogue as haptic
        bool decoded = false, failed = false;
    };
    struct StemSeen { uint64_t file = 0; uint32_t id = 0, ms = 0; double t = 0, advanced = -1; };

    AudioEngine* audio_ = nullptr;
    fs::path game_dir_;
    std::thread th_;
    std::atomic<bool> running_{false};
    std::atomic<float> speech_gain_{0.0f}, tv_s_{0.06f};
    std::atomic<bool> auto_delay_{true}, out_bluetooth_{false};
    std::atomic<bool> cutscenes_only_{false};
    std::string out_name_;                           // worker only
    std::atomic<bool> enabled_{true};

    std::mutex mu_;                                  // jobs between the script thread and the worker
    std::condition_variable cv_;
    std::deque<LineJob> line_jobs_;

    // worker-only state
    std::unordered_set<uint32_t> cut_ids_;           // every cutscene channel id
    std::vector<uint64_t> cut_bits_;                 // fast pre-filter on the low 20 bits
    std::map<uint64_t, Cut> cuts_;                   // by file offset (decoded cutscenes, the last few)
    std::map<uintptr_t, StemSeen> stems_;            // pool fields seen
    uint64_t playing_file_ = 0;
    int playing_set_ = -1;
    double play_t0_ = 0, scan_t_ = 0, last_adv_ = 0, t0_window_start_ = 0;
    bool tracks_on_ = false;

    // script-thread state (speech)
    // a line being said: its key, when it turned "playing", when its wave player's clock says it really started
    struct Said { uint64_t key; double t; bool seen; double start = -1; };
    // research probe (General.Probes=1): when does a line REALLY start? Each new line's speech sound and its children
    // (wave players) are dumped, then every changed u32 is logged for 4 s
    struct Probe {
        double t0 = 0;
        uint32_t sid = 0, voice = 0;
        uintptr_t addr[6] = {};               // sound, [+0xC0], [+0xC8], [+0xD0], [+0x08], [+0x10]
        std::vector<uint8_t> last[6];
    };
    std::map<uintptr_t, Probe> probes_;
    std::atomic<bool> probes_on_{false};
    void probe_start(uintptr_t sound, uint32_t sid, uint32_t voice, float dist, bool player, double now);
    void probe_tick(double now);
    std::map<uintptr_t, Said> said_;                 // playing requests by address
    int check_ok_ = 0, check_bad_ = 0;
    bool speech_layout_bad_ = false;
};

Dialogue& dialogue();

// the haptic signal of a voice (exposed for the self-test)
std::vector<float> speech_haptic(const std::vector<float>& voice48k);

}  // namespace dsr2
