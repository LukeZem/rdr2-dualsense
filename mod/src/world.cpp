#include "world.h"
#include "settings_ui.h"

#include "config.h"
#include "core.h"
#include "dialogue.h"
#include "game_files.h"
#include "log.h"
#include "input.h"
#include "natives.h"

namespace dsr2 {

World& world() {
    static World w;
    return w;
}

static float atomic_take(std::atomic<float>& a) { return a.exchange(0.0f); }
static void atomic_add(std::atomic<float>& a, float v) {
    float cur = a.load();
    while (!a.compare_exchange_weak(cur, cur + v)) {}
}

void World::add_gyro(float yaw, float pitch) {
    atomic_add(gyro_yaw_, yaw);
    atomic_add(gyro_pitch_, pitch);
}

GameSnapshot World::snapshot() {
    std::lock_guard<std::mutex> l(mu_);
    return snap_;
}

std::vector<WorldEvent> World::take_events() {
    std::lock_guard<std::mutex> l(mu_);
    std::vector<WorldEvent> out;
    out.swap(events_);
    return out;
}

// RAGE headings: 0 = north, counter-clockwise. Pan +1 = source on the right of the camera.
float World::frame_time() const { return nat::GET_FRAME_TIME(); }

// Speech request probe (debug log only, read only). The chain comes from disassembling the game's speech natives
// (_GET_LAST_PLAYED_SPEECH_FOR_PED, IS_ANY/AMBIENT/SCRIPTED_SPEECH_PLAYING) in this game build (image size 0x7397600):
//   ped object +0x9C (& 0x1FFFF) - u32 [exe+0x39ECE40] = index into the table at [exe+0x39ECE48], 0x148 bytes each
//   entry +0x30 -> object A (low bit = flag); A+0x218 & 2; [A+0x98] +0x4438 -> speech manager M
//     M+0x78 = array of speech requests, M+0x80 = their count (u16); request R: +0x214 type (1 ambient, 2 scripted,
//     4 ?), +0x234 state (5 = playing), +0x1D8 the playing sound (object with a vtable)
//   entry +0xB0 -> object B; B+0x218 & 2; B+0x48C0+0x388 = the last line's context hash *before* joaat's final mixing
//     (the native finishes it: h *= 9, h ^= h >> 11, h *= 0x8001) - why searching memory for the final hash failed
// Dumps each request when it appears / changes state, and its sound twice (to spot a play-position field), to find
// the fields that name the exact recording (variation, voice) and its clock. Reads go through ReadProcessMemory,
// which fails instead of crashing.
static bool peek(const void* a, void* out, size_t n) {
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), a, out, n, &got) && got == n;
}
template <class T> static bool rd(uintptr_t a, T& v) { return a && peek(reinterpret_cast<const void*>(a), &v, sizeof v); }

static uintptr_t game_exe() {
    static uintptr_t b = [] {
        auto m = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
        auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(m);
        auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(m + dos->e_lfanew);
        if (nt->OptionalHeader.SizeOfImage != 0x7397600) {
            LOGD("speechreq: different game build (image size 0x%X) - probe off", unsigned(nt->OptionalHeader.SizeOfImage));
            return uintptr_t(0);
        }
        return m;
    }();
    return b;
}

static void hexdump(const char* tag, int ped, uintptr_t at, size_t n) {
    static uint8_t buf[0x400];
    n = std::min(n, sizeof buf);
    if (!peek(reinterpret_cast<const void*>(at), buf, n)) { LOGD("%s: ped %d %llX unreadable", tag, ped, (unsigned long long)at); return; }
    for (size_t o = 0; o < n; o += 0x100) {
        char hex[0x100 * 2 + 1];
        size_t m = std::min<size_t>(0x100, n - o);
        for (size_t i = 0; i < m; ++i) snprintf(hex + i * 2, 3, "%02X", buf[o + i]);
        LOGD("%s: ped %d %llX +%03zX %s", tag, ped, (unsigned long long)at, o, hex);
    }
}

void World::speech_req(int ped, double now) {
    uintptr_t g = game_exe();
    auto* po = shv_getScriptHandleBaseAddress(ped);
    if (!g || !po) return;
    uint32_t idx = 0, lo = 0;
    uintptr_t tab = 0;
    if (!rd(uintptr_t(po) + 0x9C, idx) || !rd(g + 0x39ECE40, lo) || !rd(g + 0x39ECE48, tab) || !tab) return;
    uintptr_t entry = tab + uintptr_t(uint32_t((idx & 0x1FFFF) - lo)) * 0x148;
    uintptr_t a = 0, x = 0, mgr = 0, b = 0, arr = 0;
    uint8_t fa = 0, fb = 0;
    uint16_t cnt = 0;
    uint32_t partial = 0;
    rd(entry + 0xB0, b);
    b &= ~uintptr_t(1);
    if (b && rd(b + 0x218, fb) && (fb & 2)) rd(b + 0x48C0 + 0x388, partial);
    if (!rd(entry + 0x30, a)) return;
    a &= ~uintptr_t(1);
    if (!a || !rd(a + 0x218, fa) || !(fa & 2) || !rd(a + 0x98, x) || !rd(x + 0x4438, mgr) || !mgr) return;
    if (!rd(mgr + 0x80, cnt) || !rd(mgr + 0x78, arr) || !arr || cnt > 64) return;
    for (int i = 0; i < cnt; ++i) {
        uintptr_t r = 0;
        uint32_t type = 0, state = 0;
        uintptr_t snd = 0;
        if (!rd(arr + 8 * i, r) || !r || !rd(r + 0x214, type) || !rd(r + 0x234, state)) continue;
        rd(r + 0x1D8, snd);
        auto it = reqs_.find(r);
        bool fresh = it == reqs_.end();
        Req& q = reqs_[r];
        q.seen = now;
        if (fresh || q.state != state || q.type != type) {
            uintptr_t vt = 0;
            if (snd) rd(snd, vt);
            LOGD("speechreq: ped %d req %llX%s type %u state %u (was %d) sound %llX vt %llX partial %08X mgr %llX B %llX", ped,
                 (unsigned long long)r, fresh ? " new" : "", type, state, fresh ? -1 : int(q.state), (unsigned long long)snd,
                 (unsigned long long)(vt ? vt - g : 0), partial, (unsigned long long)mgr, (unsigned long long)b);
            hexdump("speechreq-r", ped, r, 0x300);
            if (fresh && b) hexdump("speechreq-b", ped, b + 0x48C0 + 0x300, 0x100);
            if (state == 5 && snd) {
                hexdump("speechreq-s0", ped, snd, 0x200);
                q.snd = snd;
                q.snd_t = now;
            }
            q.state = state;
            q.type = type;
        }
        if (q.snd && q.snd_t > 0 && now - q.snd_t >= 0.5) {   // the same sound half a second later
            hexdump("speechreq-s1", ped, q.snd, 0x200);
            q.snd_t = -1;
        }
    }
}

// Anim scene probe (debug log only, read only): cutscenes are anim scenes, and their clock is what the cutscene
// audio follows. Scene handles are not reachable from the player (AUDIO_GET_ENTITY_ANIM_SCENE gave -1), so list
// them from the game's scene map (found by disassembling _GET_ANIM_SCENE_TIME): [exe+0x5BD41B8] -> +0x08 buckets,
// +0x10 bucket count; node = {u32 handle, +0x08 scene object, +0x10 next}; the scene's time is the float at +0x180.
void World::scene_probe(int me, double now) {
    using namespace nat;
    if (now - scene_poll_t_ < 0.25) return;
    scene_poll_t_ = now;
    uintptr_t g = game_exe(), m = 0, bk = 0;
    uint32_t nb = 0;
    if (!g || !rd(g + 0x5BD41B8, m) || !rd(m + 8, bk) || !rd(m + 0x10, nb) || !bk || !nb || nb > 0x10000) return;
    std::map<int, Scene> next;
    for (uint32_t i = 0; i < nb; ++i) {
        uintptr_t n = 0;
        rd(bk + 8 * uintptr_t(i), n);
        for (int guard = 0; n && guard < 64; ++guard) {
            uint32_t key = 0;
            uintptr_t obj = 0, nx = 0;
            rd(n, key);
            rd(n + 8, obj);
            rd(n + 0x10, nx);
            if (obj) next[int(key)].obj = obj;
            n = nx;
        }
    }
    for (auto& [h, sc] : next) {
        auto it = scenes_.find(h);
        bool fresh = it == scenes_.end();
        if (!fresh) sc.logged = it->second.logged;
        bool run = IS_ANIM_SCENE_RUNNING(h), arthur = IS_ENTITY_PLAYING_ANIM_SCENE(me, h);
        float t = GET_ANIM_SCENE_TIME(h), raw = 0;
        rd(sc.obj + 0x180, raw);
        if (fresh)
            LOGD("scene: new %d obj %llX dict %08X duration %.3f running %d arthur %d", h, (unsigned long long)sc.obj,
                 GET_ANIM_SCENE_DICT(h), GET_ANIM_SCENE_DURATION(h), int(run), int(arthur));
        if (run && (arthur || now - sc.logged >= 1.0)) {
            LOGD("scene: %d t %.3f raw %.3f phase %.4f rate %.2f arthur %d", h, t, raw, GET_ANIM_SCENE_PHASE(h),
                 GET_ANIM_SCENE_RATE(h), int(arthur));
            sc.logged = now;
        }
    }
    for (auto& [h, sc] : scenes_)
        if (!next.count(h)) LOGD("scene: gone %d", h);
    scenes_.swap(next);
}

void World::speech_req_prune(double now) {
    for (auto it = reqs_.begin(); it != reqs_.end();)
        if (now - it->second.seen > 0.2) {
            LOGD("speechreq: req %llX gone", (unsigned long long)it->first);
            it = reqs_.erase(it);
        } else {
            ++it;
        }
}

