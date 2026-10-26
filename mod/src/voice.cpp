#include "voice.h"

#include "log.h"

#include <initguid.h>
#include <mmsystem.h>
#include <sapi.h>

namespace dsr2 {

namespace {

// CLSIDs (defined here so we don't depend on how the import library exports them)
// {41B89B6B-9399-11D2-9623-00C04F8EE628} SpInprocRecognizer
const GUID kInprocRecognizer = {0x41B89B6B, 0x9399, 0x11D2, {0x96, 0x23, 0x00, 0xC0, 0x4F, 0x8E, 0xE6, 0x28}};
// {CF3D2E50-53F2-11D2-960C-00C04F8EE628} SpMMAudioIn
const GUID kMMAudioIn = {0xCF3D2E50, 0x53F2, 0x11D2, {0x96, 0x0C, 0x00, 0xC0, 0x4F, 0x8E, 0xE6, 0x28}};
// {A910187F-0C7A-45AC-92CC-59EDAFB77B53} SpObjectTokenCategory
const GUID kTokenCategory = {0xA910187F, 0x0C7A, 0x45AC, {0x92, 0xCC, 0x59, 0xED, 0xAF, 0xB7, 0x7B, 0x53}};

template <class T>
struct Com {
    T* p = nullptr;
    ~Com() { if (p) p->Release(); }
    T** operator&() { return &p; }
    T* operator->() const { return p; }
    explicit operator bool() const { return p != nullptr; }
};

int dualsense_wavein() {
    UINT n = waveInGetNumDevs();
    for (UINT i = 0; i < n; ++i) {
        WAVEINCAPSW caps{};
        if (waveInGetDevCapsW(i, &caps, sizeof caps) == MMSYSERR_NOERROR && wcsstr(caps.szPname, L"DualSens")) return int(i);
    }
    return -1;
}

std::wstring widen(const std::string& s) { return std::wstring(s.begin(), s.end()); }

std::string narrow(const wchar_t* w) {
    std::string s;
    for (; w && *w; ++w) s += char(*w < 128 ? *w : '?');
    return s;
}

}  // namespace

bool Voice::start(const std::vector<std::string>& phrases, float min_conf, Handler h) {
    handler_ = std::move(h);
    phrases_ = phrases;
    min_conf_ = min_conf;
    running_ = true;
    thread_ = std::thread([this, phrases, min_conf] { loop(phrases, min_conf); });
    return true;
}

void Voice::stop() {
    running_ = false;
    if (thread_.joinable()) thread_.join();
}

void Voice::restart() {
    if (!handler_) return;
    stop();
    running_ = true;
    thread_ = std::thread([this] { loop(phrases_, min_conf_); });
}

void Voice::loop(std::vector<std::string> phrases, float min_conf) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    {
        Com<ISpRecognizer> rec;
        Com<ISpMMSysAudio> audio;
        Com<ISpObjectTokenCategory> cat;
        Com<IEnumSpObjectTokens> tokens;
        Com<ISpObjectToken> engine;
        Com<ISpRecoContext> ctx;
        Com<ISpRecoGrammar> grammar;
        int dev = dualsense_wavein();
        HRESULT hr = CoCreateInstance(kInprocRecognizer, nullptr, CLSCTX_ALL, __uuidof(ISpRecognizer), (void**)&rec);
        if (SUCCEEDED(hr)) hr = CoCreateInstance(kTokenCategory, nullptr, CLSCTX_ALL, __uuidof(ISpObjectTokenCategory), (void**)&cat);
        if (SUCCEEDED(hr)) hr = cat->SetId(L"HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Recognizers", FALSE);
        if (SUCCEEDED(hr)) hr = cat->EnumTokens(L"Language=409", nullptr, &tokens);
        if (SUCCEEDED(hr)) hr = tokens->Next(1, &engine, nullptr);
        if (hr != S_OK || !engine) {
            LOGW("voice: no English (US) speech recognizer installed - voice commands off");
            CoUninitialize();
            return;
        }
        const char* step = "SetRecognizer";
        hr = rec->SetRecognizer(engine.p);
        // the controller mic as Windows' speech system lists it (audio input tokens)
        Com<ISpObjectTokenCategory> inputs;
        Com<IEnumSpObjectTokens> in_tokens;
        Com<ISpObjectToken> mic;
        if (SUCCEEDED(hr)) { step = "audio inputs"; hr = CoCreateInstance(kTokenCategory, nullptr, CLSCTX_ALL, __uuidof(ISpObjectTokenCategory), (void**)&inputs); }
        if (SUCCEEDED(hr)) hr = inputs->SetId(L"HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\AudioInput", FALSE);
        if (SUCCEEDED(hr)) hr = inputs->EnumTokens(nullptr, nullptr, &in_tokens);
        if (SUCCEEDED(hr)) {
            ISpObjectToken* t = nullptr;
            while (!mic && in_tokens->Next(1, &t, nullptr) == S_OK) {
                wchar_t* desc = nullptr;
                if (SUCCEEDED(t->GetStringValue(nullptr, &desc)) && desc && wcsstr(desc, L"DualSens")) {
                    mic.p = t;
                    LOGI("voice: microphone %s", narrow(desc).c_str());
                } else {
                    t->Release();
                }
                if (desc) CoTaskMemFree(desc);
            }
        }
        if (SUCCEEDED(hr) && mic) { step = "SetInput(token)"; hr = rec->SetInput(mic.p, TRUE); }
        else if (SUCCEEDED(hr)) {
            // fallback: the MM audio object on the DualSense wave-in device
            step = "SetInput(device)";
            hr = CoCreateInstance(kMMAudioIn, nullptr, CLSCTX_ALL, __uuidof(ISpMMSysAudio), (void**)&audio);
            if (SUCCEEDED(hr) && dev >= 0) hr = audio->SetDeviceId(UINT(dev));
            if (SUCCEEDED(hr)) hr = rec->SetInput(audio.p, TRUE);
        }
        if (SUCCEEDED(hr)) { step = "CreateRecoContext"; hr = rec->CreateRecoContext(&ctx); }
        if (SUCCEEDED(hr)) { step = "events"; hr = ctx->SetNotifyWin32Event(); }
        if (SUCCEEDED(hr)) hr = ctx->SetInterest(SPFEI(SPEI_RECOGNITION) | SPFEI(SPEI_HYPOTHESIS), SPFEI(SPEI_RECOGNITION) | SPFEI(SPEI_HYPOTHESIS));
        if (SUCCEEDED(hr)) { step = "CreateGrammar"; hr = ctx->CreateGrammar(1, &grammar); }
        if (FAILED(hr) || (!mic && dev < 0)) {
            LOGW("voice: could not start the recognizer on the controller mic (%s: 0x%08lX, device %d)", step, hr, dev);
            CoUninitialize();
            return;
        }
        // commands + decoys: anything else said tends to land on a decoy
        std::vector<std::string> words = phrases;
        for (const char* d : {"hello", "hey", "how", "okay", "yes", "no", "go", "horse", "what", "hold", "now", "come", "the",
                              "and", "you", "here", "there", "hi", "high", "doing", "day"})
            words.push_back(d);
        SPSTATEHANDLE rule = nullptr;
        grammar->GetRule(L"words", 0, SPRAF_TopLevel | SPRAF_Active, TRUE, &rule);
        for (auto& w : words) grammar->AddWordTransition(rule, nullptr, widen(w).c_str(), L" ", SPWT_LEXICAL, 1.0f, nullptr);
        grammar->Commit(0);
        grammar->SetRuleState(nullptr, nullptr, SPRS_ACTIVE);
        std::string list;
        for (auto& p : phrases) list += (list.empty() ? "" : " / ") + p;
        LOGI("voice: listening for \"%s\" on the controller mic", list.c_str());
        HANDLE ev = ctx->GetNotifyEventHandle();
        double prev_end = -10;     // when the previous utterance (any word) ended
        while (running_) {
            if (WaitForSingleObject(ev, 200) != WAIT_OBJECT_0) continue;
            SPEVENT e;
            ULONG fetched = 0;
            while (SUCCEEDED(ctx->GetEvents(1, &e, &fetched)) && fetched) {
                if (e.eEventId == SPEI_HYPOTHESIS && e.elParamType == SPET_LPARAM_IS_OBJECT && e.lParam) {
                    // an early guess while the word is still being said: lets the whistle detector stand down fast
                    auto* res = reinterpret_cast<ISpRecoResult*>(e.lParam);
                    wchar_t* text = nullptr;
                    if (SUCCEEDED(res->GetText(SP_GETWHOLEPHRASE, SP_GETWHOLEPHRASE, TRUE, &text, nullptr)) && text) {
                        std::string guess = narrow(text);
                        if (std::find(phrases.begin(), phrases.end(), guess) != phrases.end()) last_command_guess = now_s();
                        CoTaskMemFree(text);
                    }
                    res->Release();
                } else if (e.eEventId == SPEI_RECOGNITION && e.elParamType == SPET_LPARAM_IS_OBJECT && e.lParam) {
                    auto* res = reinterpret_cast<ISpRecoResult*>(e.lParam);
                    SPPHRASE* ph = nullptr;
                    if (SUCCEEDED(res->GetPhrase(&ph)) && ph) {
                        wchar_t* text = nullptr;
                        res->GetText(SP_GETWHOLEPHRASE, SP_GETWHOLEPHRASE, TRUE, &text, nullptr);
                        std::string said = narrow(text);
                        float conf = ph->Rule.SREngineConfidence;
                        bool command = std::find(phrases.begin(), phrases.end(), said) != phrases.end();
                        // a command is a word said on its own: short, after a pause. In a conversation the
                        // recognizer keeps matching speech to its words ("and", "the"... and now and then "ciao").
                        SPRECORESULTTIMES times{};
                        double len = SUCCEEDED(res->GetResultTimes(&times)) ? double(times.ullLength) / 1e7 : 0.0;
                        double now = now_s(), start = now - len;
                        const char* why = !command ? "ignored"
                                        : conf < min_conf ? "too unsure"
                                        : len > 1.2 ? "too long - part of a sentence"
                                        : start - prev_end < 0.8 ? "no pause before - part of a conversation"
                                        : "command";
                        LOGD("voice heard \"%s\" (confidence %.2f, %.2f s, %s)", said.c_str(), conf, len, why);
                        if (std::string(why) == "command" && listening_ && handler_) handler_(said, conf);
                        prev_end = now;
                        if (text) CoTaskMemFree(text);
                        CoTaskMemFree(ph);
                    }
                    res->Release();
                } else if (e.elParamType == SPET_LPARAM_IS_OBJECT && e.lParam) {
                    reinterpret_cast<IUnknown*>(e.lParam)->Release();
                } else if ((e.elParamType == SPET_LPARAM_IS_POINTER || e.elParamType == SPET_LPARAM_IS_STRING) && e.lParam) {
                    CoTaskMemFree(reinterpret_cast<void*>(e.lParam));
                }
            }
        }
    }
    CoUninitialize();
}

}  // namespace dsr2
