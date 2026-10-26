"""One-off patch: footfalls from the real legs (player + horse), landings, climbing, doors, surface teaching."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "mod" / "src"
p = ROOT / "world.cpp"
s = p.read_text(encoding="utf-8")

helpers = r'''
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
    std::string surf = surfaces_.classify(mat, indoors, sub, indoors ? 0.0f : nat::GET_SNOW_LEVEL());
    if (mat && !surfaces_.known(mat) && log::debug_enabled() && logged_materials_.insert(mat).second)
        LOGD("ground material 0x%08X -> %s (teach it with F10)", mat, surf.c_str());
    return surf;
}

// A foot (or hoof) that comes to rest in world space has just been planted: that is the step.
void World::steps(int ped, Limb* limbs, int n, float body_speed, double now, bool horse, std::vector<WorldEvent>& ev) {
    double dt = now - last_tick_;
    if (dt <= 0 || dt > 0.1) dt = 1.0 / 60;
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
                                   : clampv(sp < 2.2f ? 0.45f : sp < 4.8f ? 0.7f : 0.9f, 0.3f, 1.0f) * step_strength_;
                ev.push_back(e);
            }
        }
        L.x = p.x;
        L.y = p.y;
        L.z = p.z;
        L.have = true;
    }
}
'''


def rep(a, b):
    global s
    if a not in s:
        raise SystemExit("not found: " + a[:80])
    s = s.replace(a, b, 1)


rep("void World::tick() {", helpers + "\nvoid World::tick() {")

rep("""    s.on_mount = IS_PED_ON_MOUNT(me);
    if (s.on_mount) {
        Ped horse = GET_MOUNT(me);
        if (horse) {
            s.mount_speed = GET_ENTITY_SPEED(horse);
            s.mount_stamina = GET_ATTRIBUTE_CORE_VALUE(horse, 1);
            s.mount_pitch = GET_ENTITY_ROTATION(horse).x;
            s.mount_in_water = IS_ENTITY_IN_WATER(horse);
            Vector3 hp = GET_ENTITY_COORDS(horse);
            float gz = 0;
            Hash mat = 0;
            if (GET_GROUND_Z_AND_MATERIAL(hp.x, hp.y, hp.z + 1.0f, &gz, &mat)) s.ground_material = mat;
        }
    }""", """    if (!surfaces_loaded_) {
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
        }
        s.hoof_bones = hoof_count_ >= 2;
        if (s.hoof_bones) steps(horse, hooves_, hoof_count_, s.mount_speed, s.time, true, ev);
    }""")

rep("""    s.speed = GET_ENTITY_SPEED(me);
""", """    s.speed = GET_ENTITY_SPEED(me);

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
""")

rep("""    // --- people around: who shoots, who got hurt by us, who hurt us ---
    std::vector<WorldEvent> ev;
""", """    // --- people around: who shoots, who got hurt by us, who hurt us ---
""")

rep("""    // --- gyro aim: turn the camera by what the controller turned ---""", """    // --- teach the surface under you (F10 cycles its label) ---
    int key = cfg.integer("General", "TeachSurfaceKey", 121);
    bool down = (GetAsyncKeyState(key) & 0x8000) != 0;
    if (down && !teach_down_) {
        Entity who = horse ? horse : me;
        Vector3 c = GET_ENTITY_COORDS(who);
        uint32_t mat = 0;
        surface_at(c.x, c.y, c.z, who, &mat);
        char buf[160];
        if (mat) snprintf(buf, sizeof buf, "Ground 0x%08X = %s   (F10 = next)", mat, surfaces_.teach(mat).c_str());
        else snprintf(buf, sizeof buf, "No ground under you");
        note_ = buf;
        note_until_ = s.time + 3.0;
    }
    teach_down_ = down;
    if (s.time < note_until_) {
        BG_SET_TEXT_SCALE(0.45f, 0.45f);
        BG_SET_TEXT_COLOR(255, 225, 170, 235);
        BG_DISPLAY_TEXT(VAR_STRING_LITERAL(note_.c_str()), 0.36f, 0.86f);
    }
    last_tick_ = s.time;

    // --- gyro aim: turn the camera by what the controller turned ---""")

p.write_text(s, encoding="utf-8")

h = ROOT / "world.h"
t = h.read_text(encoding="utf-8")
t = t.replace("#include <map>\n", "#include <map>\n#include <set>\n", 1)
t = t.replace("    float crouch_ = 0, carry_ = 0;\n", "    std::set<uint32_t> logged_materials_;\n", 1)
h.write_text(t, encoding="utf-8")

n = ROOT / "natives.h"
u = n.read_text(encoding="utf-8")
u = u.replace("inline bool IS_ENTITY_IN_AIR(Entity e) { return invoke<int>(0x886E37EC497200B6ull, e, 0) != 0; }",
              "inline bool IS_ENTITY_IN_AIR(Entity e) { return invoke<int>(0x886E37EC497200B6ull, e, 0) != 0; }", 1)
n.write_text(u, encoding="utf-8")
print("world patched")