// Speech probe (debug log only, read only): logs every line a ped (or Arthur) starts and stops saying - the
// line hash the game reports, the ped's model, where it stands - to find out how gameplay dialogue maps to the
// speech files (x64/audio/sfx/PEDS_*, S_*, SS_*: one stream per line, id = joaat("<CONTEXT>_<NN>") & 0x1FFFFFFF).
void World::speech_probe(int me, const int* peds, int n, float px, float py, float pz, float cam, double now) {
    using namespace nat;
    using shv::Vector3;
    bool convo = IS_ANY_CONVERSATION_PLAYING();
    if (convo != convo_) {
        LOGD("speech: conversation %s", convo ? "started" : "ended");
        convo_ = convo;
    }
    std::map<int, Talk> next;
    auto look = [&](int p, float d, float pan) {
        Talk t;
        auto it = talk_.find(p);
        if (it != talk_.end()) t = it->second;
        bool on = IS_ANY_SPEECH_PLAYING(p);
        uint32_t last = GET_LAST_PLAYED_SPEECH_FOR_PED(p);
        if (on && !t.on) {
            LOGD("speech: start ped %d model %08X line %08X (was %08X) ambient %d dist %.1f pan %+.2f%s", p,
                 GET_ENTITY_MODEL(p), last, t.last, int(IS_AMBIENT_SPEECH_PLAYING(p)), d, pan, p == me ? " (player)" : "");
            t.t0 = now;
        } else if (on && last != t.last) {
            LOGD("speech: ped %d line now %08X (was %08X), %.0f ms after start", p, last, t.last, (now - t.t0) * 1000);
        } else if (!on && t.on) {
            LOGD("speech: end ped %d line %08X after %.0f ms", p, last, (now - t.t0) * 1000);
        }
        t.on = on;
        t.last = last;
        if (on || last) next[p] = t;
        speech_req(p, now);
    };
    look(me, 0, 0);
    for (int i = 0; i < n; ++i) {
        int p = peds[i];
        if (!p || p == me) continue;
        Vector3 q = GET_ENTITY_COORDS(p);
        float dx = q.x - px, dy = q.y - py, dz = q.z - pz;
        float d = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (d > 30) continue;
        look(p, d, pan_to(q.x, q.y, cam, px, py));
    }
    talk_.swap(next);
    speech_req_prune(now);
}

float World::pan_to(float x, float y, float cam_heading, float px, float py) const {
    float bearing = std::atan2(-(x - px), (y - py)) * 180.0f / kPi;
    float rel = (bearing - cam_heading) * kPi / 180.0f;
    return clampv(-std::sin(rel), -1.0f, 1.0f);
}

static float ammo_kick(uint32_t ammo) {
    static std::map<uint32_t, float> table;
    if (table.empty()) {
        for (const char* g : {"REVOLVER", "PISTOL", "REPEATER", "RIFLE", "SHOTGUN"}) {
            std::string G(g);
            table[joaat("AMMO_" + G + "_EXPRESS")] = 1.15f;
            table[joaat("AMMO_" + G + "_HIGH_VELOCITY")] = 1.1f;
            table[joaat("AMMO_" + G + "_SPLIT_POINT")] = 1.05f;
            table[joaat("AMMO_" + G + "_EXPRESS_EXPLOSIVE")] = 1.3f;
            table[joaat("AMMO_" + G + "_VELOCITY")] = 1.1f;
        }
        table[joaat("AMMO_SHOTGUN_SLUG")] = 1.2f;
        table[joaat("AMMO_SHOTGUN_BUCKSHOT_INCENDIARY")] = 1.1f;
        table[joaat("AMMO_SHOTGUN_EXPRESS_EXPLOSIVE")] = 1.3f;
        table[joaat("AMMO_RIFLE_ELEPHANT")] = 1.2f;
    }
    auto it = table.find(ammo);
    return it == table.end() ? 1.0f : it->second;
}


// ---------------- camp life ----------------
// item-interaction states that mean eating, drinking, smoking, cleaning a gun
static const char* item_kind(uint32_t state) {
    struct Entry { uint32_t hash; const char* kind; };
    static const Entry kStates[] = {
#include "item_states.inc"
    };
    for (const auto& e : kStates)
        if (e.hash == state) return e.kind;
    return "";
}

// ---------------- bodies: footfalls from the real legs ----------------
static const char* const kFootBones[] = {"SKEL_L_Foot", "SKEL_R_Foot"};
// horse legs: names differ between skeletons, try the common RAGE ones (front, then rear)
static const char* const kHoofBones[] = {"SKEL_L_Hand", "SKEL_R_Hand", "SKEL_L_Foot", "SKEL_R_Foot",
                                         "SKEL_L_Finger00", "SKEL_R_Finger00", "SKEL_L_Toe0", "SKEL_R_Toe0"};

void World::bind_limbs(int ped, Limb* limbs, int n, const char* const* names, int names_n) {
    int found = 0;
    for (int i = 0; i < names_n && found < n; ++i) {
        int b = nat::GET_ENTITY_BONE_INDEX_BY_NAME(ped, names[i]);
        if (b >= 0) {
            limbs[found] = Limb{};
            limbs[found].bone = b;
            ++found;
        }
    }
    for (int i = found; i < n; ++i) limbs[i] = Limb{};
    if (limbs == hooves_) hoof_count_ = found;
    LOGI("%s: %d leg bones found", limbs == feet_ ? "player feet" : "horse hooves", found);
}

std::string World::surface_at(float x, float y, float z, int ped, uint32_t* mat_out) {
    float gz = 0;
    nat::Hash mat = 0;
    nat::GET_GROUND_Z_AND_MATERIAL(x, y, z + 0.5f, &gz, &mat);
    if (mat_out) *mat_out = mat;
    bool indoors = nat::GET_INTERIOR_FROM_ENTITY(ped) != 0;
    float sub = nat::GET_ENTITY_SUBMERGED_LEVEL(ped);
    return surfaces_.classify(mat, indoors, sub, indoors ? 0.0f : nat::GET_SNOW_LEVEL());
}

// A foot that comes to rest in world space has just been planted: that is the step.
// A hoof lands when its fall towards the ground stops - by height, which works at any gait (at a gallop a planted
// hoof still slides in the animation, so "comes to rest" misses most of them). Only real touchdowns are felt.
// Research probe (General.Probes=1 with Debug=1): every frame each limb's position, the ground under it and whether
// the detector fired, to DualSenseRDR2_limbs.csv - to design a hoof detector that catches every contact.
void World::record_limbs(const char* mode, int n, const float* x, const float* y, const float* z, const float* gz,
                         const bool* plant, float speed, double now) {
    if (!limb_csv_.is_open()) {
        fs::path path = module_dir() / "DualSenseRDR2_limbs.csv";
        limb_csv_.open(path, std::ios::app);
        if (!limb_csv_) return;
        LOGI("probe: recording hoof / foot heights to %s", path.string().c_str());
        limb_csv_ << "t,mode,speed,n,x,y,z,ground,plant (per limb)\n";
    }
    char buf[96];
    std::snprintf(buf, sizeof buf, "%.4f,%s,%.2f,%d", now, mode, speed, n);
    limb_csv_ << buf;
    for (int i = 0; i < n; ++i) {
        std::snprintf(buf, sizeof buf, ",%.3f,%.3f,%.4f,%.4f,%d", x[i], y[i], z[i], gz[i], int(plant[i]));
        limb_csv_ << buf;
    }
    limb_csv_ << '\n';
    if (++limb_lines_ % 120 == 0) limb_csv_.flush();
}

// Research (Record=1 with Debug=1): swimming - Arthur's hands and feet, or the swimming horse's legs, every frame to the
// same CSV (mode "swim" / "hswim"): per limb x, y, z and the water surface there (0 = none), then the body as one more
// row entry: x, y, z, heading, under water (1/0). To design stroke / paddle haptics from the real arm and leg motion.
void World::record_swim(int ped, const char* mode, const int* bones, int n, float speed, double now) {
    float x[5] = {}, y[5] = {}, z[5] = {}, w[5] = {};
    bool flag[5] = {};
    n = std::min(n, 4);
    for (int i = 0; i < n; ++i) {
        if (bones[i] < 0) continue;
        nat::Vector3 p = nat::GET_WORLD_POSITION_OF_ENTITY_BONE(ped, bones[i]);
        x[i] = p.x; y[i] = p.y; z[i] = p.z;
        if (!nat::GET_WATER_HEIGHT(p.x, p.y, p.z, &w[i])) w[i] = 0;
    }
    nat::Vector3 b = nat::GET_ENTITY_COORDS(ped);
    x[n] = b.x; y[n] = b.y; z[n] = b.z;
    w[n] = nat::GET_ENTITY_HEADING(ped);
    flag[n] = nat::IS_PED_SWIMMING_UNDER_WATER(ped);
    record_limbs(mode, n + 1, x, y, z, w, flag, speed, now);
}

// Swimming strokes from the real arms and legs (designed on a recorded swim and horse swim): a limb's position along
// the body's heading rises while it reaches forward and falls while it pulls the water back. A pull is felt once the
// limb has come back by D from its furthest reach - D grows with the stroke length (hands and feet: 3 cm or 10%,
// every pull of the recording, ~0.13 s after the reach; the horse's legs: 6 cm or 30% - their paddling is choppier).
// Arthur swims breaststroke (~0.8 strokes/s, both hands together, the kick in between); the horse paddles like a dog.
void World::strokes(int ped, Stroke* limbs, int n, bool horse, float speed, std::vector<WorldEvent>& ev) {
    const float hd = nat::GET_ENTITY_HEADING(ped) * kPi / 180.0f, fx = -std::sin(hd), fy = std::cos(hd);
    const nat::Vector3 b = nat::GET_ENTITY_COORDS(ped);
    const float dmin = horse ? 0.06f : 0.03f, frac = horse ? 0.3f : 0.1f;
    for (int i = 0; i < n; ++i) {
        Stroke& S = limbs[i];
        if (S.bone < 0) continue;
        const nat::Vector3 p = nat::GET_WORLD_POSITION_OF_ENTITY_BONE(ped, S.bone);
        const float f = (p.x - b.x) * fx + (p.y - b.y) * fy;          // how far forward of the body
        if (!S.init) {
            S.init = true;
            S.top = S.low = f;
            continue;
        }
        const float d = std::max(dmin, frac * S.size);
        if (S.state == 0) {                                           // reaching forward
            S.top = std::max(S.top, f);
            if (S.top - f <= d) continue;
            const float len = S.top - S.low;                          // the pull has begun
            S.size = 0.7f * S.size + 0.3f * std::max(0.05f, len);
            S.state = 1;
            S.low = f;
            WorldEvent e{WorldEvent::Swim, (i % 2) ? 0.4f : -0.4f, 1, ""};
            const float reach = clampv(len / 0.6f, 0.4f, 1.0f);       // a small treading stroke is felt softer
            if (horse) {
                e.cause = "paddle";
                e.strength = clampv(0.5f + speed / 6.0f, 0.6f, 1.0f) * reach * (i < 2 ? 1.0f : 0.7f);   // rear legs behind you
                if (i >= 2) e.pan *= 0.6f;
            } else {
                e.cause = i < 2 ? "pull" : "kick";
                e.strength = clampv(0.45f + speed / 5.0f, 0.6f, 1.1f) * reach;
                if (i >= 2) e.pan *= 0.6f;
            }
            ev.push_back(e);
        } else {                                                      // pulling back
            S.low = std::min(S.low, f);
            if (f - S.low > d) {
                S.state = 0;
                S.top = f;
            }
        }
    }
}

