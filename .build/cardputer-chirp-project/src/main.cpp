#include <Arduino.h>
#include <M5Cardputer.h>
#include <SPI.h>
#include <SD.h>
#include <array>
#include <cctype>
#include "app_ui.h"
#include "xpt2046_soft.h"
#include "pcfp_transport.h"
#include "uvk5_driver.h"
#include "hw_config.h"

static AppUI ui;
static XPT2046Soft touch;
static PcfpTransport pcfp;
static UVK5Driver uvk5(pcfp);
static std::array<uint8_t, UVK5Driver::IMAGE_SIZE> radioImage{};
static String radioFirmware;

static bool sdReady = false;
static bool haveImage = false;
static bool readPending = false;
static int selectedChannel = 0;
static int topChannel = 0;

enum class Screen { Home, Channels, Error };
static Screen screen = Screen::Home;
static String errorTitle;
static String errorText;
static uint32_t lastTouchMs = 0;

static bool runTouchCalibration() {
    if (touch.calibrated()) return true;
    const int tx[4] = {20, 300, 300, 20};
    const int ty[4] = {20, 20, 220, 220};
    RawTouchPoint samples[4];
    for (int step = 0; step < 4; ++step) {
        ui.drawTouchCalibrationTarget(tx[step], ty[step], step + 1);
        bool sawPress = false;
        uint32_t pressStart = 0;
        RawTouchPoint best;
        while (true) {
            M5Cardputer.update();
            if (M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed()) {
                Keyboard_Class::KeysState st = M5Cardputer.Keyboard.keysState();
                if (st.enter) {
                    ui.drawTouchCalibrationMessage("Touch skipped");
                    delay(500);
                    return false;
                }
            }
            RawTouchPoint p = touch.readRaw();
            if (p.pressed) {
                if (!sawPress) {
                    sawPress = true;
                    pressStart = millis();
                }
                best = p;
                if (millis() - pressStart > 180) {
                    samples[step] = best;
                    while (touch.readRaw().pressed) {
                        M5Cardputer.update();
                        delay(10);
                    }
                    break;
                }
            } else sawPress = false;
            delay(8);
        }
    }
    touch.saveFourPointCalibration(samples);
    ui.drawTouchCalibrationMessage("Calibration saved");
    delay(700);
    return true;
}

static void initSD() {
    pinMode(hw::TFT_CS, OUTPUT); digitalWrite(hw::TFT_CS, HIGH);
    pinMode(hw::TOUCH_CS, OUTPUT); digitalWrite(hw::TOUCH_CS, HIGH);
    pinMode(hw::SD_CS, OUTPUT); digitalWrite(hw::SD_CS, HIGH);
    SPI.begin(hw::SD_SCK, hw::SD_MISO, hw::SD_MOSI, hw::SD_CS);
    sdReady = SD.begin(hw::SD_CS, SPI, 20000000);
    if (sdReady) {
        SD.mkdir("/PocketCHIRP");
        SD.mkdir("/PocketCHIRP/Backups");
    }
    Serial.printf("[SD] %s\n", sdReady ? "ready" : "not available");
}

static String sanitizeFilename(String s) {
    if (!s.length()) return "unknown";
    for (size_t i = 0; i < s.length(); ++i) {
        char c = s[i];
        if (!isalnum(static_cast<unsigned char>(c)) && c != '-' && c != '_') s.setCharAt(i, '_');
    }
    if (s.length() > 24) s = s.substring(0, 24);
    return s;
}

static bool saveBackup() {
    if (!sdReady) return false;
    static uint32_t seq = 0;
    ++seq;
    char suffix[24];
    snprintf(suffix, sizeof(suffix), "%08lu_%03lu", (unsigned long)millis(), (unsigned long)seq);
    String path = "/PocketCHIRP/Backups/UVK5_" + sanitizeFilename(radioFirmware) + "_" + suffix + ".img";
    File f = SD.open(path, FILE_WRITE);
    if (!f) return false;
    size_t n = f.write(radioImage.data(), radioImage.size());
    f.close();
    Serial.printf("[SD] backup %s (%u bytes)\n", path.c_str(), (unsigned)n);
    return n == radioImage.size();
}

static void renderCurrent() {
    if (screen == Screen::Home) ui.drawHome(pcfp, sdReady);
    else if (screen == Screen::Channels) ui.drawChannels(radioImage, uvk5, selectedChannel, topChannel, radioFirmware);
    else ui.drawError(errorTitle, errorText);
}

static void setError(const String& title, const String& msg) {
    errorTitle = title;
    errorText = msg;
    screen = Screen::Error;
    renderCurrent();
}

