// World for the standalone test program: no game, empty snapshots.
#include "world.h"

namespace dsr2 {

World& world() {
    static World w;
    return w;
}

void World::tick() {}
GameSnapshot World::snapshot() { return GameSnapshot{}; }
std::vector<WorldEvent> World::take_events() { return {}; }
void World::add_gyro(float yaw, float pitch) {
    gyro_yaw_ = gyro_yaw_.load() + yaw;
    gyro_pitch_ = gyro_pitch_.load() + pitch;
}
float World::pan_to(float, float, float, float, float) const { return 0; }

}  // namespace dsr2