// The ground under a limb, from the game's ground query - which glitches: a surface up to ~0.5 m too high, for up
// to ~0.3 s (20% of the readings under a galloping horse). A reading that puts the limb under the ground, or jumps
// up under it, is dropped while it is short-lived and the last plausible ground is kept; a lasting offset is real
// (sunk into deep snow) and is taken after 0.4 s. False = no ground known yet.
bool World::limb_height(Limb& L, float x, float y, float z, float dt, float& h, float& raw_gz) {
    float gz = 0;
    nat::Hash mat = 0;
    bool got = nat::GET_GROUND_Z_AND_MATERIAL(x, y, z + 0.5f, &gz, &mat) && gz != 0;
    raw_gz = got ? gz : 0;
    bool plausible = got && (L.held > 0.4f || (gz <= z + 0.05f && (!L.have_gz || gz - L.good_gz < 0.25f)));
    if (plausible) {
        if (L.held > 0.4f) L.have_h = false;          // a new ground level: heights before it don't compare
        L.good_gz = gz;
        L.have_gz = true;
        L.held = 0;
    } else {
        L.held += dt;
    }
    if (!L.have_gz) return false;
    h = z - L.good_gz;
    return true;
}

// Touchdown, by height (designed and checked on recorded rides and walks - tools/dev/limbs_touchdown.py): the limb
// rose clearly above its last low, falls, and the fall stops near the bottom. "Clearly" scales with the limb's own
// swing (at least rise_min). Hooves: ~88% of the contacts at every gait, ~35 ms after the hoof lands (the old
// "lift 7 cm, come down" rule: ~38%). Feet: one per step at any pace (the old "the foot comes to rest" rule fired
// 2-3 times per walking step on the jittery foot speed).
bool World::touchdown(Limb& L, float h, float dt, float rise_min, float stop, float margin, float swing_max) {
    if (!L.have_h) {
        L.have_h = true;
        L.prev_h = L.hi = L.low = L.last_low = h;
        return false;
    }
    float v = (h - L.prev_h) / dt;
    L.prev_h = h;
    float base = std::min(L.last_low, L.low);
    if (L.td == 0) {                                  // after a touchdown: wait for a clear rise
        L.low = std::min(L.low, h);
        if (h < L.last_low) L.last_low = h;           // lower than the reference (an outlier was it): restart
        L.hi = std::max(L.hi, h);
        if (L.hi - std::min(L.last_low, L.low) > std::max(rise_min, 0.25f * L.swing)) L.td = 1;
        return false;
    }
    if (L.td == 1) {                                  // risen: wait for the fall
        L.hi = std::max(L.hi, h);
        if (v < -stop) L.td = 2;
        return false;
    }
    if (v > -stop && h < base + margin * L.swing) {    // falling: the fall stops near the bottom
        L.swing = clampv(0.7f * L.swing + 0.3f * (L.hi - h), 0.05f, swing_max);
        L.last_low = L.low = L.hi = h;
        L.td = 0;
        return true;
    }
    return false;
}

// Research probe (Probes + Debug): does a capsule around Arthur's legs touch vegetation? The game's FoliageActive is on
// already near a bush. One capsule test per frame, cycling candidate flag sets; logs when each starts / stops hitting.
void World::bush_probe(int me) {
    using namespace nat;
    static const int kFlags[] = {256, 16, 1, 511, 256 | 16};
    const int nf = int(sizeof kFlags / sizeof kFlags[0]);
    if (bush_handle_) {
        int hit = 0;
        Vector3 end{}, normal{};
        Entity ent = 0;
        int st = GET_SHAPE_TEST_RESULT(bush_handle_, &hit, &end, &normal, &ent);
        if (st == 1) return;                                // not ready yet
        if (st == 2) {
            int f = kFlags[bush_flag_i_];
            bool h = hit != 0;
            if (h != bush_hit_[f]) {
                int type = ent ? GET_ENTITY_TYPE(ent) : 0;     // 1 ped (or the horse), 2 vehicle, 3 object, 0 map
                LOGD("bush probe: flags %d %s (%s, foliage flag %d)", f, h ? "HIT" : "clear",
                     !h ? "-" : type == 1 ? "a ped / horse" : type == 2 ? "a vehicle" : type == 3 ? "an object" : "the map",
                     int(_GET_PED_BLACKBOARD_BOOL(me, "FoliageActive")));
            }
            bush_hit_[f] = h;
        }
        bush_handle_ = 0;
        bush_flag_i_ = (bush_flag_i_ + 1) % nf;
    }
    Vector3 p = GET_ENTITY_COORDS(me);
    bush_handle_ = START_SHAPE_TEST_CAPSULE(p.x, p.y, p.z - 0.4f, p.x, p.y, p.z + 0.3f, 0.35f, kFlags[bush_flag_i_], me, 7);
}

void World::steps(int ped, Limb* limbs, int n, float body_speed, double now, bool horse, std::vector<WorldEvent>& ev) {
    double dt = now - last_tick_;
    if (dt <= 0 || dt > 0.1) dt = 1.0 / 60;
    const bool rec = limb_probe_ && body_speed > 0.3f && n <= 4;
    float rx[4] = {}, ry[4] = {}, rz[4] = {}, rgz[4] = {};
    bool rp[4] = {};
    for (int i = 0; i < n && i < 4; ++i) {
        Limb& L = limbs[i];
        if (L.bone < 0) continue;
        // Self-healing: tracking resumes after a pause (riding, swimming, a cutscene - the ground under it is somewhere
        // else now), or no touchdown for 2 s while moving (a stuck state: the left foot fell silent for good once):
        // start the limb's detector afresh.
        if (now - L.last_seen > 0.5 || (body_speed > 1.0f && L.have_h && now - L.last_td > 2.0 && now - L.reset_t > 2.0)) {
            if (now - L.last_seen <= 0.5) LOGD("steps: %s %d silent for 2 s while moving - detector restarted", horse ? "hoof" : "foot", i);
            int bone = L.bone;
            L = Limb{};
            L.bone = bone;
            L.reset_t = L.last_td = now;
        }
        L.last_seen = now;
        nat::Vector3 p = nat::GET_WORLD_POSITION_OF_ENTITY_BONE(ped, L.bone);
        float h = 0;
        bool known = limb_height(L, p.x, p.y, p.z, float(dt), h, rgz[i]);
        if (rec) {
            rx[i] = p.x;
            ry[i] = p.y;
            rz[i] = p.z;
        }
        if (!known) continue;
        // a hoof that lifts 4 cm has stepped; a foot needs 7 cm (a walking foot shuffles a few cm on uneven ground)
        // and its fall must have all but stopped (a walking foot creeps the last centimetres down: fired too early)
        bool down = horse ? touchdown(L, h, float(dt), 0.04f, 0.4f, 0.65f, 1.0f)
                          : touchdown(L, h, float(dt), 0.07f, 0.1f, 0.5f, 0.6f);
        if (!down) continue;
        // the same limb can't land twice within 0.15 s (hooves) / 0.2 s (feet): a double hit
        bool double_hit = now - L.last_td < (horse ? 0.15 : 0.2);
        L.last_td = now;
        if (double_hit || body_speed <= 0.4f) continue;
        rp[i] = true;
        L.last_plant = now;
        WorldEvent e{horse ? WorldEvent::Hoof : WorldEvent::Footstep, 0, 1, surface_at(p.x, p.y, p.z, ped)};
        if (horse) {
            hoof_times_.push_back(now);
            e.pan = (i % 2) ? 0.25f : -0.25f;                              // hooves: around the centre
            // a gallop has twice the hoofbeats of a trot - each one must not also hit twice as hard
            e.strength = clampv(0.35f + body_speed / 25.0f, 0.35f, 0.7f);
        } else {
            e.pan = (i % 2) ? 0.45f : -0.45f;                              // boots: left foot left, right foot right
            float sp = body_speed;
            // walk / run / sprint: a walking step must still be felt (35% of a sprint was below it)
            e.strength = clampv(sp < 2.2f ? 0.5f : sp < 4.8f ? 0.65f : 0.8f, 0.2f, 1.0f) * step_strength_;
        }
        ev.push_back(e);
    }
    if (horse)
        while (!hoof_times_.empty() && now - hoof_times_.front() > 1.5) hoof_times_.pop_front();
    if (rec) record_limbs(horse ? "horse" : "foot", n, rx, ry, rz, rgz, rp, body_speed, now);
}

static float wrap180(float a) {
    while (a > 180) a -= 360;
    while (a < -180) a += 360;
    return a;
}

// Say the phrase: Arthur turns his head to the closest person and says a greeting line, they look
// back and answer. Only speech - no buttons are pressed, so it can never do anything but greet.
bool World::speak(int ped, const std::vector<std::string>& lines, int listener, std::string* used) {
    using namespace nat;
    for (const auto& line : lines) {
        for (Hash param : {joaat("SPEECH_PARAMS_FORCE"), joaat("SPEECH_PARAMS_STANDARD"), Hash(0)}) {
            ScriptedSpeechParams sp{line.c_str(), nullptr, 0, param, listener, 0, 1, 1};
            if (PLAY_PED_AMBIENT_SPEECH_NATIVE(ped, &sp)) {
                if (used) *used = line;
                return true;
            }
        }
    }
    return false;
}

// Arthur greets `target` with voice lines only (no honor): the fallback when the real interaction fails.
void World::speech_greet(int me, int target, const GameSnapshot& s, std::vector<WorldEvent>& ev) {
    using namespace nat;
    TASK_LOOK_AT_ENTITY(me, target, 3000);
    bool male = IS_PED_MALE(target);
    int h = s.hour;
    std::vector<std::string> lines;
    if (h >= 5 && h < 12) lines.push_back(male ? "GREET_MORNING_MALE" : "GREET_MORNING_FEMALE");
    if (h >= 18 && h < 23) lines.push_back(male ? "GREET_EVENING_MALE" : "GREET_EVENING_FEMALE");
    lines.push_back(male ? "GREET_MALE" : "GREET_FEMALE");
    lines.push_back("GREET_GENERAL");
    std::string used;
    if (!speak(me, lines, target, &used)) {
        LOGI("greeting: the game refused every greeting line");
        return;
    }
    LOGI("greeting (voice only, no honor): Arthur says %s", used.c_str());
    TASK_LOOK_AT_ENTITY(target, me, 3500);
    reply_target_ = target;
    reply_at_ = s.time + 1.4;
    ev.push_back({WorldEvent::Ack, 0, 0.5f, "speech"});
}

