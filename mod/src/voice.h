// Voice commands on the controller microphone (Windows speech recognizer, offline, English).
// A tiny command grammar: the phrases we act on plus decoy words, so other speech and the TV's
// dialogue match a decoy instead of a command.
#pragma once

#include "common.h"

#include <thread>

namespace dsr2 {

class Voice {
public:
    using Handler = std::function<void(const std::string& phrase, float confidence)>;
    bool start(const std::vector<std::string>& phrases, float min_confidence, Handler h);
    void stop();
    void restart();
    std::atomic<double> last_command_guess{-10};   // the recognizer's early guess was a command (while still speaking)
    void set_listening(bool on) { listening_ = on; }

private:
    void loop(std::vector<std::string> phrases, float min_conf);
    std::thread thread_;
    std::atomic<bool> running_{false}, listening_{true};
    Handler handler_;
    std::vector<std::string> phrases_;
    float min_conf_ = 0.35f;
};

}  // namespace dsr2
