#include "world.h"
#include "settings_ui.h"

#include "config.h"
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
// A hoof lands when it comes down to the ground after being lifted - by height, which works at any gait
// (at a gallop a planted hoof still slides in the animation, so "comes to rest" misses most of them).
void World::steps(int ped, Limb* limbs, int n, float body_speed, double now, bool horse, std::vector<WorldEvent>& ev) {
    double dt = now - last_tick_;
    if (dt <= 0 || dt > 0.1) dt = 1.0 / 60;
    if (horse) {
        for (int i = 0; i < n; ++i) {
            Limb& L = limbs[i];
            if (L.bone < 0) continue;
            nat::Vector3 p = nat::GET_WORLD_POSITION_OF_ENTITY_BONE(ped, L.bone);
            float gz = 0;
            nat::Hash mat = 0;
            if (!nat::GET_GROUND_Z_AND_MATERIAL(p.x, p.y, p.z + 0.5f, &gz, &mat) || gz == 0) continue;
            float h = p.z - gz;
            if (!L.have_h) {
                L.contact = h;
                L.have_h = true;
            }
            // standing height: the lowest it has been lately (drifts up slowly so slopes and gaits re-learn)
            L.contact = std::min(L.contact + 0.06f * float(dt), h);
            if (h > L.contact + 0.07f) L.lifted = true;
            bool down = h < L.contact + 0.035f;
            if (L.lifted && down && body_speed > 0.4f && now - L.last_plant > 0.1) {
                L.lifted = false;
                L.last_plant = now;
                hoof_times_.push_back(now);
                WorldEvent e{WorldEvent::Hoof, (i % 2) ? 0.25f : -0.25f, clampv(0.3f + body_speed / 11.0f, 0.3f, 1.0f),
                             surface_at(p.x, p.y, p.z, ped)};
                ev.push_back(e);
            }
            L.x = p.x;
            L.y = p.y;
            L.z = p.z;
            L.have = true;
        }
        while (!hoof_times_.empty() && now - hoof_times_.front() > 1.5) hoof_times_.pop_front();
        return;
    }
    float lowest = 1e9f;
    for (int i = 0; i < n; ++i)
        if (limbs[i].bone >= 0 && limbs[i].have) lowest = std::min(lowest, limbs[i].z);
    for (int i = 0; i < n; ++i) {
        Limb& L = limbs[i];
        if (L.bone < 0) continue;
        nat::Vector3 p = nat::GET_WORLD_POSITION_OF_ENTITY_BONE(ped, L.bone);
        if (L.have) {
            float dx = p.x - L.x, dy = p.y - L.y, dz = p.z - L.z;
            float v = std::sqrt(dx * dx + dy * dy + dz * dz) / float(dt);
            float hi = std::max(horse ? 1.6f : 0.9f, 0.55f * body_speed);
            float lo = std::max(horse ? 0.6f : 0.35f, 0.22f * body_speed);
            if (v > hi) L.swinging = true;
            bool low_enough = p.z < lowest + (horse ? 0.25f : 0.12f);
            if (L.swinging && v < lo && low_enough && body_speed > 0.4f && now - L.last_plant > (horse ? 0.12 : 0.2)) {
                L.swinging = false;
                L.last_plant = now;
                WorldEvent e{horse ? WorldEvent::Hoof : WorldEvent::Footstep, 0, 1, surface_at(p.x, p.y, p.z, ped)};
                // which side: feet left/right, hooves around the centre
                e.pan = horse ? ((i % 2) ? 0.25f : -0.25f) : ((i % 2) ? 0.45f : -0.45f);
                float sp = body_speed;
                e.strength = horse ? clampv(0.3f + sp / 11.0f, 0.3f, 1.0f)
                                   : clampv(sp < 2.2f ? 0.35f : sp < 4.8f ? 0.6f : 0.8f, 0.2f, 1.0f) * step_strength_;
                ev.push_back(e);
            }
        }
        L.x = p.x;
        L.y = p.y;
        L.z = p.z;
        L.have = true;
    }
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
    settings_ui_tick(s.time);            // the Settings page's data store, also while no player exists
    Player pl = PLAYER_ID();
    Ped me = PLAYER_PED_ID();
    if (!me || !IS_PLAYER_PLAYING(pl)) {
        std::lock_guard<std::mutex> l(mu_);
        snap_ = s;
        return;
    }
    s.valid = true;
    s.blocked = IS_PAUSE_MENU_ACTIVE() || IS_LOADING_SCREEN_VISIBLE() || IS_SCREEN_FADED_OUT() || !IS_PLAYER_CONTROL_ON(pl);
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
    if (s.armed) {
        int ammo = 0;
        if (GET_AMMO_IN_CLIP(me, &ammo, w)) s.clip = ammo;
        s.clip_max = GET_MAX_AMMO_IN_CLIP(me, w);
        if (cfg.flag("Triggers", "AmmoTypeRecoil", true)) s.kick_mult = ammo_kick(GET_PED_AMMO_TYPE_FROM_WEAPON(me, w));
        if (cfg.flag("Triggers", "ConditionGrit", true)) {
            Entity obj = GET_CURRENT_PED_WEAPON_ENTITY_INDEX(me);
            if (obj) s.grit = clampv(0.6f * GET_WEAPON_DEGRADATION(obj) + 0.4f * GET_WEAPON_DIRT(obj), 0.0f, 1.0f) * 0.5f;
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
    s.shooting = IS_PED_SHOOTING(me);
    s.free_aim = IS_PLAYER_FREE_AIMING(pl);
    s.lock_on = IS_PLAYER_TARGETTING_ANYTHING(pl);
    s.aiming = s.free_aim || s.lock_on;
    s.dead_eye = IS_SPECIAL_ABILITY_ACTIVE(pl);
    // cores: a fortified (gold) core counts as full - never a low-health warning
    bool gold_health = IS_ATTRIBUTE_CORE_OVERPOWERED(me, 0), gold_stamina = IS_ATTRIBUTE_CORE_OVERPOWERED(me, 1);
    int raw_health = GET_ATTRIBUTE_CORE_VALUE(me, 0), raw_stamina = GET_ATTRIBUTE_CORE_VALUE(me, 1);
    s.health_core = gold_health ? 100 : raw_health;
    s.stamina_core = gold_stamina ? 100 : raw_stamina;
    int cores_key = raw_health / 5 * 1000 + raw_stamina / 5 * 10 + gold_health * 2 + gold_stamina;
    if (cores_key != cores_logged_) {
        LOGD("cores: health %d%s, stamina %d%s", raw_health, gold_health ? " (fortified)" : "", raw_stamina,
             gold_stamina ? " (fortified)" : "");
        cores_logged_ = cores_key;
    }
    s.swimming = IS_PED_SWIMMING(me);

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
        Vector3 hp = GET_ENTITY_COORDS(horse);
        s.horse_surface = surface_at(hp.x, hp.y, hp.z, horse);
        if (horse != hooves_horse_) {
            hooves_horse_ = horse;
            bind_limbs(horse, hooves_, 4, kHoofBones, 8);
            hoof_times_.clear();
        }
        s.hoof_bones = hoof_count_ >= 2;
        size_t before = ev.size();
        if (s.hoof_bones) steps(horse, hooves_, hoof_count_, s.mount_speed, s.time, true, ev);
        hoof_plants_ += int(ev.size() - before);
        s.hoof_rate = float(hoof_times_.size()) / 1.5f;
        if (log::debug_enabled() && s.time - hoof_stat_t_ > 3.0) {
            if (s.mount_speed > 1.0f)
                LOGD("hooves: speed %.1f m/s, %.1f plants/s detected", s.mount_speed, hoof_plants_ / (s.time - hoof_stat_t_));
            hoof_plants_ = 0;
            hoof_stat_t_ = s.time;
        }
    }
    s.in_train = IS_PED_IN_ANY_TRAIN(me);
    s.in_vehicle = IS_PED_IN_ANY_VEHICLE(me);
    s.speed = GET_ENTITY_SPEED(me);

    // --- on foot: steps, landings, climbing, doors ---
    if (!s.on_mount && !s.in_vehicle && !s.swimming && !s.blocked) {
        if (me != feet_ped_) {
            feet_ped_ = me;
            bind_limbs(me, feet_, 2, kFootBones, 2);
        }
        bool crouch = GET_PED_CROUCH_MOVEMENT(me), carry = IS_PED_CARRYING_SOMETHING(me);
        step_strength_ = (crouch ? 0.55f : 1.0f) * (carry ? 1.25f : 1.0f);
        steps(me, feet_, 2, s.speed, s.time, false, ev);
        bool air = IS_ENTITY_IN_AIR(me) || IS_PED_FALLING(me);
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

    // --- people around: who shoots, who got hurt by us, who hurt us ---
    int peds[256];
    int n = shv_worldGetAllPeds(peds, 256);
    Ped melee_target = GET_MELEE_TARGET_FOR_PED(me);
    std::map<int, int> seen;
    int attacker = 0;
    float attacker_dist = 1e9f;
    int health = GET_ENTITY_HEALTH(me);
    bool hurt = last_health_ >= 0 && health < last_health_;
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
            if (it != ped_health_.end() && h < it->second && HAS_ENTITY_BEEN_DAMAGED_BY_ENTITY(p, me)) {
                if (d < 3.0f) ++melee_hits_;
                else ev.push_back({WorldEvent::HitConfirm, 0.5f, 1.0f, ""});
            }
        }
        if (hurt && d < attacker_dist && HAS_ENTITY_BEEN_DAMAGED_BY_ENTITY(me, p)) {
            attacker = p;
            attacker_dist = d;
        }
    }
    ped_health_.swap(seen);
    greet(pl, me, pos.x, pos.y, peds, n, s, ev);
    s.melee_hits = melee_hits_;
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
    {
        Hash w1 = 0, w2 = 0;
        float pct = 0;
        GET_CURR_WEATHER_STATE(&w1, &w2, &pct);
        Hash wt = pct > 0.5f ? w2 : w1;
        s.thunder = wt == joaat("THUNDER") || wt == joaat("THUNDERSTORM") || wt == joaat("HURRICANE");
        s.indoors = GET_INTERIOR_FROM_ENTITY(me) != 0;
    }

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