// Say the phrase: the real greeting, as if you focused the person and chose Greet - it counts for honor.
// Everything goes through the game's own interaction actions (never aim, never a raw button):
//   turn the camera to the person -> request interaction focus -> once the game has focused them and
//   shows the Greet prompt, trigger the Greet action -> let go. Nothing else can be triggered: if the
//   focus doesn't happen, or you start aiming, it stops (and Arthur just says hello, without honor).
void World::greet(int pl, int me, float px, float py, const int* peds, int n, const GameSnapshot& s,
                  std::vector<WorldEvent>& ev) {
    using namespace nat;
    static const Hash kLockOn = joaat("INPUT_INTERACT_LOCKON");
    static const Hash kGreet = joaat("INPUT_INTERACT_LOCKON_POS");
    double now = s.time;
    if (reply_target_ && now >= reply_at_) {           // speech fallback: the other person answers
        int t = reply_target_;
        reply_target_ = 0;
        std::string used;
        if (!IS_PED_DEAD_OR_DYING(t) && speak(t, {"GREET_GENERAL_STRANGER", "GREET_GENERAL"}, me, &used))
            LOGI("greeting: they answered (%s)", used.c_str());
    }
    bool requested = greet_requested_.exchange(false);
    auto fail = [&](const char* why) {
        LOGI("greeting: %s", why);
        int t = greet_target_;
        greet_ = Greet::Idle;
        if (t && config().flag("Voice", "SpeechFallback", true) && !IS_PED_DEAD_OR_DYING(t)) speech_greet(me, t, s, ev);
    };
    if (greet_ != Greet::Idle && (s.blocked || IS_PLAYER_FREE_AIMING(pl))) {
        greet_ = Greet::Idle;
        LOGI("greeting: cancelled (aiming / menu)");
        return;
    }
    if (requested && greet_ == Greet::Idle) {
        if (s.blocked) { LOGI("greeting: not now (menu / cutscene / no control)"); return; }
        if (now - last_greet_ < 2.0) return;
        float range = config().num("Voice", "Range", 6.0f);
        float cam = GET_GAMEPLAY_CAM_ROT().z;
        int target = 0;
        float best = 1e9f;
        for (int i = 0; i < n; ++i) {
            int p = peds[i];
            if (!p || p == me || !IS_PED_HUMAN(p) || IS_PED_DEAD_OR_DYING(p)) continue;
            Vector3 q = GET_ENTITY_COORDS(p);
            float dx = q.x - px, dy = q.y - py, d = std::sqrt(dx * dx + dy * dy);
            if (d > range) continue;
            float bearing = std::atan2(-dx, dy) * 180.0f / kPi;
            float score = d + std::fabs(wrap180(bearing - cam)) / 45.0f;
            if (score < best) { best = score; target = p; }
        }
        if (!target) { LOGI("greeting: nobody close enough"); return; }
        last_greet_ = now;
        greet_target_ = target;
        greet_ = s.armed ? Greet::Idle : Greet::Turn;
        if (s.armed) { fail("weapon in hand - the game only greets with it holstered"); return; }
        greet_t_ = now;
        greet_from_ = GET_GAMEPLAY_CAM_RELATIVE_HEADING();
    }
    if (greet_ == Greet::Idle) return;
    Vector3 q = GET_ENTITY_COORDS(greet_target_);
    float want = wrap180(std::atan2(-(q.x - px), q.y - py) * 180.0f / kPi - GET_ENTITY_HEADING(me));
    switch (greet_) {
    case Greet::Turn: {                                   // smooth camera turn onto them (~0.25 s)
        float k = clampv(float(now - greet_t_) / 0.25f, 0.0f, 1.0f);
        k = k * k * (3 - 2 * k);
        SET_GAMEPLAY_CAM_RELATIVE_HEADING(greet_from_ + wrap180(want - greet_from_) * k);
        if (k >= 1.0f) { greet_ = Greet::Lock; greet_t_ = now; lock_t_ = 0; }
        break;
    }
    case Greet::Lock: {                                   // hold "interaction focus" until the game focuses them
        SET_CONTROL_VALUE_NEXT_FRAME(0, kLockOn, 1.0f);
        Entity t = 0;
        bool locked = (GET_PLAYER_INTERACTION_TARGET_ENTITY(pl, &t) || GET_PLAYER_TARGET_ENTITY(pl, &t)) && t &&
                      IS_ENTITY_A_PED(t) && IS_PED_HUMAN(t);
        if (locked && !lock_t_) { lock_t_ = now; greet_target_ = t; }
        bool prompt = UI_PROMPT_IS_CONTROL_ACTION_ACTIVE(kGreet);
        if (lock_t_ && now - lock_t_ > 0.25 && prompt) { greet_ = Greet::Press; press_frames_ = 0; }
        else if (now - greet_t_ > 1.2) fail(locked ? "focused, but no Greet prompt appeared" : "could not focus them");
        break;
    }
    case Greet::Press:                                    // the Greet action for a few frames
        SET_CONTROL_VALUE_NEXT_FRAME(0, kLockOn, 1.0f);
        SET_CONTROL_VALUE_NEXT_FRAME(0, kGreet, 1.0f);
        if (++press_frames_ >= 3) {
            greet_ = Greet::Hold;
            greet_t_ = now;
            LOGI("greeting: real greet (counts for honor)");
            ev.push_back({WorldEvent::Ack, 0, 1, "real"});
        }
        break;
    case Greet::Hold:                                     // keep focus while Arthur talks, then let go
        SET_CONTROL_VALUE_NEXT_FRAME(0, kLockOn, 1.0f);
        if (now - greet_t_ > 0.6) greet_ = Greet::Idle;
        break;
    default:
        break;
    }
}

