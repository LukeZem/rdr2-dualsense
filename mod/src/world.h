// Game state, read every frame on the ScriptHook script thread and published as a snapshot
// for the controller thread. Read-only towards the game, except the gameplay camera (gyro aim)
// and the small on-screen note shown while teaching a surface.
#pragma once

#include "common.h"
#include "dialogue.h"
#include "surfaces.h"

#include <deque>
#include <fstream>
#include <map>
#include <set>

namespace dsr2 {

struct GameSnapshot {
    bool valid = false;            // in game, player exists
    bool menu = false;             // a menu is open (pause, satchel, map, catalog...)
    bool blocked = true;           // pause menu, loading, fade, cutscene / no control: no triggers, no actions
    bool halted = true;            // pause menu, loading, fade: no effects at all (cutscenes are NOT halted: the
                                   // world keeps moving - steps, hooves, shots and hits are felt there too)
    bool cutscene = false;         // no control, but the world runs (cutscene / scripted moment)
    uint32_t weapon = 0, group = 0;
    bool armed = false;
    int clip = -1, clip_max = -1;
    bool reloading = false, shooting = false, aiming = false;
    bool free_aim = false, lock_on = false;   // aiming freely / the game's aim assist holds a target
    bool dead_eye = false;
    int health_core = 100, stamina_core = 100;   // health_core: real health in % (100 when fortified)
    float grit = 0, kick_mult = 1, tremor = 0;
    bool on_mount = false;
    float mount_speed = 0, mount_pitch = 0;
    int mount_stamina = 100;
    std::string horse_surface = "ground";
    bool hoof_bones = false;       // the horse's leg bones were found
    float hoof_rate = 0;           // real hoof contacts per second over the last 1.5 s
    bool in_train = false, in_vehicle = false;
    float speed = 0;
    bool swimming = false;
    float wade = 0, horse_wade = 0;          // how deep in water (0..1 of the body: Arthur / the horse)
    bool foliage = false, horse_foliage = false;   // pushing through bushes (the game's own ped blackboard)
    float foliage_height = 0, horse_foliage_height = 0;
    float temperature = 15;
    bool wanted = false;
    int hour = 12;
    uint32_t weather = 0;
    bool lantern = false;
    bool wheel = false;            // weapon / item wheel open
    uint32_t wheel_item = 0;          // the item highlighted in the wheel (0 when closed)
    bool ready = true;             // the game: the gun in hand can fire right now (cooldown over, cocked)
    bool holstering = false;       // a weapon is going into / coming out of the holster
    int attach_point = -1;         // where the weapon in hand is carried otherwise (GET_DEFAULT_WEAPON_ATTACH_POINT)
    bool dual_wield = false;       // a second gun in the off hand
    FishingState fishing;
    int deadeye_marks = 0;         // targets painted in Dead Eye
    int minigame = 0;              // 1 five finger fillet, 2 poker, 3 blackjack, 4 dominoes
    float rain = 0;                // 0..1
    bool indoors = false;
    std::string activity;          // clean_gun, skin, scrub, craft, cook (a texture while it lasts)
    float activity_pan = 0;
    bool lasso_attached = false;
    float lasso_pull = 0;
    int melee_hits = 0;
    bool melee_target_near = false;
    double time = 0;
};

struct WorldEvent {
    enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack, Honor, Minigame, Horse, Life, Explosion } type;
    float pan = 0;          // -1 left .. +1 right (relative to the camera / which foot)
    float strength = 1;     // 0..1
    std::string cause;      // damage: bullet melee animal fall; steps/hooves: surface
};

