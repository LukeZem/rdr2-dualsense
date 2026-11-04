// Offline checks of the C++ port against the behaviour verified in the Python lab tests.
#include "catalog.h"
#include "config.h"
#include "dsp.h"
#include "engine.h"
#include "gameaudio.h"
#include "haptics.h"
#include "input.h"
#include "surfaces.h"
#include "settings_menu.h"
#include "log.h"

#include <clocale>
#include <complex>
#include <fstream>
#include <cstdio>
#include <set>

namespace dsr2 {

namespace {

int g_fail = 0, g_pass = 0;
#define CHECK(cond, what)                                                       \
    do {                                                                        \
        if (cond) ++g_pass;                                                     \
        else { ++g_fail; printf("  FAIL %s  (%s:%d)\n", what, __FILE__, __LINE__); } \
    } while (0)

struct Rig {
    WeaponEngine eng;
    double t = 1.0;
    std::vector<EngineFrame> frames;
    std::vector<int> raws;
    GameHints hints;
    bool game_fires = true;
    int last_rt_ = 0, rt_prev_ = 0;
    Rig(const nlohmann::json& p, Settings s = Settings{}) : eng(p, Calibration{}, s, {}) {}
    Rig& feed(const std::vector<int>& rs, uint32_t buttons = 0, int l2 = 0) {
        for (int r : rs) {
            t += 0.004;
            InputState in;
            in.t = t;
            in.r2 = r;
            in.l2 = l2;
            in.buttons = buttons;
            in.fresh = true;
            raws.push_back(r);
            // the game: it fires the frame after it sees R2 go down (when it is in game and wants to fire)
            if (hints.valid && game_fires) hints.shooting = rt_prev_ == 0 && last_rt_ == 255;
            rt_prev_ = last_rt_;
            frames.push_back(eng.update(in, hints));
            last_rt_ = std::max(0, frames.back().game_rt);
        }
        return *this;
    }
    Rig& hold(int raw, double s, int l2 = 0) { return feed(std::vector<int>(size_t(s / 0.004), raw), 0, l2); }
    Rig& pull(int to = 255, int n = 40, int l2 = 0) {
        std::vector<int> v;
        for (int i = 0; i <= n; ++i) v.push_back(to * i / n);
        return feed(v, 0, l2);
    }
    Rig& release(int n = 10, int l2 = 0) { return feed(std::vector<int>(size_t(n), 0), 0, l2); }
    int count(const std::string& cue) const {
        int c = 0;
        for (auto& f : frames) for (auto& q : f.cues) c += q.name == cue;
        return c;
    }
    int shots_rt() const {     // rising edges of the RT the game would see
        int c = 0, prev = 0;
        for (auto& f : frames) { int v = std::max(0, f.game_rt); c += prev == 0 && v == 255; prev = v; }
        return c;
    }
};

}  // namespace

int run_selftests(const fs::path& data) {
    Catalog cat;
    cat.load(data / "weapons.json");
    std::string name;
    nlohmann::json catt = cat.resolve(joaat("WEAPON_REVOLVER_CATTLEMAN"), 0, name);
    CHECK(!catt.is_null() && name == "WEAPON_REVOLVER_CATTLEMAN", "resolve by game hash");
    CHECK(cat.resolve_name("WEAPON_REVOLVER_LEMAT").value("clip", 0) == 9, "tune overrides class (LeMat clip 9)");
    nlohmann::json fb = cat.resolve(0x12345678, joaat("GROUP_REPEATER"), name);
    CHECK(!fb.is_null() && name.find("CARBINE") != std::string::npos, "unknown weapon falls back to its group");

    {   // one shot at the break, none while held, RT jumps 0 -> 255 exactly there
        Settings s; s.manual_action = false;
        Rig r(catt, s);
        r.pull().hold(255, 1.0);
        CHECK(r.shots_rt() == 1, "single shot, no refire while held");
        size_t first = 0;
        while (first < r.frames.size() && r.frames[first].game_rt != 255) ++first;
        CHECK(first < r.frames.size() && r.raws[first] >= r.eng.break_raw() && r.raws[first - 1] < r.eng.break_raw(),
              "shot fires on the first sample past the break");
    }
    {   // single action: the next tap cocks the hammer (aiming, so no fanning)
        Settings s; s.fanning = false;
        Rig r(catt, s);
        r.pull(255, 40, 200).release(125, 200).pull(255, 40, 200);
        CHECK(r.count("hammer_cock") == 1, "second tap cocks the hammer");
        r.release(80, 200).pull(255, 40, 200);
        CHECK(r.count(r.eng.id() + ":shot") + r.count("shot_revolver") == 2, "third tap fires");
    }
    {   // fanning when hip firing
        Rig r(catt);
        r.pull().release(100).pull();
        CHECK(r.count("shot_revolver") == 2, "rapid hip-fire taps fan the hammer");
    }
    {   // lever action
        Rig r(cat.resolve_name("WEAPON_REPEATER_CARBINE"));
        r.pull().release(125).pull().release(80).pull();
        CHECK(r.count("lever_open") == 1 && r.count("lever_close") == 1 && r.count("shot_repeater") == 2, "lever cycles between shots");
    }
    {   // empty double barrel: dry click
        Rig r(cat.resolve_name("WEAPON_SHOTGUN_DOUBLEBARREL"));
        for (int i = 0; i < 2; ++i) r.pull().release(100);
        r.pull();
        CHECK(r.count("dry_fire") == 1, "dry click when empty");
    }
    {   // game data: reloading switches the trigger off; game clip 0 = empty
        Rig r(catt);
        r.hints.valid = true;
        r.hints.reloading = true;
        r.feed({0, 0});
        CHECK(r.frames.back().state == "reloading" && r.frames.back().r2[0] == fx::OFF, "game reload: trigger slack");
        r.hints.reloading = false;
        r.hints.clip = 0;
        r.feed({0}).pull();
        CHECK(r.count("dry_fire") == 1, "game says empty: dry click");
    }
    {   // fishing from the game's fishing task: bite on R2, line tension on L2, the fight, the catch
        Rig r(cat.resolve_name("WEAPON_FISHINGROD"));
        r.hints.valid = true;
        FishingState& fs = r.hints.fishing;
        fs.active = true;
        fs.state = 6;
        r.hold(0, 0.1);
        CHECK(r.frames.back().r2[0] != fx::OFF && r.count("fish_bite") == 0, "line in the water: R2 light, no bite yet");
        fs.weight_lb = 3.5f;
        r.hold(0, 0.1);
        CHECK(r.count("fish_bite") == 1 && r.frames.back().r2 == fx::vibration(2, 7, 9), "a fish takes the bait: R2 tugs");
        fs.state = 7;
        fs.tension = 0.5f;
        fs.struggle = 1;
        fs.side = 0.9f;
        r.hold(0, 1.0);
        bool right = false;
        for (auto& fr : r.frames) for (auto& c : fr.cues) right |= c.name == "fish_tug" && c.has_pan && c.pan > 0.5f;
        CHECK(r.count("fish_hooked") == 1 && r.frames.back().l2 == fx::feedback(0, 5), "hooked: L2 holds the line tension");
        CHECK(right, "the fish surges to its side (right)");
        fs.tension = 0.95f;
        r.hold(0, 0.05);
        CHECK(r.frames.back().l2 == fx::vibration(0, 8, 30), "about to snap: L2 strains");
        fs.state = 6;
        fs.weight_lb = 0;
        r.hold(0, 0.05);
        CHECK(r.count("line_snap") == 1, "snapped at high tension");
        fs.state = 7; fs.tension = 0.3f;
        r.hold(0, 0.3);
        fs.state = 12;
        r.hold(0, 2.0);
        CHECK(r.count("fish_landed") == 1 && r.count("fish_flop") >= 1, "landed: it flaps in your hand");
    }
    {   // Dead Eye: marks tick, and each shot of the volley kicks when the game fires it
        Rig r(cat.resolve_name("WEAPON_REVOLVER_CATTLEMAN"));
        r.hints.valid = true;
        r.hints.dead_eye = true;
        r.hints.clip = 6;
        r.hold(0, 0.1);
        r.hints.deadeye_marks = 1; r.hold(0, 0.1);
        r.hints.deadeye_marks = 2; r.hold(0, 0.1);
        CHECK(r.count("deadeye_mark") == 2, "two targets painted: two ticks");
        int before = r.count("shot_revolver");
        for (int i = 0; i < 3; ++i) {               // the game fires the volley by itself
            r.hints.clip -= 1;
            r.hints.shooting = true;
            r.hold(0, 0.02);
            r.hints.shooting = false;
            r.hold(0, 0.25);
        }
        CHECK(r.count("shot_revolver") - before == 3, "every volley shot kicks");
    }
    {   // ini numbers read the same whatever locale the game switches to (it uses a decimal comma)
        fs::path tmp = fs::temp_directory_path() / "dsr2_locale_test.ini";
        { std::ofstream o(tmp); o << "[Gyro]\nVerticalRatio=0.75\n[Voice]\nMinConfidence=0,7\n"; }
        const char* prev = setlocale(LC_ALL, nullptr);
        std::string saved = prev ? prev : "C";
        bool comma_locale = setlocale(LC_ALL, "Russian") != nullptr;
        Config cfg;
        cfg.load(tmp.wstring());
        CHECK(std::fabs(cfg.num("Gyro", "VerticalRatio", 9) - 0.75f) < 1e-4f &&
              std::fabs(cfg.num("Voice", "MinConfidence", 9) - 0.7f) < 1e-4f, "0.75 / 0,7 read right under a comma locale");
        if (!comma_locale) printf("  (note: Russian locale not available, tested in the C locale)\n");
        setlocale(LC_ALL, saved.c_str());
        fs::remove(tmp);
    }
    {   // the settings page writes the ini in place: comments and order kept, missing keys added, read back
        fs::path tmp = fs::temp_directory_path() / "dsr2_set_test.ini";
        { std::ofstream o(tmp); o << "; top comment\n[Haptics]\n; how strong\nFootsteps=0.22\n\n[Gyro]\nMode=off\n"; }
        Config cfg;
        cfg.load(tmp.wstring());
        const MenuEntry* steps = nullptr; const MenuEntry* gyro = nullptr; const MenuEntry* trig = nullptr;
        for (auto& e : SettingsMenu::entries()) {
            if (std::string(e.key) == "Footsteps") steps = &e;
            if (std::string(e.key) == "Mode") gyro = &e;
            if (std::string(e.section) == "Triggers" && std::string(e.key) == "Enabled") trig = &e;
        }
        CHECK(steps && gyro && trig, "settings page lists footsteps, gyro, triggers");
        CHECK(SettingsMenu::value_text(*steps, cfg) == "22%", "footsteps shows 22%");
        cfg.set("Haptics", "Footsteps", SettingsMenu::stepped(*steps, cfg, +1));
        CHECK(SettingsMenu::value_text(*steps, cfg) == "30%", "right: 22% -> 30% (on the 10% grid)");
        cfg.set("Gyro", "Mode", SettingsMenu::stepped(*gyro, cfg, +1));
        cfg.set("Triggers", "Enabled", SettingsMenu::stepped(*trig, cfg, -1));
        CHECK(cfg.str("Gyro", "Mode", "") == "aim" && !cfg.flag("Triggers", "Enabled", true), "choice and new section written");
        std::ifstream in(tmp);
        std::string all((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
        CHECK(all.find("; top comment") != std::string::npos && all.find("; how strong") != std::string::npos &&
              all.find("Footsteps=0.3") != std::string::npos && all.find("[Triggers]") != std::string::npos,
              "comments kept, value replaced in place, section appended");
        for (int i = 0; i < 30; ++i) {
            std::string v = SettingsMenu::stepped(*steps, cfg, -1);
            if (v.empty()) break;
            cfg.set("Haptics", "Footsteps", v);
        }
        CHECK(SettingsMenu::value_text(*steps, cfg) == "Off", "left all the way: Off, then stops");
        in.close();
        fs::remove(tmp);
    }
    {   // the in-game page: toggles and choices = option steppers (index), levels = whole percents
        Config cfg;
        std::set<std::string> ids;
        const MenuEntry* steps = nullptr; const MenuEntry* strength = nullptr; const MenuEntry* gyro = nullptr;
        const MenuEntry* trig = nullptr;
        bool ok = true;
        for (auto& e : SettingsMenu::entries()) {
            if (e.kind == MenuEntry::Header) continue;
            ok = ok && ids.insert(e.id).second &&
                 (e.kind == MenuEntry::Number) == SettingsMenu::option_labels(e).empty();
            if (std::string(e.key) == "Footsteps") steps = &e;
            if (std::string(e.section) == "Haptics" && std::string(e.key) == "Strength") strength = &e;
            if (std::string(e.key) == "Mode") gyro = &e;
            if (std::string(e.section) == "Triggers" && std::string(e.key) == "Enabled") trig = &e;
        }
        CHECK(ok && steps && strength && gyro && trig, "page rows: unique ids, options only for toggles / choices");
        CHECK(SettingsMenu::page_max(*steps) == 100 && SettingsMenu::page_max(*strength) == 200, "levels: 0 .. max %");
        CHECK(SettingsMenu::page_value(*steps, cfg) == 35, "footsteps default 0.35 shows as exactly 35%");
        CHECK(SettingsMenu::page_ini(*steps, 37) == "0.37" && SettingsMenu::page_ini(*strength, 200) == "2" &&
              SettingsMenu::page_ini(*steps, 0) == "0", "percent -> ini value");
        CHECK(SettingsMenu::page_ini(*steps, 101).empty() && SettingsMenu::page_ini(*steps, -1).empty(),
              "out of range -> nothing");
        CHECK(SettingsMenu::option_labels(*gyro) == std::vector<std::string>({"DS_GYRO_MODE_OFF", "DS_GYRO_MODE_AIM"}) &&
              SettingsMenu::page_ini(*gyro, 1) == "aim" && SettingsMenu::page_ini(*gyro, 2).empty(), "choice options");
        CHECK(SettingsMenu::page_value(*trig, cfg) == 1 && SettingsMenu::page_ini(*trig, 0) == "0", "toggle 0 / 1");
    }
    {   // double action: every quick press reaches the game, whatever its "ready to shoot" says
        Settings st; st.manual_action = false;
        Rig r(cat.resolve_name("WEAPON_REVOLVER_DOUBLEACTION"), st);
        r.hints.valid = true;
        r.hints.hip_fire = false;
        r.hints.ready = false;                      // false for 1.5 s and more after a shot in the real game
        r.pull(255, 80);
        r.release(150).pull(255, 80);
        r.release(150).pull(255, 80);
        CHECK(r.count("shot_revolver") == 3, "three quick presses, three shots, not ready or not");
        r.release(10).pull(190, 30).hold(190, 0.1);
        CHECK(r.count("shot_revolver") == 4, "a quick follow-up needs no full pull");
    }
    {   // from the hip and with two guns the game cycles single-action guns itself: no R2 stroke of ours
        for (int mode = 0; mode < 2; ++mode) {
            Rig r(cat.resolve_name("WEAPON_REVOLVER_CATTLEMAN"));
            r.hints.valid = true;
            r.hints.hip_fire = mode == 0;
            r.hints.dual_wield = mode == 1;
            r.hints.ready = false;
            r.pull(255, 80);
            r.release(40).pull(255, 80);
            CHECK(r.count("hammer_cock") == 0, "no hammer stroke from the hip / with two guns");
            CHECK(r.frames.back().state != "action" && r.frames.back().state != "cycling", "never waits for a stroke");
        }
    }
    {   // the game's readiness decides cocking: not ready -> the next stroke works the lever
        Rig r(cat.resolve_name("WEAPON_REPEATER_CARBINE"));
        r.hints.valid = true;
        r.hints.hip_fire = false;
        r.pull();
        r.hints.ready = false;
        r.release(40);
        CHECK(r.frames.back().state == "action", "not ready after a shot: lever stroke next");
        r.pull();
        CHECK(r.count("lever_open") == 1 && r.count("shot_repeater") == 1, "the stroke works the lever, no shot");
        r.hints.ready = true;                       // the game: lever closed, chambered
        r.release(20).pull();
        CHECK(r.count("shot_repeater") == 2, "ready again: fires");
    }
    {   // the game cocks it by itself (auto-cock mod, aiming): skip the stroke
        Rig r(cat.resolve_name("WEAPON_REVOLVER_CATTLEMAN"));
        r.hints.valid = true;
        r.hints.hip_fire = false;
        r.pull(255, 40, 200);
        r.hints.ready = false;
        r.release(40, 200);
        r.hints.ready = true;
        r.release(5, 200).pull(255, 40, 200);
        CHECK(r.count("hammer_cock") == 0 && r.count("shot_revolver") == 2, "game-cocked: fires without a stroke");
    }
    {   // in game the kick comes with the game's real shot; a press the game refuses gets no kick
        Rig r(cat.resolve_name("WEAPON_REVOLVER_CATTLEMAN"));
        r.hints.valid = true;
        r.game_fires = false;
        r.pull();
        r.hold(255, 2.0);
        CHECK(r.count("shot_revolver") == 0 && r.count("reset_click") >= 1, "refused shot: the sear clicks, no kick");
        Rig q(cat.resolve_name("WEAPON_REVOLVER_CATTLEMAN"));
        q.hints.valid = true;
        q.pull();
        q.hold(255, 0.3);
        CHECK(q.count("shot_revolver") == 1, "the game fires: the kick comes");
    }
    {   // recoil: a shove against the finger first, then the fading rumble
        Settings s; s.manual_action = false;
        Rig r(cat.resolve_name("WEAPON_SHOTGUN_DOUBLEBARREL"), s);
        r.pull().hold(255, 0.3);
        std::vector<uint8_t> modes;
        for (auto& f : r.frames) if (f.state == "held") modes.push_back(f.r2[0]);
        auto first_vib = std::find(modes.begin(), modes.end(), fx::VIBRATION);
        CHECK(first_vib != modes.end() && first_vib != modes.begin() && *(first_vib - 1) == fx::FEEDBACK,
              "shove (feedback) right before the rumble (vibration)");
        CHECK(std::count(modes.begin(), modes.end(), fx::VIBRATION) >= 25, "rumble lasts ~100 ms+");
    }
    {   // bow
        Rig r(cat.resolve_name("WEAPON_BOW"));
        r.pull(200, 10).hold(200, 1.2).release();
        CHECK(r.count("bow_release") == 1, "bow fires on release after a full draw");
    }
    {   // melee without the game: L2 = target
        nlohmann::json fist = cat.resolve_name("WEAPON_UNARMED");
        fist["melee"]["block_chance"] = 0;
        Rig r(fist);
        r.feed({0}, R1, 200).release(100, 200).feed({0}, R1, 200).release(100, 200).feed({0}, R1, 200).release(100, 200);
        CHECK(r.count("punch_finisher") == 1, "third hit in a row is a finisher");
        Rig m(fist);
        m.feed({0}, R1).release(100);
        CHECK(m.count("punch_miss") == 1, "swing at air is a miss");
    }
    {   // melee in game: the hit comes from real damage
        Rig r(cat.resolve_name("WEAPON_UNARMED"));
        r.hints.valid = true;
        r.hints.hip_fire = false;
        r.feed({0}, R1).release(20);
        r.hints.melee_hits = 1;
        r.release(5);
        CHECK(r.count("punch_impact") + r.count("punch_impact_face") == 1, "game damage confirms the punch");
    }
    {   // DSP: converted gunshot keeps its energy where the actuators work
        std::vector<float> shot(44100 * 8 / 10);
        Rng rng(1);
        for (size_t i = 0; i < shot.size(); ++i) shot[i] = rng.gauss() * std::exp(-float(i) / 44100 / 0.08f);
        Stereo h = dsp::to_haptic(shot, 44100, dsp::preset("handgun"), 0.5f, 1.0f);
        size_t n = 1;
        while (n < h.size() / 2) n <<= 1;
        std::vector<std::complex<float>> a(n);
        for (size_t i = 0; i < h.size() / 2; ++i) a[i] = h[2 * i + 1];
        dsp::fft(a);
        double lo = 0, hi = 0;
        for (size_t k = 1; k < n / 2; ++k) (k * 48000.0 / n > 500 ? hi : lo) += std::abs(a[k]);
        CHECK(hi / (lo + hi) < 0.12, "haptic energy stays below 500 Hz");
        auto k = dsp::kick_steps(shot, 44100, 16);
        CHECK(!k.empty() && k[0] == 8 && std::is_sorted(k.rbegin(), k.rend()), "recoil envelope decays");
    }
    {   // recipes render; speaker fallback is audible
        HapticLibrary lib;
        lib.load(data / "haptics.json", nullptr);
        Stereo out;
        Cue c;
        c.name = "hammer_cock";
        CHECK(lib.render(c, out) && out.size() > 100, "recipe renders");
        CHECK(lib.speaker_sound(c, out) && out.size() > 100, "speaker sound for a mechanism");
        for (const char* r : {"hoof_dirt", "hoof_stone", "rail_clack", "hit_bullet", "gunfire_near", "shiver", "horse_heartbeat",
                              "land", "climb_grab", "door_open"}) {
            c.name = r;
            CHECK(lib.render(c, out), r);
        }
        // every surface the world can report has a footstep and a hoof recipe
        for (const auto& surf : Surfaces::labels()) {
            c.name = "step_" + surf;
            CHECK(lib.render(c, out), c.name.c_str());
            c.name = "hoof_" + surf;
            CHECK(lib.render(c, out), c.name.c_str());
        }
    }
    {   // surface teaching: cycles labels, persists, context fallbacks
        fs::path tmp = fs::temp_directory_path() / "dsr2_materials_test.json";
        fs::remove(tmp);
        Surfaces s;
        s.load(tmp);
        CHECK(s.classify(0x1234, false, 0, 0) == "ground", "unknown ground outdoors");
        CHECK(s.classify(0x1234, true, 0, 0) == "wood", "indoors = floorboards");
        CHECK(s.classify(0x1234, false, 0.3f, 0) == "water", "wading = water");
        CHECK(s.classify(0x1234, false, 0, 0.8f) == "snow", "snow on the ground");
        CHECK(s.teach(0x1234, "ground") == "grass" && s.teach(0x1234, "grass") == "mud", "F10 cycles labels");
        Surfaces again;
        again.load(tmp);
        CHECK(again.classify(0x1234, true, 0, 0) == "mud", "taught label saved and wins over context");
        fs::remove(tmp);
    }
    {   // ground materials: joaat("<name>_<line in materials.dat>")
        CHECK(joaat("default_0") == 0x962C3F7B && joaat("concrete_1") == 0x46CA81E8, "material hash scheme (GTA V pairs)");
        struct { uint32_t h; const char* name; const char* label; } seen[] = {
            {0x962C3F7B, "default_0", "ground"}, {0x15620571, "gravel_small_26", "gravel"},
            {0xB760A3D3, "gravel_dirt_32", "gravel"}, {0x4FB3BD53, "gravel_grass_33", "gravel"},
            {0x98D6E803, "dirt_track_34", "ground"}, {0xB77A074A, "dirt_grass_36", "ground"},
            {0x99F95379, "mud_hard_37", "ground"}, {0x4FD0CB17, "mud_soft_39", "mud"},
            {0x7A630E3B, "mud_deep_41", "mud"}, {0x1C028F83, "clay_hard_46", "ground"},
            {0x8FB48DA9, "grass_dead_53", "grass"}, {0x9AA99348, "grass_56", "grass"},
            {0xDD7EE301, "grass_short_57", "grass"}, {0x68758D7D, "pine_needles_63", "grass"},
            {0x8EA8779E, "leaves_dry_64", "grass"}, {0x48F70312, "wood_roof_91", "wood"},
            {0x1CC71ECE, "wood_solid_medium_96", "wood"},
        };
        int ok = 0;
        for (auto& e : seen) {
            std::string n = Surfaces::identify(e.h);
            if (n == e.name && Surfaces::label_for(n) == e.label) ++ok;
            else LOGW("material 0x%08X: got '%s' (%s), want %s", e.h, n.c_str(), Surfaces::label_for(n).c_str(), e.name);
        }
        CHECK(ok == int(std::size(seen)), "the 17 materials seen in game are identified and labelled");
        double t1 = now_s();
        CHECK(Surfaces::identify(0x00001234).empty(), "an unknown hash stays unknown");
        LOGI("material search: %.1f ms per unknown hash", (now_s() - t1) * 1000);
        CHECK(Surfaces::label_for("mud_underwater_40") == "water" && Surfaces::label_for("snow_loose_20") == "snow" &&
              Surfaces::label_for("sandstone_9") == "stone" && Surfaces::label_for("sand_wet_15") == "sand" &&
              Surfaces::label_for("carpet_fabric_80") == "ground", "material names -> surfaces");
        Surfaces s;
        s.classify(0x4FD0CB17, false, 0, 0);                // first sight: identified in the background
        for (int i = 0; i < 200 && s.name_of(0x4FD0CB17).empty(); ++i) Sleep(10);
        CHECK(s.classify(0x4FD0CB17, false, 0, 0) == "mud", "mud_soft under the boots = mud");
        CHECK(s.classify(0x4FD0CB17, false, 0, 0.8f) == "snow", "snow on top of it = snow");
    }
    {   // the XInput hook, exactly as the game calls it
        CHECK(input().install_hook(), "hook xinput9_1_0");
        using GetFn = DWORD(WINAPI*)(DWORD, XINPUT_STATE*);
        using SetFn = DWORD(WINAPI*)(DWORD, XINPUT_VIBRATION*);
        HMODULE x = GetModuleHandleW(L"xinput9_1_0.dll");
        auto get = reinterpret_cast<GetFn>(GetProcAddress(x, "XInputGetState"));
        auto set = reinterpret_cast<SetFn>(GetProcAddress(x, "XInputSetState"));
        InputState s;
        s.buttons = CROSS | DPAD_LEFT;
        s.r2 = 120;
        s.l2 = 77;
        s.lx = 255;
        s.ly = 0;
        input().publish(s, 255, true);
        XINPUT_STATE st{};
        CHECK(get(0, &st) == ERROR_SUCCESS, "pad 0 connected");
        CHECK((st.Gamepad.wButtons & XINPUT_GAMEPAD_A) && (st.Gamepad.wButtons & XINPUT_GAMEPAD_DPAD_LEFT), "buttons mapped");
        CHECK(st.Gamepad.bRightTrigger == 255 && st.Gamepad.bLeftTrigger == 77, "RT from the engine, LT raw");
        CHECK(st.Gamepad.sThumbLX > 32000 && st.Gamepad.sThumbLY > 32000, "stick up/right");
        CHECK(get(1, &st) == ERROR_DEVICE_NOT_CONNECTED, "other pads hidden");
        input().inject(XINPUT_GAMEPAD_DPAD_UP, 0.2);
        input().publish(s, -1, true);
        get(0, &st);
        CHECK((st.Gamepad.wButtons & XINPUT_GAMEPAD_DPAD_UP) && st.Gamepad.bRightTrigger == 120, "whistle injection, RT passthrough");
        XINPUT_VIBRATION v{65535, 32768};
        CHECK(set(0, &v) == ERROR_SUCCESS && input().rumble_low() > 0.99f && input().rumble_high() > 0.49f, "game rumble captured");
    }
    printf("selftest: %d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}

}  // namespace dsr2
