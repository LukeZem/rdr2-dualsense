"""One-off patch: reopen the controller's audio (haptics, whistle mic, voice) after a reconnect;
mic level meter; several phrases per command (chao = ciao / chow)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "mod" / "src"


def edit(name, pairs):
    p = ROOT / name
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{name}: not found: {a[:80]}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


# ---------------- audio: restart + level meter ----------------
edit("audio.h", [
    ("    void stop();\n    bool ok() const", "    void stop();\n    // reopen every device stream (the controller was unplugged / reconnected)\n    void restart();\n    float mic_level() const { return mic_level_.load(); }\n    bool ok() const"),
    ("    std::function<void()> on_whistle_;", "    std::function<void()> on_whistle_;\n    std::atomic<float> mic_level_{0};\n    float mic_sens_ = 1.0f, ga_gain_ = 0;\n    std::string ga_hint_;\n    bool mic_started_ = false, ga_started_ = false;\n    std::mutex restart_mu_;"),
])
edit("audio.cpp", [
    ("""void AudioEngine::stop() {
    running_ = false;
    for (auto* t : {&render_, &loop_, &mic_})
        if (t->joinable()) t->join();
}""", """void AudioEngine::stop() {
    running_ = false;
    for (auto* t : {&render_, &loop_, &mic_})
        if (t->joinable()) t->join();
    ok_ = false;
}

void AudioEngine::restart() {
    std::lock_guard<std::mutex> l(restart_mu_);
    stop();
    running_ = true;
    render_ = std::thread([this] { render_thread(); });
    if (ga_started_) loop_ = std::thread([this] { loopback_thread(ga_hint_); });
    if (mic_started_) mic_ = std::thread([this] { mic_thread(mic_sens_); });
    LOGI("audio devices reopened");
}"""),
    ("""    game_audio_gain_ = gain;
    if (gain <= 0 || loop_.joinable()) return;""", """    game_audio_gain_ = gain;
    if (gain <= 0 || loop_.joinable()) return;
    ga_started_ = true;
    ga_hint_ = hint;"""),
    ("""    on_whistle_ = std::move(on_whistle);
    if (mic_.joinable()) return;""", """    on_whistle_ = std::move(on_whistle);
    if (mic_.joinable()) return;
    mic_started_ = true;
    mic_sens_ = sens;"""),
    ("""                frame.push_back(s);
                if (int(frame.size()) < N) continue;""", """                frame.push_back(s);
                if (int(frame.size()) < N) continue;
                {
                    float pk = 0;
                    for (float v : frame) pk = std::max(pk, std::fabs(v));
                    mic_level_ = pk;
                }"""),
])

# ---------------- voice: restart + several phrases ----------------
edit("voice.h", [
    ("    void stop();\n", "    void stop();\n    void restart();\n"),
    ("    Handler handler_;", "    Handler handler_;\n    std::vector<std::string> phrases_;\n    float min_conf_ = 0.35f;"),
])
edit("voice.cpp", [
    ("""    handler_ = std::move(h);
    running_ = true;""", """    handler_ = std::move(h);
    phrases_ = phrases;
    min_conf_ = min_conf;
    running_ = true;"""),
    ("""void Voice::stop() {
    running_ = false;
    if (thread_.joinable()) thread_.join();
}""", """void Voice::stop() {
    running_ = false;
    if (thread_.joinable()) thread_.join();
}

void Voice::restart() {
    if (!handler_) return;
    stop();
    running_ = true;
    thread_ = std::thread([this] { loop(phrases_, min_conf_); });
}"""),
    ("""        LOGI("voice: listening for \\"%s\\" on the controller mic", phrases.empty() ? "" : phrases[0].c_str());""",
     """        std::string list;
        for (auto& p : phrases) list += (list.empty() ? "" : " / ") + p;
        LOGI("voice: listening for \\"%s\\" on the controller mic", list.c_str());"""),
])

# ---------------- core: phrases list, reconnect watch ----------------
edit("core.h", [
    ("    bool reload_key_down_ = false;", "    bool reload_key_down_ = false;\n    bool pad_was_connected_ = false, pad_seen_ = false;\n    std::atomic<bool> restarting_{false};"),
])
edit("core.cpp", [
    ("""        std::string phrase = c.str("Voice", "Phrase", "howdy");
        voice_.start({phrase}, """, """        // "Phrase" may list several spellings/words, comma separated: chao = ciao / chow
        std::vector<std::string> phrases;
        std::string list = c.str("Voice", "Phrase", "ciao,chow"), cur;
        for (char ch : list + ",") {
            if (ch == ',') {
                while (!cur.empty() && cur.back() == ' ') cur.pop_back();
                if (!cur.empty()) phrases.push_back(cur);
                cur.clear();
            } else if (ch != ' ' || !cur.empty()) {
                cur += char(tolower((unsigned char)ch));
            }
        }
        voice_.start(phrases, """),
    ("""    if (!pad_.connected()) input().publish(InputState{}, -1, false);   // let other pads through""",
     """    if (!pad_.connected()) input().publish(InputState{}, -1, false);   // let other pads through
    // the controller came back (cable, Bluetooth, sleep): Windows recreated its audio devices
    bool conn = pad_.connected();
    if (conn && !pad_was_connected_ && pad_seen_ && !restarting_.exchange(true)) {
        LOGI("controller reconnected - reopening its audio (haptics, mic, voice)");
        std::thread([this] {
            Sleep(1500);                      // give Windows a moment to publish the new endpoints
            audio_.restart();
            voice_.restart();
            restarting_ = false;
        }).detach();
    }
    if (conn) pad_seen_ = true;
    pad_was_connected_ = conn;"""),
])
edit("config.cpp", [
    ("Phrase=howdy\n", "; Several words allowed, comma separated (chao: the recognizer knows it as \"ciao\" / \"chow\")\nPhrase=ciao,chow\n"),
])

# ---------------- mic test: live level ----------------
edit("standalone.cpp", [
    ("""        dsr2::log::set_debug(true);
        while (true) {
            dsr2::core().script_tick();
            Sleep(16);
        }""", """        dsr2::log::set_debug(true);
        double next = 0;
        while (true) {
            dsr2::core().script_tick();
            Sleep(16);
            if (dsr2::now_s() >= next) {        // live mic level, so you can see sound arrives
                next = dsr2::now_s() + 0.25;
                float lv = dsr2::core().audio().mic_level();
                int bars = std::min(40, int(lv * 160));
                printf("\\r  mic %-40s %s ", std::string(bars, '#').c_str(),
                       dsr2::core().audio().mic_listening() ? "listening" : "MUTED    ");
                fflush(stdout);
            }
        }"""),
])
print("patched")