void World::tick() {
    using namespace nat;
    Config& cfg = config();
    GameSnapshot s;
    s.time = now_s();
    limb_probe_ = log::debug_enabled() && cfg.flag("General", "Record", false);   // recorder, bush probe, cue log
    // Testing (Debug=1): [General] SetWeather=rain / thunderstorm / snow / sunny ... sets the game's weather when it
    // changes (edit the ini, hold PS); "clear" gives the weather back to the game.
    if (log::debug_enabled()) {
        std::string want = cfg.str("General", "SetWeather", "");
        if (want != weather_set_) {
            weather_set_ = want;
            if (storm_) SET_RAIN(-1.0f);                  // leaving the test storm: the weather's own rain again
            storm_ = false;
            if (want == "clear") {
                CLEAR_OVERRIDE_WEATHER();
                CLEAR_WEATHER_TYPE_PERSIST();
                LOGI("weather: back to the game's own");
            } else if (want == "storm") {                // the worst there is: hurricane, full rain, full wind, lightning
                CLEAR_OVERRIDE_WEATHER();                // close by - for testing rain and thunder
                CLEAR_WEATHER_TYPE_PERSIST();
                SET_WEATHER_TYPE(joaat("hurricane"), true, true, true, 2.0f, false);
                storm_ = true;
                storm_t0_ = s.time;
                storm_reapplied_ = 0;
                next_bolt_ = s.time + 6.0;
                LOGI("weather: test storm (hurricane, full rain and wind, lightning 25-80 m away every 8-20 s)");
            } else if (!want.empty()) {
                SET_WEATHER_TYPE(joaat(want), true, true, true, 4.0f, false);
                LOGI("weather: set to %s (from the ini, SetWeather)", want.c_str());
            }
        }
    }
    if (storm_) {
        // the game restores its own weather after loading a story: set the storm again 10 and 30 s in
        const double again[2] = {10.0, 30.0};
        if (storm_reapplied_ < 2 && s.time - storm_t0_ > again[storm_reapplied_]) {
            SET_WEATHER_TYPE(joaat("hurricane"), true, true, true, 2.0f, false);
            ++storm_reapplied_;
        }
        SET_RAIN(1.0f);
        SET_WIND_SPEED(12.0f);
        if (s.time >= next_bolt_) {
            Vector3 me_at = GET_ENTITY_COORDS(PLAYER_PED_ID());
            const float a = float(std::rand() % 360) * kPi / 180.0f, d = 25.0f + float(std::rand() % 56);
            FORCE_LIGHTNING_FLASH_AT_COORDS(me_at.x + d * std::cos(a), me_at.y + d * std::sin(a), me_at.z);
            LOGI("weather: lightning %.0f m away", d);
            next_bolt_ = s.time + 8.0 + double(std::rand() % 13);
        }
    }
    if (!game_files::ready()) core().load_game_files();   // scripts run: the game's archives are mounted
    settings_ui_tick(s.time);            // the Settings page's data store, also while no player exists
    Player pl = PLAYER_ID();
    Ped me = PLAYER_PED_ID();
    if (!me || !IS_PLAYER_PLAYING(pl)) {
        std::lock_guard<std::mutex> l(mu_);
        snap_ = s;
        return;
    }
    s.valid = true;
    s.halted = IS_PAUSE_MENU_ACTIVE() || IS_LOADING_SCREEN_VISIBLE() || GET_IS_LOADING_SCREEN_ACTIVE() ||
               IS_PLAYER_SWITCH_IN_PROGRESS() || IS_SCREEN_FADED_OUT() || !IS_SCREEN_FADED_IN();
    s.blocked = s.halted || !IS_PLAYER_CONTROL_ON(pl);
    s.cutscene = s.blocked && !s.halted;
    if (log::debug_enabled()) {                       // debug: when control goes and comes back (cutscenes), and why
        int why = (IS_PAUSE_MENU_ACTIVE() ? 1 : 0) | (IS_LOADING_SCREEN_VISIBLE() ? 2 : 0) | (IS_SCREEN_FADED_OUT() ? 4 : 0) |
                  (!IS_PLAYER_CONTROL_ON(pl) ? 8 : 0);
        if (why != blocked_why_) {
            LOGD("control: %s%s%s%s%s", why ? "lost -" : "back", why & 1 ? " pause" : "", why & 2 ? " loading" : "",
                 why & 4 ? " faded" : "", why & 8 ? " no-control (cutscene/scripted)" : "");
            blocked_why_ = why;
        }
    }
    s.menu = IS_PAUSE_MENU_ACTIVE();               // (IS_ANY_UIAPP_ACTIVE is true all the time in game)
    if (s.menu != menu_logged_) {
        LOGD("menu %s", s.menu ? "open" : "closed");
        menu_logged_ = s.menu;
    }
    Vector3 pos = GET_ENTITY_COORDS(me);
    float cam = GET_GAMEPLAY_CAM_ROT().z;

    // --- weapon ---
    Hash w = 0;
    GET_CURRENT_PED_WEAPON(me, &w);
    s.weapon = w;
    s.group = w ? GET_WEAPONTYPE_GROUP(w) : 0;
    s.armed = w && w != joaat("WEAPON_UNARMED");
    s.lantern = w == joaat("WEAPON_MELEE_LANTERN") || w == joaat("WEAPON_MELEE_DAVY_LANTERN");
    s.attach_point = s.armed ? GET_DEFAULT_WEAPON_ATTACH_POINT(w) : -1;
    {
        Hash off = 0;
        s.dual_wield = s.armed && GET_CURRENT_PED_WEAPON_AT(me, &off, 1) && off && off != joaat("WEAPON_UNARMED");
        if (s.dual_wield != dual_logged_) {
            LOGD("dual wield: %d (off hand 0x%08X)", int(s.dual_wield), off);
            dual_logged_ = s.dual_wield;
        }
    }
    if (s.armed) {
        int ammo = 0;
        if (GET_AMMO_IN_CLIP(me, &ammo, w)) s.clip = ammo;
        s.clip_max = GET_MAX_AMMO_IN_CLIP(me, w);
        if (cfg.flag("Triggers", "AmmoTypeRecoil", true)) s.kick_mult = ammo_kick(GET_PED_AMMO_TYPE_FROM_WEAPON(me, w));
        if (cfg.flag("Triggers", "ConditionGrit", true)) {
            Entity obj = GET_CURRENT_PED_WEAPON_ENTITY_INDEX(me);
            if (obj) s.grit = clampv(0.6f * GET_WEAPON_DEGRADATION(obj) + 0.4f * GET_WEAPON_DIRT(obj), 0.0f, 1.0f);
        }
    }
    // fishing: the game's own fishing task (read only - the fishing script writes it back every frame)
    if (w == joaat("WEAPON_FISHINGROD")) {
        alignas(8) uint64_t buf[32] = {};
        FishingState& f = s.fishing;
        f.active = GET_TASK_FISHING(me, buf);
        auto i32 = [&](int i) { return int32_t(uint32_t(buf[i])); };
        auto f32 = [&](int i) { uint32_t u = uint32_t(buf[i]); float v; std::memcpy(&v, &u, 4); return std::isfinite(v) ? v : 0.0f; };
        if (f.active) {
            f.state = i32(0);
            f.distance = f32(2);
            f.reel = f32(4);
            f.cmd = i32(6);
            f.fish = uint32_t(buf[7]);
            f.weight_lb = f32(8) * 54.25f;
            f.tension = clampv(f32(13), 0.0f, 1.0f);
            f.struggle = f32(17);
            f.side = f32(22);
        }
        if (log::debug_enabled() && f.state != fish_log_state_) {
            LOGD("fishing: state %d -> %d (tension %.2f, fish %.1f lb, struggle %.0f, reel %.2f, side %.2f, bits %d)",
                 fish_log_state_, f.state, f.tension, f.weight_lb, f.struggle, f.reel, f.side, f.cmd);
            fish_log_state_ = f.state;
        }
    } else {
        fish_log_state_ = -1;
    }
    s.deadeye_marks = s.dead_eye ? GET_NUM_MARKED_DEADEYE_TARGETS(pl) : 0;
    if (s.deadeye_marks != marks_logged_) {
        LOGD("dead eye: %d marked", s.deadeye_marks);
        marks_logged_ = s.deadeye_marks;
    }
    s.reloading = IS_PED_RELOADING(me);
    s.ready = IS_PED_WEAPON_READY_TO_SHOOT(me);
    s.holstering = IS_WEAPON_HOLSTER_STATE_CHANGING(me);
    if (s.armed && s.ready != last_ready_) {
        if (ready_change_t_ > 0) LOGD("weapon ready: %s (after %.0f ms)", s.ready ? "yes" : "no", (s.time - ready_change_t_) * 1000);
        last_ready_ = s.ready;
        ready_change_t_ = s.time;
    }
    static const Hash kWheel = joaat("INPUT_OPEN_WHEEL_MENU");
    s.wheel = IS_CONTROL_PRESSED(0, kWheel) || IS_DISABLED_CONTROL_PRESSED(0, kWheel);
    s.wheel_item = s.wheel ? HUD_GET_INVENTORY_WHEEL_CURRENTLY_HIGHLIGHTED() : 0;
    s.shooting = IS_PED_SHOOTING(me);
    s.free_aim = IS_PLAYER_FREE_AIMING(pl);
    s.lock_on = IS_PLAYER_TARGETTING_ANYTHING(pl);
    s.aiming = s.free_aim || s.lock_on;
    s.dead_eye = IS_SPECIAL_ABILITY_ACTIVE(pl);
    // low health = Arthur's real health (the ring), like the game's own warning - not the core, which can be
    // empty while the health is full. A fortified (gold) ring or core counts as healthy.
    bool gold_health = IS_ATTRIBUTE_CORE_OVERPOWERED(me, 0) || IS_ATTRIBUTE_OVERPOWERED(me, 0);
    bool gold_stamina = IS_ATTRIBUTE_CORE_OVERPOWERED(me, 1) || IS_ATTRIBUTE_OVERPOWERED(me, 1);
    int raw_health = GET_ATTRIBUTE_CORE_VALUE(me, 0), raw_stamina = GET_ATTRIBUTE_CORE_VALUE(me, 1);
    int hp = GET_ENTITY_HEALTH(me), hp_max = GET_ENTITY_MAX_HEALTH(me);
    int health_pct = hp_max > 0 ? clampv(hp * 100 / hp_max, 0, 100) : 100;
    s.health_core = gold_health ? 100 : health_pct;
    s.stamina_core = gold_stamina ? 100 : raw_stamina;
    int cores_key = health_pct / 5 * 100000 + raw_health / 5 * 1000 + raw_stamina / 5 * 10 + gold_health * 2 + gold_stamina;
    if (cores_key != cores_logged_) {
        LOGD("health %d/%d (%d%%)%s, health core %d, stamina core %d%s", hp, hp_max, health_pct,
             gold_health ? " (fortified)" : "", raw_health, raw_stamina, gold_stamina ? " (fortified)" : "");
        cores_logged_ = cores_key;
    }
    s.swimming = IS_PED_SWIMMING(me);
    // wading and bushes: how deep in water, and the game's own "pushing through foliage" state (the one it uses for
    // its foliage sounds and animation)
    s.wade = GET_ENTITY_SUBMERGED_LEVEL(me);
    s.foliage = _GET_PED_BLACKBOARD_BOOL(me, "FoliageActive");
    s.foliage_height = s.foliage ? _GET_PED_BLACKBOARD_FLOAT(me, "FoliageHeight") : 0.0f;
    if (log::debug_enabled() && s.foliage != foliage_logged_) {
        foliage_logged_ = s.foliage;
        LOGD("foliage: Arthur %s (height %.2f)", s.foliage ? "pushing through" : "out", s.foliage_height);
    }
    if (limb_probe_) bush_probe(me);

    // --- body: exhaustion, cold, drink ---
    s.temperature = GET_TEMPERATURE_AT_COORDS(pos.x, pos.y, pos.z);
    float drunk = IS_PED_DRUNK(me) ? clampv(GET_PED_DRUNKNESS(me), 0.3f, 1.0f) : 0.0f;
    float tired = clampv((25.0f - float(s.stamina_core)) / 25.0f, 0.0f, 1.0f);
    float cold = clampv((-3.0f - s.temperature) / 15.0f, 0.0f, 1.0f);
    if (cfg.flag("Triggers", "Tremor", true)) s.tremor = std::max({tired * 0.8f, cold, drunk});

    // --- horse / transport ---
    if (!surfaces_loaded_) {
        surfaces_.load(data_dir() / "materials.json");
        surfaces_loaded_ = true;
    }
    std::vector<WorldEvent> ev;
    s.on_mount = IS_PED_ON_MOUNT(me);
    Ped horse = s.on_mount ? GET_MOUNT(me) : 0;
    if (horse) {
        s.mount_speed = GET_ENTITY_SPEED(horse);
        s.mount_stamina = GET_ATTRIBUTE_CORE_VALUE(horse, 1);
        s.mount_pitch = GET_ENTITY_ROTATION(horse).x;
        s.horse_wade = GET_ENTITY_SUBMERGED_LEVEL(horse);
        s.horse_foliage = _GET_PED_BLACKBOARD_BOOL(horse, "FoliageActive");
        s.horse_foliage_height = s.horse_foliage ? _GET_PED_BLACKBOARD_FLOAT(horse, "FoliageHeight") : 0.0f;
        if (log::debug_enabled() && s.horse_foliage != horse_foliage_logged_) {
            horse_foliage_logged_ = s.horse_foliage;
            LOGD("foliage: the horse %s (height %.2f)", s.horse_foliage ? "pushing through" : "out", s.horse_foliage_height);
        }
        Vector3 hp = GET_ENTITY_COORDS(horse);
        s.horse_surface = surface_at(hp.x, hp.y, hp.z, horse);
        if (horse != hooves_horse_) {
            hooves_horse_ = horse;
            bind_limbs(horse, hooves_, 4, kHoofBones, 8);
            hoof_times_.clear();
        }
        s.hoof_bones = hoof_count_ >= 2;
        bool horse_swims = IS_PED_SWIMMING(horse);
        if (log::debug_enabled() && horse_swims != horse_swim_logged_) {
            horse_swim_logged_ = horse_swims;
            LOGD("swim: the horse %s", horse_swims ? "swims" : "is out of the water");
        }
        if (horse_swims && hoof_count_ == 4 && !s.halted) {
            if (!horse_swim_was_ || horse != paddle_horse_) {          // a fresh swim: start the legs' detectors anew
                paddle_horse_ = horse;
                for (int i = 0; i < 4; ++i) {
                    paddle_[i] = Stroke{};
                    paddle_[i].bone = hooves_[i].bone;
                }
            }
            strokes(horse, paddle_, 4, true, s.mount_speed, ev);
            if (limb_probe_) {
                int bones[4] = {hooves_[0].bone, hooves_[1].bone, hooves_[2].bone, hooves_[3].bone};
                record_swim(horse, "hswim", bones, 4, s.mount_speed, s.time);
            }
        }
        horse_swim_was_ = horse_swims;
        size_t before = ev.size();
        if (s.hoof_bones) steps(horse, hooves_, hoof_count_, s.mount_speed, s.time, true, ev);
        hoof_plants_ += int(ev.size() - before);
        s.hoof_rate = float(hoof_times_.size()) / 1.5f;
        if (log::debug_enabled() && s.time - hoof_stat_t_ > 3.0) {
            if (s.mount_speed > 1.0f)
                LOGD("hooves: speed %.1f m/s, %.1f plants/s detected, ground %s, snow %.2f, in water %.2f", s.mount_speed,
                     hoof_plants_ / (s.time - hoof_stat_t_), s.horse_surface.c_str(), GET_SNOW_LEVEL(),
                     GET_ENTITY_SUBMERGED_LEVEL(horse));
            hoof_plants_ = 0;
            hoof_stat_t_ = s.time;
        }
    }
    if (!horse) horse_swim_was_ = false;
    s.in_train = IS_PED_IN_ANY_TRAIN(me);
    s.in_vehicle = IS_PED_IN_ANY_VEHICLE(me);
    s.speed = GET_ENTITY_SPEED(me);

    // --- swimming: strokes from the real arms and legs, a splash for a jump into water ---
    const float falling = -GET_ENTITY_VELOCITY(me).z;                 // falling speed (m/s), the fastest in 0.5 s
    if (falling > fall_max_ || s.time - fall_max_t_ > 0.5) {
        fall_max_ = falling;
        fall_max_t_ = s.time;
    }
    if (log::debug_enabled() && s.swimming != swim_logged_) {
        swim_logged_ = s.swimming;
        LOGD("swim: Arthur %s (falling %.1f m/s just before)", s.swimming ? "swims" : "is out of the water", fall_max_);
    }
    if (s.swimming && !s.on_mount && !s.halted) {
        if (!swim_was_ || me != swim_ped_) {                          // a fresh swim: start the detectors anew
            swim_ped_ = me;
            static const char* const kSwimBones[] = {"SKEL_L_Hand", "SKEL_R_Hand", "SKEL_L_Foot", "SKEL_R_Foot"};
            for (int i = 0; i < 4; ++i) {
                swim_[i] = Stroke{};
                swim_[i].bone = GET_ENTITY_BONE_INDEX_BY_NAME(me, kSwimBones[i]);
            }
            if (fall_max_ > 2.0f)                                     // jumped or fell in
                ev.push_back({WorldEvent::Swim, 0, clampv(fall_max_ / 8.0f, 0.4f, 1.0f), "dive"});
        }
        strokes(me, swim_, 4, false, s.speed, ev);
        if (limb_probe_) {
            int bones[4] = {swim_[0].bone, swim_[1].bone, swim_[2].bone, swim_[3].bone};
            record_swim(me, "swim", bones, 4, s.speed, s.time);
        }
    }
    swim_was_ = s.swimming && !s.on_mount;

    // --- on foot: steps, landings, climbing, doors ---
    if (!s.on_mount && !s.in_vehicle && !s.swimming && !s.halted) {
        if (me != feet_ped_) {
            feet_ped_ = me;
            bind_limbs(me, feet_, 2, kFootBones, 2);
        }
        bool crouch = GET_PED_CROUCH_MOVEMENT(me), carry = IS_PED_CARRYING_SOMETHING(me);
        step_strength_ = (crouch ? 0.55f : 1.0f) * (carry ? 1.25f : 1.0f);
        size_t before_steps = ev.size();
        steps(me, feet_, 2, s.speed, s.time, false, ev);
        if (ev.size() > before_steps) {
            foot_plants_ += int(ev.size() - before_steps);
            foot_surface_ = ev.back().cause;
        }
        if (log::debug_enabled() && s.time - foot_stat_t_ > 3.0) {    // debug: how often steps are felt, and where
            if (s.speed > 0.5f)
                LOGD("steps: speed %.1f m/s, %.1f steps/s, ground %s, snow %.2f, in water %.2f", s.speed,
                     foot_plants_ / (s.time - foot_stat_t_), foot_surface_.c_str(), GET_SNOW_LEVEL(),
                     GET_ENTITY_SUBMERGED_LEVEL(me));
            foot_plants_ = 0;
            foot_stat_t_ = s.time;
        }
        bool air =IS_ENTITY_IN_AIR(me) || IS_PED_FALLING(me);
        double dt = s.time - last_tick_;
        if (air && dt > 0 && dt < 0.1) air_time_ += dt;
        if (!air) {
            if (air_time_ > 0.3) {
                Vector3 c = GET_ENTITY_COORDS(me);
                ev.push_back({WorldEvent::Land, 0, clampv(float(air_time_) / 1.2f, 0.3f, 1.0f), surface_at(c.x, c.y, c.z, me)});
            }
            air_time_ = 0;
        }
        bool climbing = IS_PED_CLIMBING(me) || IS_PED_VAULTING(me);
        if (climbing && !was_climbing_) ev.push_back({WorldEvent::Climb, 0, 1, ""});
        was_climbing_ = climbing;
        bool door = IS_PED_OPENING_DOOR(me);
        if (door && !was_door_) ev.push_back({WorldEvent::Door, 0.3f, 1, ""});
        was_door_ = door;
    } else {
        air_time_ = 0;
    }

    // --- world ---
    s.hour = GET_CLOCK_HOURS();
    s.weather = GET_PREV_WEATHER_TYPE_HASH_NAME();
    s.wanted = IS_LAW_INCIDENT_ACTIVE(pl) || GET_WANTED_SCORE(pl) > 0;

    // --- lasso ---
    Entity target = GET_LASSO_TARGET(me);
    if (target) {
        s.lasso_attached = true;
        s.lasso_pull = clampv(GET_ENTITY_SPEED(target) / 5.0f + (IS_ENTITY_A_PED(target) && IS_PED_RAGDOLL(target) ? 0.2f : 0.0f), 0.0f, 1.0f);
    }

    // --- explosions: the game's own, as they happen (thrown or placed dynamite - ours or anyone's -, lanterns, gas,
    // vehicles, Molotovs, explosive rounds, lightning strikes). One check per frame; only a new one is examined: its
    // kind (by explosion tag), how far (nested spheres) and which side (spheres left / right of the camera). ---
    if (IS_EXPLOSION_IN_SPHERE(-1, pos.x, pos.y, pos.z, 150.0f)) {
        if (!explosion_on_ && s.time - explosion_t_ > 0.4) {
            auto any = [&](std::initializer_list<int> tags) {
                for (int t : tags)
                    if (IS_EXPLOSION_IN_SPHERE(t, pos.x, pos.y, pos.z, 150.0f)) return true;
                return false;
            };
            // tags: 33 lightning; 2 3 molotov, 24 lantern, 30 fire arrow; 12 19 32 explosive / phosphorus rounds, 21 firework
            const char* kind = any({33}) ? "thunder" : any({2, 3, 24, 30}) ? "fire" : any({12, 19, 32, 21}) ? "small" : "blast";
            float dist = 150.0f;
            for (float r : {6.0f, 15.0f, 35.0f, 80.0f})
                if (IS_EXPLOSION_IN_SPHERE(-1, pos.x, pos.y, pos.z, r)) {
                    dist = r;
                    break;
                }
            float pan = 0;
            if (dist > 6.0f) {
                float hd = cam * kPi / 180.0f, rx = std::cos(hd), ry = std::sin(hd);      // the camera's right
                float off = dist * 0.6f, rad = dist * 0.75f;
                bool right = IS_EXPLOSION_IN_SPHERE(-1, pos.x + rx * off, pos.y + ry * off, pos.z, rad);
                bool left = IS_EXPLOSION_IN_SPHERE(-1, pos.x - rx * off, pos.y - ry * off, pos.z, rad);
                pan = right && !left ? 0.6f : left && !right ? -0.6f : 0.0f;
            }
            float strength = dist <= 6 ? 1.0f : dist <= 15 ? 0.8f : dist <= 35 ? 0.55f : dist <= 80 ? 0.35f : 0.2f;
            ev.push_back({WorldEvent::Explosion, pan, strength, kind});
            explosion_t_ = s.time;
            LOGD("explosion: %s within %.0f m, side %+.1f", kind, dist, pan);
        }
        explosion_on_ = true;
    } else {
        explosion_on_ = false;
    }

    // --- people around: who shoots, who got hurt by us, who hurt us ---
    int peds[256];
    int n = shv_worldGetAllPeds(peds, 256);
    Ped melee_target = GET_MELEE_TARGET_FOR_PED(me);
    // Who really damaged whom just now: the game's own damage events (EVENT_ENTITY_DAMAGED: [0] damaged, [1] by whom),
    // read only. The "has X ever damaged Y" record lasts forever - a gunman from minutes ago turned every later bit
    // of health drain (a tonic's gold wearing off) into a felt hit.
    {
        static const Hash kDamaged = 0x18010D37;       // EVENT_ENTITY_DAMAGED
        int n_ev = GET_NUMBER_OF_EVENTS(0);
        for (int i = 0; i < n_ev; ++i) {
            if (GET_EVENT_AT_INDEX(0, i) != kDamaged) continue;
            alignas(8) uint64_t d[9] = {};
            if (!GET_EVENT_DATA(0, i, d, 9)) continue;
            const int victim = int(uint32_t(d[0])), by = int(uint32_t(d[1]));
            if (victim == me) {
                if (log::debug_enabled() && s.time - damaged_me_t_ > 0.3)
                    LOGD("damage event: Arthur hurt by %s", !by ? "nothing (fall, fire...)" : by == me ? "himself"
                         : !DOES_ENTITY_EXIST(by) || !IS_ENTITY_A_PED(by) ? "an object" : IS_PED_HUMAN(by) ? "a person" : "an animal");
                damaged_me_by_ = by;
                damaged_me_t_ = s.time;
            } else if (by == me && victim) {
                hit_by_me_t_[victim] = s.time;
            }
        }
        for (auto it = hit_by_me_t_.begin(); it != hit_by_me_t_.end();)
            it = s.time - it->second > 1.0 ? hit_by_me_t_.erase(it) : std::next(it);
    }
    std::map<int, int> seen;
    int attacker = 0;
    float attacker_dist = 1e9f;
    int health = GET_ENTITY_HEALTH(me);
    bool hurt = last_health_ >= 0 && health < last_health_;
    const bool damage_now = s.time - damaged_me_t_ < 0.3;   // the game reported damage to Arthur this moment
    if (hurt && damage_now && damaged_me_by_ && damaged_me_by_ != me && DOES_ENTITY_EXIST(damaged_me_by_) &&
        IS_ENTITY_A_PED(damaged_me_by_)) {
        Vector3 q = GET_ENTITY_COORDS(damaged_me_by_);
        float dx = q.x - pos.x, dy = q.y - pos.y, dz = q.z - pos.z;
        attacker = damaged_me_by_;
        attacker_dist = std::sqrt(dx * dx + dy * dy + dz * dz);
    }
    for (int i = 0; i < n; ++i) {
        Ped p = peds[i];
        if (!p || p == me) continue;
        Vector3 q = GET_ENTITY_COORDS(p);
        float dx = q.x - pos.x, dy = q.y - pos.y, dz = q.z - pos.z;
        float d = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (d > 90) continue;
        if (p == melee_target && d < 2.6f) s.melee_target_near = true;
        if (IS_PED_SHOOTING(p) && d < 75 && s.time - ped_shot_t_[p] > 0.08) {
            ped_shot_t_[p] = s.time;
            ev.push_back({WorldEvent::Gunfire, pan_to(q.x, q.y, cam, pos.x, pos.y), 1.0f / (1.0f + d / 12.0f), ""});
        }
        if (d < 45) {
            int h = GET_ENTITY_HEALTH(p);
            seen[p] = h;
            auto it = ped_health_.find(p);
            auto hit = hit_by_me_t_.find(p);
            if (it != ped_health_.end() && h < it->second && hit != hit_by_me_t_.end() && s.time - hit->second < 0.3) {
                if (d < 3.0f) ++melee_hits_;
                else ev.push_back({WorldEvent::HitConfirm, 0.5f, 1.0f, ""});
            }
        }
    }
    ped_health_.swap(seen);
    if (log::debug_enabled() && config().flag("General", "Probes", false)) {   // research probes (General.Probes=1)
        speech_probe(me, peds, n, pos.x, pos.y, pos.z, cam, s.time);
        scene_probe(me, s.time);
    }
    // speech vibration: who near is talking (their game objects; the dialogue module reads which line)
    talkers_.clear();
    if (dialogue().speech_wanted()) {
        // everyone within 25 m (nearest 16): the game's "is speaking" natives miss some conversation lines, the
        // speech requests in memory do not
        talkers_.push_back({shv_getScriptHandleBaseAddress(me), me, 0.0f, 0.0f, true});
        std::vector<Dialogue::Talker> close_by;
        for (int i = 0; i < n; ++i) {
            int p = peds[i];
            if (!p || p == me) continue;
            shv::Vector3 q = GET_ENTITY_COORDS(p);
            float dx = q.x - pos.x, dy = q.y - pos.y, dz = q.z - pos.z;
            float d = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (d > 25) continue;
            close_by.push_back({shv_getScriptHandleBaseAddress(p), p, pan_to(q.x, q.y, cam, pos.x, pos.y), d, false});
        }
        std::sort(close_by.begin(), close_by.end(), [](const auto& a, const auto& b) { return a.dist < b.dist; });
        if (close_by.size() > 16) close_by.resize(16);
        talkers_.insert(talkers_.end(), close_by.begin(), close_by.end());
    }
    dialogue().game_tick(talkers_, talkers_.empty() ? 0 : GET_LAST_PLAYED_SPEECH_FOR_PED(me));
    greet(pl, me, pos.x, pos.y, peds, n, s, ev);
    s.melee_hits = melee_hits_;
    // a hit only when something really hit: an attacker, a fall, or a real chunk of health. Small drops with
    // nobody around are the health ring draining (a fortified ring wearing off, an empty core) - not hits.
    if (hurt && !attacker && !IS_PED_FALLING(me) && !IS_PED_RAGDOLL(me)) {
        int max_hp = GET_ENTITY_MAX_HEALTH(me);
        if (last_health_ - health < std::max(1, max_hp * 2 / 100)) {
            LOGD("health %d -> %d: drain, not a hit", last_health_, health);
            hurt = false;
        }
    }
    if (hurt) {
        float amount = clampv(float(last_health_ - health) / 40.0f, 0.15f, 1.0f);
        WorldEvent e{WorldEvent::Damage, 0, amount, "bullet"};
        if (attacker) {
            Vector3 q = GET_ENTITY_COORDS(attacker);
            e.pan = pan_to(q.x, q.y, cam, pos.x, pos.y);
            e.cause = !IS_PED_HUMAN(attacker) ? "animal" : (attacker_dist < 3.0f ? "melee" : "bullet");
        } else if (IS_PED_FALLING(me) || IS_PED_RAGDOLL(me)) {
            e.cause = "fall";
        } else {
            e.cause = "other";
        }
        ev.push_back(e);
    }
    last_health_ = health;

    // --- the game's events (8-byte slots; sizes must match exactly) ---
    {
        static const Hash kCalmPed = 0x89AB08C3;      // calmer, mount, calm type, fully calmed
        static const Hash kPrompt = 0x52AE9189;       // EVENT_PLAYER_PROMPT_TRIGGERED: [0] prompt type (49 brush, 50 feed)
        static const Hash kCalcLoot = 0x834F764A;     // EVENT_CALCULATE_LOOT: [23] looter, [24] looted entity
        static const Hash kLoot = 0xA5E4EAF7;         // EVENT_LOOT: [26] looter, [29] herb (non-zero = a plant)
        static const Hash kLootDone = 0x52063E5B;     // EVENT_LOOT_COMPLETE: [0] looter, [1] entity, [2] success
        static const Hash kPickup = 0xD7092502;       // EVENT_PICKUP_CARRIABLE: [0] carrier, [2] taken from a horse
        static const Hash kStow = 0x4086BF1A;         // EVENT_PLACE_CARRIABLE_ONTO_PARENT: [0] player, [2] horse
        int n_ev = GET_NUMBER_OF_EVENTS(0);
        for (int i = 0; i < n_ev; ++i) {
            Hash type = GET_EVENT_AT_INDEX(0, i);
            alignas(8) uint64_t d[36] = {};
            auto slot = [&](int k) { return int(uint32_t(d[k])); };
            auto life = [&](const char* what) { ev.push_back({WorldEvent::Life, 0, 1, what}); };
            if (type == kCalmPed) {
                if (!GET_EVENT_DATA(0, i, d, 4) || slot(0) != me) continue;
                LOGD("horse calmed (type %d, fully %d)", slot(2), slot(3));
                ev.push_back({WorldEvent::Horse, 0, slot(2) >= 3 ? 1.0f : 0.7f, "calm"});
            } else if (type == kPrompt) {
                if (!GET_EVENT_DATA(0, i, d, 10) || (slot(0) != 49 && slot(0) != 50)) continue;
                care_ = slot(0) == 49 ? "brush" : "feed";
                care_start_ = s.time;
                care_until_ = s.time + 25;
                LOGD("horse care: %s", care_.c_str());
            } else if (type == kCalcLoot) {
                d[1] = 10;                                 // the two reward arrays' lengths, as Rockstar's scripts set them
                d[12] = 10;
                if (!GET_EVENT_DATA(0, i, d, 26) || slot(23) != me) continue;
                if (GET_IS_ANIMAL(slot(24))) {
                    skin_until_ = s.time + 15;
                    LOGD("skinning");
                }
            } else if (type == kLoot) {
                d[1] = 10;
                d[12] = 10;
                if (GET_EVENT_DATA(0, i, d, 36) && slot(26) == me && slot(29) != 0) life("pluck");
            } else if (type == kLootDone) {
                if (GET_EVENT_DATA(0, i, d, 3) && slot(0) == me) skin_until_ = 0;
            } else if (type == kPickup) {
                if (GET_EVENT_DATA(0, i, d, 4) && slot(0) == me) life("heave");
            } else if (type == kStow) {
                if (GET_EVENT_DATA(0, i, d, 6) && slot(0) == me) life("stow");
            }
        }
    }

    // --- camp life: what Arthur has in his hands, and what he is doing ---
    if (s.time - life_poll_t_ > 0.5) {
        life_poll_t_ = s.time;
        auto running = [](const char* script) { return GET_NUMBER_OF_THREADS_RUNNING_THE_SCRIPT_WITH_THIS_HASH(joaat(script)) > 0; };
        smoking_ = running("generic_smoking_item");
        drinking_ = running("generic_alcohol_item") || running("coffee_drinking");
        eating_ = running("generic_multibite_item") || running("stew_eating");
        bathing_ = running("bathing");
    }
    {
        Hash item = GET_ITEM_INTERACTION_STATE(me);
        std::string kind = item_kind(item);
        if (kind.empty() && item) kind = smoking_ ? "smoke" : drinking_ ? "drink" : eating_ ? "eat" : "";
        if (item != last_item_) {
            if (item) LOGD("item in hand: state 0x%08X (%s)", item, kind.empty() ? "?" : kind.c_str());
            last_item_ = item;
        }
        // each bite, sip or puff: the moment the game applies the item's effect
        static const Hash kApplyStat = 0x1A602839;
        if (kind != "clean" && HAS_ANIM_EVENT_FIRED(me, kApplyStat) && s.time - last_apply_t_ > 0.4) {
            last_apply_t_ = s.time;
            ev.push_back({WorldEvent::Life, 0, 1, kind == "smoke" ? "puff" : kind == "eat" ? "bite" : "gulp"});
        }
        if (kind == "clean") s.activity = "clean_gun";
    }
    if (s.time < care_until_) {                            // each brush stroke / mouthful the horse takes
        static const Hash kInteract = 0x8CED1179;
        if (HAS_ANIM_EVENT_FIRED(me, kInteract) && s.time - last_interact_t_ > 0.3) {
            last_interact_t_ = s.time;
            ev.push_back({WorldEvent::Life, 0, 1, care_});
        }
        if (s.time - care_start_ > 1.5 && !IS_ANIMAL_INTERACTION_RUNNING(me)) care_until_ = 0;
    }
    if (s.time < skin_until_) s.activity = "skin";
    if (bathing_) {
        const char* st = GET_TASK_MOVE_NETWORK_STATE(me);
        std::string b = st ? st : "";
        if (b.rfind("Scrub_", 0) == 0 && b != "Scrub_Idle") {
            s.activity = "scrub";
            s.activity_pan = b.find("Left") != std::string::npos ? -0.6f : b.find("Right") != std::string::npos ? 0.6f : 0.0f;
        }
    }
    {
        static const Hash kCraft[] = {joaat("WORLD_PLAYER_DYNAMIC_KNEEL_FIRE_CRAFT"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_FIRE_CRAFT_ACTIVE"),
                                      joaat("WORLD_PLAYER_DYNAMIC_KNEEL_FIRE_CRAFT_CUP"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_KNIFE")};
        static const Hash kCook[] = {joaat("WORLD_PLAYER_DYNAMIC_KNEEL_SEARGRILL1"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_COOKGRILL1"),
                                     joaat("WORLD_PLAYER_DYNAMIC_KNEEL_COOKGRILL2"), joaat("WORLD_PLAYER_DYNAMIC_KNEEL_COOK_KNIFE_ACTIVE_ARTHUR")};
        Hash sc = GET_ACTIVE_DYNAMIC_SCENARIO(me);
        if (sc) {
            for (Hash h : kCraft) if (sc == h) s.activity = "craft";
            for (Hash h : kCook) if (sc == h) s.activity = "cook";
        }
    }

    // --- voice: horse commands, through the game's own actions ---
    {
        static const Hash kSoothe = joaat("INPUT_INTERACT_ANIMAL"), kStop = joaat("INPUT_HORSE_STOP"),
                          kSpur = joaat("INPUT_HORSE_SPRINT");
        int cmd = horse_cmd_.exchange(HorseNone);
        if (cmd == HorseStop) {
            if (horse && s.mount_speed > 0.4f) {
                rein_until_ = s.time + 4.0;
                ev.push_back({WorldEvent::Horse, 0, 1, "rein"});
                LOGI("voice: whoa - reining in at %.1f m/s", s.mount_speed);
            } else {
                LOGI("voice: whoa - not riding a moving horse");
            }
        } else if (cmd == HorseSpur) {
            if (horse) {
                spurs_left_ = clampv(cfg.integer("Voice", "SpurTaps", 2), 1, 6);   // like tapping Cross/A that many times
                next_spur_ = s.time;
                rein_until_ = 0;
                LOGI("voice: faster - spurring at %.1f m/s (horse stamina %d)", s.mount_speed, s.mount_stamina);
            } else {
                LOGI("voice: faster - not riding");
            }
        } else if (cmd == HorseCalm) {
            if (horse) {
                soothe_frames_ = 2;                          // the game's Calm / pat while riding
                LOGI("voice: easy - soothing the horse (agitation %.2f)", GET_PED_MOTIVATION(horse, 3, 0));
            } else {
                Ped h = GET_ACTIVE_HORSE_FOR_PLAYER(pl);
                if (!h) h = GET_LAST_MOUNT(me);
                Vector3 hp = h && DOES_ENTITY_EXIST(h) ? GET_ENTITY_COORDS(h) : Vector3{};
                Vector3 mp = GET_ENTITY_COORDS(me);
                float d = std::hypot(hp.x - mp.x, hp.y - mp.y);
                if (h && DOES_ENTITY_EXIST(h) && !IS_PED_DEAD_OR_DYING(h) && d < 3.5f) {
                    TASK_ANIMAL_INTERACTION(me, h, joaat("Interaction_PositiveShort"), 0, false);
                    LOGI("voice: easy - patting the horse");
                } else {
                    LOGI("voice: easy - no horse close enough");
                }
            }
        }
        if (spurs_left_ > 0 && horse && s.time >= next_spur_) {
            spur_frames_ = 2;
            --spurs_left_;
            next_spur_ = s.time + 0.3;
            ev.push_back({WorldEvent::Horse, 0, 1, "spur"});
        }
        if (!horse) spurs_left_ = 0;
        if (spur_frames_ > 0) {
            SET_CONTROL_VALUE_NEXT_FRAME(0, kSpur, 1.0f);
            --spur_frames_;
        }
        if (soothe_frames_ > 0) {
            SET_CONTROL_VALUE_NEXT_FRAME(0, kSoothe, 1.0f);
            --soothe_frames_;
        }
        if (s.time < rein_until_) {
            if (horse && s.mount_speed > 0.3f) SET_CONTROL_VALUE_NEXT_FRAME(0, kStop, 1.0f);
            else rein_until_ = 0;
        }
    }

    // --- table games: from the game's scripts, the buttons they read and Arthur's hand animations ---
    if (s.time - minigame_poll_t_ > 0.5) {
        minigame_poll_t_ = s.time;
        static const char* const kGames[] = {"", "fillet_sp", "poker_sp", "bjack_sp", "dominoes_sp"};
        int mg = 0;
        for (int i = 1; i <= 4; ++i)
            if (GET_NUMBER_OF_THREADS_RUNNING_THE_SCRIPT_WITH_THIS_HASH(joaat(kGames[i])) > 0) mg = i;
        if (mg != minigame_) LOGI("table game: %s", mg ? kGames[mg] : "none");
        minigame_ = mg;
    }
    s.minigame = minigame_;
    if (minigame_) {
        auto pressed = [](const char* in) {
            Hash a = joaat(in);
            return IS_DISABLED_CONTROL_JUST_PRESSED(0, a) || IS_CONTROL_JUST_PRESSED(0, a);
        };
        auto push = [&](const char* what) { ev.push_back({WorldEvent::Minigame, 0, 1, what}); };
        if (minigame_ == 1) {
            for (const char* k : {"INPUT_MINIGAME_FFF_A", "INPUT_MINIGAME_FFF_B", "INPUT_MINIGAME_FFF_X", "INPUT_MINIGAME_FFF_Y"})
                if (pressed(k)) push("knife");
        } else if (minigame_ == 4 && pressed("INPUT_MINIGAME_DOMINOES_PLAY_TILE")) {
            tile_at_ = s.time + 0.35;                         // the tile reaches the table
        }
        const char* st = GET_TASK_MOVE_NETWORK_STATE(me);
        std::string state = st ? st : "";
        if (state != mg_state_) {
            LOGD("table game: Arthur's hands -> %s", state.c_str());
            auto has = [&](const char* w) { return state.find(w) != std::string::npos; };
            if (minigame_ == 1) {
                if (has("Fail")) push("knife_miss");
            } else if (minigame_ == 2 || minigame_ == 3) {
                if (has("Shuffle")) push("riffle");
                else if (has("Bet")) push("chips");
                else if (state == "Check" || has("Hit")) push("knock");
                else if (has("Fold") || has("Reveal") || has("Peek") || has("HoldCards") || has("Deck") || has("Take") ||
                         has("Flop") || has("Turn") || has("River"))
                    push("card");
            }
            mg_state_ = state;
        }
        if (tile_at_ > 0 && s.time >= tile_at_) {
            push("tile");
            tile_at_ = 0;
        }
    } else {
        mg_state_.clear();
    }

    // --- weather on the hat ---
    s.rain = GET_RAIN_LEVEL();
    s.indoors = GET_INTERIOR_FROM_ENTITY(me) != 0;

    // --- honor: the story scripts count every gain / loss in stats ---
    if (s.time - honor_poll_t_ > 0.2) {
        honor_poll_t_ = s.time;
        auto stat = [](const char* name, int* v) {
            StatId id{joaat(name), 0};
            return STAT_ID_GET_INT(&id, v);
        };
        int cur = 0, pos = 0, neg = 0;
        bool ok = stat("HONOR_CURRENT", &cur) & stat("HONOR_POSITIVE_TOTAL", &pos) & stat("HONOR_NEGATIVE_TOTAL", &neg);
        if (ok && !honor_logged_) {
            LOGI("honor: %d (%d gains, %d losses so far)", cur, pos, neg);
            honor_logged_ = true;
        } else if (!ok && !honor_logged_) {
            LOGI("honor: the stats can't be read - no honor feedback");
            honor_logged_ = true;
        }
        if (ok && honor_ok_) {
            int d = cur - honor_;
            if (pos > honor_pos_ || neg > honor_neg_) {
                bool up = pos > honor_pos_;
                LOGI("honor %s %+d (now %d)", up ? "up" : "down", d, cur);
                ev.push_back({WorldEvent::Honor, 0, clampv(std::abs(d) / 20.0f, 0.4f, 1.0f), up ? "up" : "down"});
            }
        }
        if (ok) {
            honor_ = cur;
            honor_pos_ = pos;
            honor_neg_ = neg;
        }
        honor_ok_ = ok;
    }

    // --- debug: F11 measures at which L2 value the game starts aiming: the L2 the game sees ramps 0..80, each value
    //     held 150 ms, and the game's own aim control / aiming state is logged (stand still, nothing in hand)
    if (log::debug_enabled()) {
        static const Hash kAim = joaat("INPUT_AIM");
        bool f11 = (GetAsyncKeyState(VK_F11) & 0x8000) != 0;
        if (f11 && !probe_down_ && probe_v_ < 0) {
            probe_v_ = 0;
            probe_t_ = s.time;
            input().probe_lt(0);
            LOGI("aim probe: start");
        }
        probe_down_ = f11;
        if (probe_v_ >= 0 && s.time - probe_t_ >= 0.15) {
            LOGI("aim probe: L2 %3d -> aim pressed %d, aim value %.3f, aiming %d, focusing %d", probe_v_,
                 int(IS_CONTROL_PRESSED(0, kAim)), double(GET_CONTROL_NORMAL(0, kAim)), int(IS_PLAYER_FREE_AIMING(pl)),
                 int(IS_PLAYER_FREE_FOCUSING(pl)));
            probe_v_ += 2;
            probe_t_ = s.time;
            if (probe_v_ > 80) {
                probe_v_ = -1;
                LOGI("aim probe: done");
            }
            input().probe_lt(probe_v_);
        }
    }

    // --- the surface under you: F10 shows what it is, F10 again (while shown) changes it ---
    int key = cfg.integer("General", "TeachSurfaceKey", 121);
    bool down = (GetAsyncKeyState(key) & 0x8000) != 0;
    if (down && !teach_down_) {
        Entity who = horse ? horse : me;
        Vector3 c = GET_ENTITY_COORDS(who);
        uint32_t mat = 0;
        std::string now_label = surface_at(c.x, c.y, c.z, who, &mat);
        std::string name = surfaces_.name_of(mat);
        if (name.empty()) {
            char hex[16];
            snprintf(hex, sizeof hex, "0x%08X", mat);
            name = hex;
        }
        char buf[200];
        if (!mat) {
            snprintf(buf, sizeof buf, "No ground under you");
        } else if (s.time < note_until_ && mat == note_material_) {
            snprintf(buf, sizeof buf, "Ground %s = %s   (F10 = next)", name.c_str(), surfaces_.teach(mat, now_label).c_str());
        } else {
            snprintf(buf, sizeof buf, "Ground %s = %s   (F10 again to change)", name.c_str(), now_label.c_str());
        }
        note_ = buf;
        note_until_ = s.time + 3.0;
        note_material_ = mat;
    }
    teach_down_ = down;
    if (s.time < note_until_) {
        BG_SET_TEXT_SCALE(0.45f, 0.45f);
        BG_SET_TEXT_COLOR(255, 225, 170, 235);
        BG_DISPLAY_TEXT(VAR_STRING_LITERAL(note_.c_str()), 0.36f, 0.86f);
    }
    last_tick_ = s.time;

    // --- gyro aim: turn the camera by what the controller turned ---
    float yaw = atomic_take(gyro_yaw_), pitch = atomic_take(gyro_pitch_);
    // only while the right stick rests: setting the camera every frame would override the stick
    if (gyro_enabled && !s.blocked && ((s.free_aim && !s.lock_on) || gyro_wants_always) && !gyro_stick_busy &&
        (std::fabs(yaw) > 1e-4f || std::fabs(pitch) > 1e-4f)) {
        SET_GAMEPLAY_CAM_RELATIVE_HEADING(GET_GAMEPLAY_CAM_RELATIVE_HEADING() + yaw);
        SET_GAMEPLAY_CAM_RELATIVE_PITCH(GET_GAMEPLAY_CAM_RELATIVE_PITCH() + pitch);
    }

    std::lock_guard<std::mutex> l(mu_);
    snap_ = s;
    for (auto& e : ev) events_.push_back(e);
    if (events_.size() > 64) events_.erase(events_.begin(), events_.end() - 64);
}

}  // namespace dsr2
