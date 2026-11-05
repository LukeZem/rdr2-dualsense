// The game functions the mod reads (hashes from alloc8or's RDR3 native DB). Read-only except the
// gameplay camera (gyro aim). Only call from the ScriptHook script thread.
#pragma once

#include "shv.h"

namespace dsr2::nat {

using namespace dsr2::shv;

inline Player PLAYER_ID() { return invoke<Player>(0x217E9DC48139933Dull); }
inline Ped PLAYER_PED_ID() { return invoke<Ped>(0x096275889B8E0EE0ull); }
inline bool IS_PLAYER_PLAYING(Player p) { return invoke<int>(0xBFFB35986CAAE58Cull, p) != 0; }
inline bool IS_PLAYER_CONTROL_ON(Player p) { return invoke<int>(0x7964097FCE4C244Bull, p) != 0; }
inline bool IS_PLAYER_FREE_AIMING(Player p) { return invoke<int>(0x936F967D4BE1CE9Dull, p) != 0; }
inline bool IS_PLAYER_FREE_FOCUSING(Player p) { return invoke<int>(0x1A51BFE60708E482ull, p) != 0; }
// where a weapon is carried when it is not in the hand (holster on the hip, back, ...); -1 = nowhere (melee)
inline int GET_DEFAULT_WEAPON_ATTACH_POINT(Hash weapon) { return invoke<int>(0x65DC4AC5B96614CBull, weapon); }
inline bool GET_PLAYER_TARGET_ENTITY(Player p, Entity* e) { return invoke<int>(0xAE663DDD99C8A670ull, p, e) != 0; }
inline bool IS_PLAYER_TARGETTING_ANYTHING(Player p) { return invoke<int>(0x4605C66E0F935F83ull, p) != 0; }
inline bool IS_SPECIAL_ABILITY_ACTIVE(Player p) { return invoke<int>(0xB16223CB7DA965F0ull, p) != 0; }
inline float GET_PLAYER_DEAD_EYE(Player p) { return invoke<float>(0xA81D24AE0AF99A5Eull, p); }
inline bool IS_LAW_INCIDENT_ACTIVE(Player p) { return invoke<int>(0xAD401C63158ACBAAull, p) != 0; }
inline int GET_WANTED_SCORE(Player p) { return invoke<int>(0xDD5FD601481F648Bull, p); }

inline bool IS_ENTITY_DEAD(Entity e) { return invoke<int>(0x7D5B1F88E7504BBAull, e) != 0; }
inline int GET_ENTITY_HEALTH(Entity e) { return invoke<int>(0x82368787EA73C0F7ull, e); }
inline int GET_ENTITY_MAX_HEALTH(Entity e) { return invoke<int>(0x15D757606D170C3Cull, e, 0); }
inline Vector3 GET_ENTITY_COORDS(Entity e) { return invoke<Vector3>(0xA86D5F069399F44Dull, e, 1, 0); }
inline float GET_ENTITY_HEADING(Entity e) { return invoke<float>(0xC230DD956E2F5507ull, e); }
inline float GET_ENTITY_SPEED(Entity e) { return invoke<float>(0xFB6BA510A533DF81ull, e); }
inline Vector3 GET_ENTITY_ROTATION(Entity e) { return invoke<Vector3>(0xE09CAF86C32CB48Full, e, 2); }
inline bool IS_ENTITY_IN_WATER(Entity e) { return invoke<int>(0xDDE5C125AC446723ull, e) != 0; }
inline float GET_ENTITY_SUBMERGED_LEVEL(Entity e) { return invoke<float>(0x4A77C3F73FD9E831ull, e); }
inline bool IS_ENTITY_IN_AIR(Entity e) { return invoke<int>(0x886E37EC497200B6ull, e, 0) != 0; }
inline bool HAS_ENTITY_BEEN_DAMAGED_BY_ENTITY(Entity a, Entity b) { return invoke<int>(0x7B6E7BEC1143AC86ull, a, b, 1, 1) != 0; }
inline bool HAS_ENTITY_BEEN_DAMAGED_BY_ANY_PED(Entity e) { return invoke<int>(0x9934E9C42D52D87Eull, e) != 0; }
inline void CLEAR_ENTITY_LAST_DAMAGE_ENTITY(Entity e) { invoke<void>(0xBB19AC7D4DCEFD0Full, e); }
inline bool IS_ENTITY_A_PED(Entity e) { return invoke<int>(0xCF8176912DDA4EA5ull, e) != 0; }

inline bool IS_PED_HUMAN(Ped p) { return invoke<int>(0xB980061DA992779Dull, p) != 0; }
inline bool IS_PED_DEAD_OR_DYING(Ped p) { return invoke<int>(0x3317DEDB88C95038ull, p, 1) != 0; }
inline bool IS_PED_SHOOTING(Ped p) { return invoke<int>(0x34616828CD07F1A1ull, p) != 0; }
inline bool IS_PED_RELOADING(Ped p) { return invoke<int>(0x24B100C68C645951ull, p) != 0; }
inline bool IS_PED_ON_MOUNT(Ped p) { return invoke<int>(0x460BC76A0E10655Eull, p) != 0; }
inline Ped GET_MOUNT(Ped p) { return invoke<Ped>(0xE7E11B8DCBED1058ull, p); }
inline bool IS_PED_IN_ANY_TRAIN(Ped p) { return invoke<int>(0x6F972C1AB75A1ED0ull, p) != 0; }
inline bool IS_PED_IN_ANY_VEHICLE(Ped p) { return invoke<int>(0x997ABD671D25CA0Bull, p, 0) != 0; }
inline bool IS_PED_IN_ANY_BOAT(Ped p) { return invoke<int>(0x2E0E1C2B4F6CB339ull, p) != 0; }
inline bool IS_PED_SWIMMING(Ped p) { return invoke<int>(0x9DE327631295B4C2ull, p) != 0; }
inline bool IS_PED_RAGDOLL(Ped p) { return invoke<int>(0x47E4E977581C5B55ull, p) != 0; }
inline bool IS_PED_FALLING(Ped p) { return invoke<int>(0xFB92A102F1C4DFA3ull, p) != 0; }
inline bool IS_PED_IN_MELEE_COMBAT(Ped p) { return invoke<int>(0x4E209B2C1EAD5159ull, p) != 0; }
inline Ped GET_MELEE_TARGET_FOR_PED(Ped p) { return invoke<Ped>(0x18A3E9EE1297FD39ull, p); }
inline bool IS_PED_DRUNK(Ped p) { return invoke<int>(0x50F124E6EF188B22ull, p) != 0; }
inline float GET_PED_DRUNKNESS(Ped p) { return invoke<float>(0x6FB76442469ABD68ull, p); }
inline Entity GET_LASSO_TARGET(Ped p) { return invoke<Entity>(0xB65A4DAB460A19BDull, p); }
inline bool IS_PED_LASSOED(Ped p) { return invoke<int>(0x9682F850056C9ADEull, p) != 0; }
// speech probe (read only): who is talking, which line
inline float GET_FRAME_TIME() { return invoke<float>(0x5E72022914CE3C38ull); }
// anim scene probe (read only): scene handles come from the game's scene map (see World::scene_probe), then its clock
// loads, switches, fades: no haptics at all then (cutscenes are not halted)
inline bool GET_IS_LOADING_SCREEN_ACTIVE() { return invoke<int>(0x71D4BF5890659B0Cull) != 0; }
inline bool IS_SCREEN_FADED_IN() { return invoke<int>(0x37F9A426FBCF4AF2ull) != 0; }
inline bool IS_PLAYER_SWITCH_IN_PROGRESS() { return invoke<int>(0xED20CB1F5297791Dull) != 0; }
inline bool IS_ENTITY_PLAYING_ANIM_SCENE(Entity e, int s) { return invoke<int>(0x3AB6C7B0BB0DF4B1ull, e, s) != 0; }
inline bool IS_ANIM_SCENE_RUNNING(int s) { return invoke<int>(0xCBFC7725DE6CE2E0ull, s, 0) != 0; }
inline float GET_ANIM_SCENE_PHASE(int s) { return invoke<float>(0x3FBC3F51BF12DFBFull, s); }
inline float GET_ANIM_SCENE_TIME(int s) { return invoke<float>(0x61BE7D6186260002ull, s); }
inline float GET_ANIM_SCENE_DURATION(int s) { return invoke<float>(0x49F1D143ADE32656ull, s); }
inline float GET_ANIM_SCENE_RATE(int s) { return invoke<float>(0x43C21623E42B821Bull, s); }
inline Hash GET_ANIM_SCENE_DICT(int s) { return invoke<Hash>(0xAE5ADA4FE3E21ADCull, s); }
inline Hash GET_ENTITY_MODEL(Entity e) { return invoke<Hash>(0xDA76A9F39210D365ull, e); }
inline bool IS_ANY_SPEECH_PLAYING(Ped p) { return invoke<int>(0x729072355FA39EC9ull, p) != 0; }
inline Hash GET_LAST_PLAYED_SPEECH_FOR_PED(Ped p) { return invoke<Hash>(0x6BFFB7C276866996ull, p); }
inline bool IS_ANY_CONVERSATION_PLAYING() { return invoke<int>(0xA2CAC9DEF0195E6Full, 0) != 0; }
inline Hash HUD_GET_INVENTORY_WHEEL_CURRENTLY_HIGHLIGHTED() { return invoke<Hash>(0x9C409BBC492CB5B1ull); }  // only while the wheel is open
inline bool IS_ATTRIBUTE_OVERPOWERED(Ped p, int attr) { return invoke<int>(0x103C2F885ABEB00Bull, p, attr) != 0; }  // fortified ring
inline bool IS_ATTRIBUTE_CORE_OVERPOWERED(Ped p, int core) { return invoke<int>(0x200373A8DF081F22ull, p, core) != 0; }  // fortified (gold)
inline int GET_ATTRIBUTE_CORE_VALUE(Ped p, int core) { return invoke<int>(0x36731AC041289BB1ull, p, core); }  // 0 health 1 stamina 2 dead eye

inline bool GET_CURRENT_PED_WEAPON(Ped p, Hash* out) { return invoke<int>(0x3A87E44BB9A01D54ull, p, out, 1, 0, 1) != 0; }
// the weapon at an attach point; 1 = the off hand (second pistol)
inline bool GET_CURRENT_PED_WEAPON_AT(Ped p, Hash* out, int point) { return invoke<int>(0x3A87E44BB9A01D54ull, p, out, 1, point, 1) != 0; }
inline Entity GET_CURRENT_PED_WEAPON_ENTITY_INDEX(Ped p) { return invoke<Entity>(0x3B390A939AF0B5FCull, p, 0); }
inline bool GET_AMMO_IN_CLIP(Ped p, int* ammo, Hash w) { return invoke<int>(0x2E1202248937775Cull, p, ammo, w) != 0; }
inline int GET_MAX_AMMO_IN_CLIP(Ped p, Hash w) { return invoke<int>(0xA38DCFFCEA8962FAull, p, w, 1); }
// stats: honor lives in the story scripts' HONOR_* stats (written on every honor change)
struct StatId { alignas(8) Hash base; alignas(8) Hash permutation; };
inline bool STAT_ID_GET_INT(StatId* id, int* out) { return invoke<int>(0x767FBC2AC802EF3Eull, id, out) != 0; }
inline int GET_NUM_MARKED_DEADEYE_TARGETS(Player p) { return invoke<int>(0xCCD9B77F70D31C9Dull, p); }
inline int GET_NUMBER_OF_THREADS_RUNNING_THE_SCRIPT_WITH_THIS_HASH(Hash h) { return invoke<int>(0x8E34C953364A76DDull, h); }
inline bool IS_DISABLED_CONTROL_JUST_PRESSED(int pad, Hash a) { return invoke<int>(0x91AEF906BCA88877ull, pad, a) != 0; }
inline bool IS_CONTROL_JUST_PRESSED(int pad, Hash a) { return invoke<int>(0x580417101DDB492Full, pad, a) != 0; }
inline const char* GET_TASK_MOVE_NETWORK_STATE(Ped p) { return invoke<const char*>(0x717E4D1F2048376Dull, p); }
inline Ped GET_LAST_MOUNT(Ped p) { return invoke<Ped>(0x4C8B59171957BCF7ull, p); }
inline Ped GET_ACTIVE_HORSE_FOR_PLAYER(Player p) { return invoke<Ped>(0x46FA0AE18F4C7FA9ull, p); }
inline bool DOES_ENTITY_EXIST(Entity e) { return invoke<int>(0xD42BD6EB2E0F1677ull, e) != 0; }
inline void TASK_ANIMAL_INTERACTION(Ped p, Ped target, Hash type, Hash model, bool skip_idle) {
    invoke<void>(0xCD181A959CFDD7F4ull, p, target, type, model, int(skip_idle));
}
inline float GET_PED_MOTIVATION(Ped p, int state, Ped target) { return invoke<float>(0x42688E94E96FD9B4ull, p, state, target); }
// the game's event queue (group 0 = AI events); data are 8-byte slots
inline int GET_NUMBER_OF_EVENTS(int group) { return invoke<int>(0x5CE8DE5909565748ull, group); }
inline Hash GET_EVENT_AT_INDEX(int group, int i) { return invoke<Hash>(0xA85E614430EFF816ull, group, i); }
inline bool GET_EVENT_DATA(int group, int i, void* data, int slots) { return invoke<int>(0x57EC5FA4D4D6AFCAull, group, i, data, slots) != 0; }
// weather
inline float GET_RAIN_LEVEL() { return invoke<float>(0x931B5F4CC130224Bull); }
inline void GET_CURR_WEATHER_STATE(Hash* a, Hash* b, float* pct) { invoke<void>(0x0AC679B2342F14F2ull, a, b, pct); }
// camp life
inline Hash GET_ITEM_INTERACTION_STATE(Ped p) { return invoke<Hash>(0x6AA3DCA2C6F5EB6Dull, p); }
inline bool HAS_ANIM_EVENT_FIRED(Entity e, Hash ev) { return invoke<int>(0x5851CC48405F4A07ull, e, ev) != 0; }
inline bool IS_ANIMAL_INTERACTION_RUNNING(Ped p) { return invoke<int>(0x7FC84E85D98F063Dull, p) != 0; }
inline bool GET_IS_ANIMAL(Entity e) { return invoke<int>(0x9A100F1CF4546629ull, e) != 0; }
inline Hash GET_ACTIVE_DYNAMIC_SCENARIO(Ped p) { return invoke<Hash>(0xC22AA08A8ADB87D4ull, p); }
// the game's own UI engine: ui apps, data binding, ui events (settings page)
struct UiEvent { alignas(8) Hash type; alignas(8) int i; alignas(8) Hash hash; alignas(8) int datastore; };
inline bool EVENTS_UI_IS_PENDING(Hash ch) { return invoke<int>(0x67ED5A7963F2F722ull, ch) != 0; }
inline bool EVENTS_UI_PEEK_MESSAGE(Hash ch, UiEvent* e) { return invoke<int>(0x90237103F27F7937ull, ch, e) != 0; }
inline void EVENTS_UI_POP_MESSAGE(Hash ch) { invoke<void>(0x8E8A2369F48EC839ull, ch); }
inline int LAUNCH_UIAPP_BY_HASH_WITH_ENTRY(Hash app, Hash entry) { return invoke<int>(0xC1BCF31E975B3195ull, app, entry); }
inline bool IS_UIAPP_RUNNING_BY_HASH(Hash app) { return invoke<int>(0x4E511D093A86AD49ull, app) != 0; }
inline void CLOSE_UIAPP_BY_HASH(Hash app) { invoke<void>(0x2FF10C9C3F92277Eull, app); }
inline bool REQUEST_UIAPP_TRANSITION_BY_HASH(Hash app, Hash tr) { return invoke<int>(0x7689CD255655BFD7ull, app, tr) != 0; }
inline Hash DATABINDING_ADD_DATA_CONTAINER_FROM_PATH(const char* parent, const char* name) { return invoke<Hash>(0x0C827D175F1292F4ull, parent, name); }
inline Hash DATABINDING_ADD_DATA_CONTAINER(Hash parent, const char* name) { return invoke<Hash>(0xEB4F9A3537EEABCDull, parent, name); }
inline Hash DATABINDING_ADD_DATA_HASH(Hash parent, const char* name, Hash v) { return invoke<Hash>(0x8538F1205D60ECA6ull, parent, name, v); }
inline Hash DATABINDING_ADD_DATA_INT(Hash parent, const char* name, int v) { return invoke<Hash>(0x307A3247C5457BDEull, parent, name, v); }
inline Hash DATABINDING_ADD_DATA_BOOL(Hash parent, const char* name, bool v) { return invoke<Hash>(0x58BAA5F635DA2FF4ull, parent, name, int(v)); }
inline Hash DATABINDING_ADD_DATA_STRING(Hash parent, const char* name, const char* v) { return invoke<Hash>(0x617FCA1C5652BBADull, parent, name, v); }
inline Hash DATABINDING_ADD_UI_ITEM_LIST(Hash parent, const char* name) { return invoke<Hash>(0xFE74FA57E0CE6824ull, parent, name); }
inline void DATABINDING_INSERT_UI_ITEM_TO_LIST(Hash list, int i, Hash alias, Hash item) { invoke<void>(0xEE97A05C05F16E41ull, list, i, alias, item); }
inline void DATABINDING_CLEAR_BINDING_ARRAY(Hash list) { invoke<void>(0xA1F15C1D03DF802Dull, list); }
inline void DATABINDING_WRITE_STRING_FROM_PARENT(Hash parent, const char* name, const char* v) { invoke<void>(0x4FF713B2F17A391Eull, parent, name, v); }
inline void DATABINDING_REMOVE_DATA_ENTRY(Hash e) { invoke<void>(0x0AE9938D0541F2DAull, e); }
inline Hash DATABINDING_ADD_HASH_ARRAY(Hash parent, const char* name) { return invoke<Hash>(0x52F5F08278EA5D75ull, parent, name); }
// appends (index -1) a hash to a hash array - net_main_offline fills dynamic_list_item_option_stepper_items with it
inline void DATABINDING_INSERT_HASH_TO_ARRAY(Hash array, Hash v, int index) { invoke<void>(0x7FC60C94C83C5CD7ull, array, v, index); }
inline void VIRTUAL_COLLECTION_SET_SIZE(Hash col, int n) { invoke<void>(0x9DCE9B01A93B58BCull, col, n); }
inline void VIRTUAL_COLLECTION_SET_INTEREST_INDEX(Hash col, int i) { invoke<void>(0x49A8447533308BCFull, col, i); }
inline Hash DATABINDING_GET_DATA_CONTAINER_FROM_PATH(const char* path) { return invoke<Hash>(0x0C827D175F1292F2ull, path); }
inline Hash DATABINDING_READ_HASH_STRING_FROM_PARENT(Hash parent, const char* name) { return invoke<Hash>(0x9B535990B01B62DEull, parent, name); }
inline int DATABINDING_READ_INT_FROM_PARENT(Hash parent, const char* name) { return invoke<int>(0xFFC566A4801F6B40ull, parent, name); }
inline void VIRTUAL_COLLECTION_ITEM_ADD(Hash col, int i, Hash alias, Hash item) { invoke<void>(0x6DCBF187221CF73Dull, col, i, alias, item); }
inline bool VIRTUAL_COLLECTION_EXISTS(Hash col) { return invoke<int>(0x37963B56755BFB35ull, col) != 0; }
inline bool DATABINDING_IS_ENTRY_VALID(Hash e) { return invoke<int>(0x1E7130793AAAAB8Dull, e) != 0; }
inline void DATABINDING_WRITE_DATA_BOOL_FROM_PARENT(Hash parent, const char* name, bool v) { invoke<void>(0xBDFE546E4C2D0E21ull, parent, name, int(v)); }
inline void DATABINDING_WRITE_DATA_INT_FROM_PARENT(Hash parent, const char* name, int v) { invoke<void>(0x9EFA98238BA08FC4ull, parent, name, v); }
inline bool IS_UIAPP_ACTIVE_BY_HASH(Hash app) { return invoke<int>(0x25B7A0206BDFAC76ull, app) != 0; }
inline bool IS_UIAPP_TRANSITIONING_BY_HASH(Hash app) { return invoke<int>(0x42095B886D30DE66ull, app) != 0; }
inline Hash GET_UIAPP_CURRENT_ACTIVITY_BY_HASH(Hash app) { return invoke<Hash>(0x96FD694FE5BE55DCull, app); }
inline bool CAN_LAUNCH_UIAPP_BY_HASH_WITH_ENTRY(Hash app, Hash entry) { return invoke<int>(0x16F47D434B6086BFull, app, entry) != 0; }
inline void CLOSE_UIAPP_BY_HASH_IMMEDIATE(Hash app) { invoke<void>(0x04428420A248A354ull, app); }
inline bool DOES_TEXT_LABEL_EXIST(const char* label) { return invoke<int>(0x73C258C68D6F55B6ull, label) != 0; }
inline const char* GET_STRING_FROM_HASH_KEY(Hash label) { return invoke<const char*>(0xBD5DD5EAE2B6CE14ull, label); }
inline void DISABLE_CONTROL_ACTION(int pad, Hash action, bool related) { invoke<void>(0xFE99B66D079CF6BCull, pad, action, int(related)); }
inline bool GET_TASK_FISHING(Ped p, void* data) { return invoke<int>(0xF3735ACD11ACD500ull, p, data) != 0; }
inline bool IS_PED_WEAPON_READY_TO_SHOOT(Ped p) { return invoke<int>(0xB80CA294F2F26749ull, p) != 0; }
inline bool IS_WEAPON_HOLSTER_STATE_CHANGING(Ped p) { return invoke<int>(0x2387D6E9C6B478AAull, p) != 0; }
inline Hash GET_WEAPONTYPE_GROUP(Hash w) { return invoke<Hash>(0xEDCA14CA5199FF25ull, w); }
inline Hash GET_PED_AMMO_TYPE_FROM_WEAPON(Ped p, Hash w) { return invoke<Hash>(0x7FEAD38B326B9F74ull, p, w); }
inline float GET_WEAPON_DEGRADATION(Entity weaponObject) { return invoke<float>(0x0D78E1097F89E637ull, weaponObject); }
inline float GET_WEAPON_DIRT(Entity weaponObject) { return invoke<float>(0x810E8AE9AFEA7E54ull, weaponObject); }

inline float GET_GAMEPLAY_CAM_RELATIVE_HEADING() { return invoke<float>(0xC4ABF536048998AAull); }
inline float GET_GAMEPLAY_CAM_RELATIVE_PITCH() { return invoke<float>(0x99AADEBBA803F827ull); }
inline void SET_GAMEPLAY_CAM_RELATIVE_HEADING(float h) { invoke<void>(0x5D1EB123EAC5D071ull, h, 1.0f); }
inline void SET_GAMEPLAY_CAM_RELATIVE_PITCH(float p) { invoke<void>(0xFB760AF4F537B8BFull, p, 1.0f); }
inline Vector3 GET_GAMEPLAY_CAM_ROT() { return invoke<Vector3>(0x0252D2B5582957A6ull, 2); }

inline bool IS_ANY_UIAPP_ACTIVE() { return invoke<int>(0xAC959AB99AAF3D9Full) != 0; }   // satchel, map, catalog, journal...
inline bool IS_PAUSE_MENU_ACTIVE() { return invoke<int>(0x535384D6067BA42Eull) != 0; }
inline bool IS_SCREEN_FADED_OUT() { return invoke<int>(0xF5472C80DF2FF847ull) != 0; }
inline bool IS_LOADING_SCREEN_VISIBLE() { return invoke<int>(0xB54ADBE65D528FCBull) != 0; }
inline int GET_CLOCK_HOURS() { return invoke<int>(0xC82CF208C2B19199ull); }
inline Hash GET_PREV_WEATHER_TYPE_HASH_NAME() { return invoke<Hash>(0x4BEB42AEBCA732E9ull); }
inline float GET_TEMPERATURE_AT_COORDS(float x, float y, float z) { return invoke<float>(0xB98B78C3768AF6E0ull, x, y, z); }
inline bool GET_GROUND_Z_AND_MATERIAL(float x, float y, float z, float* gz, Hash* mat) {
    int flags = 0;
    return invoke<int>(0xBBE5B63EFFB08E68ull, x, y, z, 17, gz, mat, &flags) != 0;   // 17: map + objects, as R* scripts
}

// bodies, movement, surroundings
inline int GET_ENTITY_BONE_INDEX_BY_NAME(Entity e, const char* name) { return invoke<int>(0xBACA8FE9C76C124Eull, e, name); }
inline Vector3 GET_WORLD_POSITION_OF_ENTITY_BONE(Entity e, int bone) { return invoke<Vector3>(0x82CFA50E34681CA5ull, e, bone); }
inline int GET_INTERIOR_FROM_ENTITY(Entity e) { return invoke<int>(0xB417689857646F61ull, e); }
inline float GET_SNOW_LEVEL() { return invoke<float>(0x1E5D727041BE1709ull); }
inline bool GET_PED_CROUCH_MOVEMENT(Ped p) { return invoke<int>(0xD5FE956C70FF370Bull, p) != 0; }
inline bool IS_PED_CARRYING_SOMETHING(Ped p) { return invoke<int>(0xA911EE21EDF69DAFull, p) != 0; }
inline bool IS_PED_CLIMBING(Ped p) { return invoke<int>(0x53E8CB4F48BFE623ull, p) != 0; }
inline bool IS_PED_VAULTING(Ped p) { return invoke<int>(0x117C70D1F5730B5Eull, p) != 0; }
inline bool IS_PED_JUMPING(Ped p) { return invoke<int>(0xCEDABC5900A0BF97ull, p) != 0; }
inline bool IS_PED_OPENING_DOOR(Ped p) { return invoke<int>(0x26AF0E8E30BD2A2Cull, p) != 0; }
inline float GET_ENTITY_HEIGHT_ABOVE_GROUND(Entity e) { return invoke<float>(0x0D3B5BAEA08F63E9ull, e); }

// speech and looking (greeting)
struct ScriptedSpeechParams {
    const char* speechName;
    const char* voiceName;
    alignas(8) int variation;
    alignas(8) Hash speechParamHash;
    alignas(8) Ped listenerPed;
    alignas(8) int syncOverNetwork;
    alignas(8) int v7;
    alignas(8) int v8;
};
static_assert(sizeof(ScriptedSpeechParams) == 0x40, "ScriptedSpeechParams size");
inline bool PLAY_PED_AMBIENT_SPEECH_NATIVE(Ped speaker, ScriptedSpeechParams* p) { return invoke<int>(0x8E04FEDD28D42462ull, speaker, p) != 0; }
inline bool IS_AMBIENT_SPEECH_PLAYING(Ped p) { return invoke<int>(0x9072C8B49907BFADull, p) != 0; }
inline void TASK_LOOK_AT_ENTITY(Ped p, Entity target, int ms) { invoke<void>(0x69F4BE8C8CC4796Cull, p, target, ms, 2048, 3, 0); }
inline bool IS_PED_MALE(Ped p) { return invoke<int>(0x6D9F5FAA7488BA46ull, p) != 0; }
// simulate a game action (not a physical button) for the next frame; value 0..1
inline bool SET_CONTROL_VALUE_NEXT_FRAME(int pad, Hash action, float value) { return invoke<int>(0xE8A25867FBA3B05Eull, pad, action, value) != 0; }
inline bool GET_PLAYER_INTERACTION_TARGET_ENTITY(Player p, Entity* e) { return invoke<int>(0x3EE1F7A8C32F24E1ull, p, e, 0, 0) != 0; }
inline bool UI_PROMPT_IS_CONTROL_ACTION_ACTIVE(Hash action) { return invoke<int>(0x1BE19185B8AFE299ull, action) != 0; }
inline bool IS_CONTROL_PRESSED(int pad, Hash action) { return invoke<int>(0xF3A21BCD95725A4Aull, pad, action) != 0; }
inline float GET_CONTROL_NORMAL(int pad, Hash action) { return invoke<float>(0xEC3C9B8D5327B563ull, pad, action); }
inline bool IS_DISABLED_CONTROL_PRESSED(int pad, Hash action) { return invoke<int>(0xE2587F8CBBD87B1Dull, pad, action) != 0; }

// on-screen text (the surface teaching note)
inline const char* VAR_STRING_LITERAL(const char* text) { return invoke<const char*>(0xFA925AC00EB830B9ull, 10, "LITERAL_STRING", text); }
inline void BG_SET_TEXT_SCALE(float x, float y) { invoke<void>(0xA1253A3C870B6843ull, x, y); }
inline void BG_SET_TEXT_COLOR(int r, int g, int b, int a) { invoke<void>(0x16FA5CE47F184F1Eull, r, g, b, a); }
inline void BG_DISPLAY_TEXT(const char* varstring, float x, float y) { invoke<void>(0x16794E044C9EFB58ull, varstring, x, y); }

}  // namespace dsr2::nat