class World {
public:
    void tick();                                     // script thread, every frame
    // hoof diagnostics (debug log)
    int hoof_plants_ = 0;
    int foot_plants_ = 0;                // debug: steps felt since foot_stat_t_
    bool foliage_logged_ = false, horse_foliage_logged_ = false;
    void bush_probe(int me);
    int bush_handle_ = 0, bush_flag_i_ = 0;  // research probe: capsule tests against vegetation
    std::map<int, bool> bush_hit_;
    std::string weather_set_;            // testing: the SetWeather last applied
    bool explosion_on_ = false;           // an explosion within 150 m right now
    double explosion_t_ = -10;
    std::string foot_surface_ = "-";
    bool last_ready_ = true;
    int fish_log_state_ = -1;
    int cores_logged_ = -1;
    bool menu_logged_ = false;
    // honor (story-mode stats)
    double honor_poll_t_ = 0;
    int honor_ = 0, honor_pos_ = -1, honor_neg_ = -1;
    bool honor_ok_ = false, honor_logged_ = false;
    int marks_logged_ = 0;
    // voice horse commands
    int soothe_frames_ = 0, spur_frames_ = 0, spurs_left_ = 0;
    double next_spur_ = 0;
    double rein_until_ = 0;
    // table games
    int minigame_ = 0;
    double minigame_poll_t_ = 0, tile_at_ = 0;
    std::string mg_state_;
    // camp life
    double life_poll_t_ = 0, last_apply_t_ = 0, last_interact_t_ = 0, care_until_ = 0, care_start_ = 0, skin_until_ = 0;
    bool smoking_ = false, drinking_ = false, eating_ = false, bathing_ = false;
    uint32_t last_item_ = 0;
    std::string care_;
    double ready_change_t_ = 0;
    double hoof_stat_t_ = 0, foot_stat_t_ = 0;
    GameSnapshot snapshot();
    std::vector<WorldEvent> take_events();
    void add_gyro(float yaw_deg, float pitch_deg);
    void request_greet() { greet_requested_ = true; }   // any thread (voice recognizer)
    enum HorseCommand { HorseNone, HorseCalm, HorseStop, HorseSpur };
    void request_horse(HorseCommand c) { horse_cmd_ = c; }   // any thread (voice recognizer)
    bool gyro_wants_always = false;
    bool gyro_enabled = false;
    std::atomic<bool> gyro_stick_busy{false};

private:
    struct Limb {                               // a hoof or a foot (World::steps)
        int bone = -1;
        double last_plant = 0, last_td = 0, last_seen = -10, reset_t = 0;   // felt / any touchdown / tracked / restarted
        float good_gz = 0, held = 0;            // the last plausible ground under it, how long it has been held
        bool have_gz = false, have_h = false;
        int td = 0;                             // touchdown: 0 after one, 1 rose enough, 2 falling
        float hi = 0, low = 0, last_low = 0, prev_h = 0, swing = 0.2f;
    };
    float pan_to(float x, float y, float cam_heading, float px, float py) const;
    void steps(int ped, Limb* limbs, int n, float body_speed, double now, bool horse, std::vector<WorldEvent>& ev);
    bool limb_height(Limb& L, float x, float y, float z, float dt, float& h, float& raw_gz);
    static bool touchdown(Limb& L, float h, float dt, float rise_min, float stop, float margin, float swing_max);
    void record_limbs(const char* mode, int n, const float* x, const float* y, const float* z, const float* gz,
                      const bool* plant, float speed, double now);
    bool limb_probe_ = false;             // research: record limb heights (General.Probes + Debug)
    std::ofstream limb_csv_;
    long limb_lines_ = 0;
    void bind_limbs(int ped, Limb* limbs, int n, const char* const* names, int names_n);
    std::string surface_at(float x, float y, float z, int ped, uint32_t* mat_out = nullptr);

    std::mutex mu_;
    GameSnapshot snap_;
    std::vector<WorldEvent> events_;
    int last_health_ = -1;
    std::map<int, int> ped_health_;
    std::map<int, double> ped_shot_t_;
    // speech probe (debug log only): per ped speaking state, to map spoken lines to the speech files
    struct Talk { bool on = false; uint32_t last = 0; double t0 = 0; };
    std::map<int, Talk> talk_;
    bool convo_ = false;
    int blocked_why_ = 0;
    struct Req { uint32_t state = 0, type = 0; double seen = 0; uintptr_t snd = 0; double snd_t = 0; };
    std::map<uintptr_t, Req> reqs_;   // speech request probe (debug): requests seen, by address
    std::vector<Dialogue::Talker> talkers_;   // speech vibration: who near is talking this frame
    struct Scene { uintptr_t obj = 0; double logged = 0; };
    std::map<int, Scene> scenes_;     // anim scene probe (debug): scenes by handle
    double scene_poll_t_ = 0;
public:
    float frame_time() const;
private:
    void scene_probe(int me, double now);
    void speech_req(int ped, double now);
    void speech_req_prune(double now);
    void speech_probe(int me, const int* peds, int n, float px, float py, float pz, float cam, double now);
    int melee_hits_ = 0;
    std::atomic<float> gyro_yaw_{0}, gyro_pitch_{0};
    // bodies
    Surfaces surfaces_;
    bool surfaces_loaded_ = false;
    int feet_ped_ = 0, hooves_horse_ = 0;
    Limb feet_[2], hooves_[4];
    int hoof_count_ = 0;
    std::deque<double> hoof_times_;
    double last_tick_ = 0, air_time_ = 0;
    bool was_climbing_ = false, was_door_ = false;
    float step_strength_ = 1;
    float last_step_t_ = 0;
    // teaching note
    bool teach_down_ = false;
    bool probe_down_ = false;
    bool dual_logged_ = false;
    int probe_v_ = -1;              // aim probe: the L2 value being shown to the game (-1 = not running)
    double probe_t_ = 0;
    std::string note_;
    double note_until_ = 0;
    uint32_t note_material_ = 0;
    // voice greeting
    void greet(int pl, int me, float px, float py, const int* peds, int n, const GameSnapshot& s,
               std::vector<WorldEvent>& ev);
    bool speak(int ped, const std::vector<std::string>& lines, int listener, std::string* used);
    std::atomic<bool> greet_requested_{false};
    std::atomic<int> horse_cmd_{HorseNone};
    void speech_greet(int me, int target, const GameSnapshot& s, std::vector<WorldEvent>& ev);
    int reply_target_ = 0;
    double reply_at_ = 0, last_greet_ = -10;
    // real greeting through the game's interaction actions (counts for honor)
    enum class Greet { Idle, Turn, Lock, Press, Hold } greet_ = Greet::Idle;
    int greet_target_ = 0;
    double greet_t_ = 0, lock_t_ = 0;
    float greet_from_ = 0;
    int press_frames_ = 0;
};

World& world();

}  // namespace dsr2