static void startConnect() {
    pcfp.startScan();
    ui.drawHome(pcfp, sdReady);
}

static void startRead() {
    if (pcfp.state() == PcfpTransport::State::Connected && !pcfp.isReady()) {
        if (!pcfp.startSession(UVK5Driver::BAUD, 8, 0, 0, false, false)) {
            setError("PCFP", pcfp.statusText());
            return;
        }
    }
    if (!pcfp.isReady()) {
        readPending = true;
        startConnect();
        return;
    }
    readPending = false;
    ui.drawProgress("Reading radio", 0, UVK5Driver::IMAGE_SIZE, "UV-K5/K6 @ 38400");
    String firmware;
    bool ok = uvk5.download(radioImage, firmware, [](size_t done, size_t total) {
        M5Cardputer.update();
        ui.drawProgress("Reading radio", done, total, radioFirmware.length() ? radioFirmware : "UV-K5/K6");
    });
    if (!ok) {
        setError("Radio read failed", uvk5.lastError());
        return;
    }
    radioFirmware = firmware;
    haveImage = true;
    bool backed = saveBackup();
    selectedChannel = 0;
    topChannel = 0;
    screen = Screen::Channels;
    ui.drawChannels(radioImage, uvk5, selectedChannel, topChannel,
                    radioFirmware + (backed ? "  SD backup" : ""));
}

static void moveSelection(int delta) {
    selectedChannel = constrain(selectedChannel + delta, 0, 199);
    if (selectedChannel < topChannel) topChannel = selectedChannel;
    if (selectedChannel >= topChannel + 8) topChannel = selectedChannel - 7;
    renderCurrent();
}

static bool hit(const TouchPoint& p, int x, int y, int w, int h) {
    return p.pressed && p.x >= x && p.x < x + w && p.y >= y && p.y < y + h;
}

static void handleTouch() {
    if (!touch.calibrated()) return;
    TouchPoint p = touch.read();
    if (!p.pressed) return;
    if (millis() - lastTouchMs < 250) return;
    lastTouchMs = millis();
    if (screen == Screen::Home) {
        if (hit(p, 8, 190, 72, 40)) startConnect();
        else if (hit(p, 86, 190, 72, 40)) startRead();
    } else if (screen == Screen::Channels) {
        if (p.y >= 32 && p.y < 32 + 8 * 19) {
            int row = (p.y - 32) / 19;
            int idx = topChannel + row;
            if (idx >= 0 && idx < 200) {
                selectedChannel = idx;
                renderCurrent();
            }
        } else if (hit(p, 8, 194, 72, 36)) { screen = Screen::Home; renderCurrent(); }
        else if (hit(p, 86, 194, 72, 36)) moveSelection(-1);
        else if (hit(p, 164, 194, 72, 36)) moveSelection(1);
    } else if (screen == Screen::Error && hit(p, 110, 188, 100, 38)) {
        screen = Screen::Home;
        renderCurrent();
    }
}

static void handleKeyboard() {
    M5Cardputer.update();
    if (!M5Cardputer.Keyboard.isChange() || !M5Cardputer.Keyboard.isPressed()) return;
    Keyboard_Class::KeysState st = M5Cardputer.Keyboard.keysState();
    for (auto c : st.word) {
        if (c == 'c' || c == 'C') startConnect();
        else if (c == 'r' || c == 'R') startRead();
        else if (screen == Screen::Channels && (c == ',' || c == ';')) moveSelection(-1);
        else if (screen == Screen::Channels && (c == '/' || c == '.')) moveSelection(1);
        else if (c == '`') { screen = Screen::Home; renderCurrent(); }
    }
    if (st.del && screen != Screen::Home) { screen = Screen::Home; renderCurrent(); }
    if (st.enter && screen == Screen::Error) { screen = Screen::Home; renderCurrent(); }
}

void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println("\nCardputerCHIRP M1 boot");
    auto cfg = M5.config();
    M5Cardputer.begin(cfg, true);
    ui.begin();
    touch.begin();
    runTouchCalibration();
    initSD();
    pcfp.begin();
    renderCurrent();
}

void loop() {
    pcfp.poll();
    if (readPending && pcfp.state() == PcfpTransport::State::Connected) {
        startRead();
        return;
    }
    static PcfpTransport::State prevState = PcfpTransport::State::Idle;
    if (pcfp.state() != prevState) {
        prevState = pcfp.state();
        if (screen == Screen::Home) renderCurrent();
    }
    handleKeyboard();
    handleTouch();
    delay(8);
}
