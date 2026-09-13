#include "xpt2046_soft.h"
#include <algorithm>
#include <cmath>

static constexpr uint16_t PRESSURE_THRESHOLD = 350;

void XPT2046Soft::begin() {
    pinMode(hw::TOUCH_CS, OUTPUT);
    digitalWrite(hw::TOUCH_CS, HIGH);
    pinMode(hw::TOUCH_SCK, OUTPUT);
    digitalWrite(hw::TOUCH_SCK, LOW);
    pinMode(hw::TOUCH_MOSI, OUTPUT);
    digitalWrite(hw::TOUCH_MOSI, LOW);
    pinMode(hw::TOUCH_MISO, INPUT);
    pinMode(hw::SD_CS, OUTPUT);
    digitalWrite(hw::SD_CS, HIGH);
    pinMode(hw::TFT_CS, OUTPUT);
    digitalWrite(hw::TFT_CS, HIGH);
    loadCalibration();
}

uint8_t XPT2046Soft::transfer8(uint8_t v) {
    uint8_t r = 0;
    for (int i = 7; i >= 0; --i) {
        digitalWrite(hw::TOUCH_MOSI, (v >> i) & 1);
        digitalWrite(hw::TOUCH_SCK, HIGH);
        r = static_cast<uint8_t>((r << 1) | (digitalRead(hw::TOUCH_MISO) ? 1 : 0));
        digitalWrite(hw::TOUCH_SCK, LOW);
    }
    return r;
}

uint16_t XPT2046Soft::read12(uint8_t command) {
    digitalWrite(hw::TOUCH_CS, LOW);
    transfer8(command);
    uint16_t v = static_cast<uint16_t>(transfer8(0x00)) << 8;
    v |= transfer8(0x00);
    digitalWrite(hw::TOUCH_CS, HIGH);
    return (v >> 3) & 0x0FFF;
}

uint16_t XPT2046Soft::median5(uint16_t* values) {
    std::sort(values, values + 5);
    return values[2];
}

RawTouchPoint XPT2046Soft::readRaw() {
    RawTouchPoint p;
    uint16_t z1 = read12(0xB0);
    uint16_t z2 = read12(0xC0);
    uint16_t pressure = static_cast<uint16_t>(std::min<int>(4095, z1 + (4095 - z2)));
    if (pressure < PRESSURE_THRESHOLD || z1 == 0 || z1 >= 4095) return p;
    uint16_t xs[5];
    uint16_t ys[5];
    for (int i = 0; i < 5; ++i) {
        xs[i] = read12(0xD0);
        ys[i] = read12(0x90);
    }
    p.x = median5(xs);
    p.y = median5(ys);
    p.pressure = pressure;
    p.pressed = true;
    return p;
}

int XPT2046Soft::mapAxis(int raw, int rawAtLow, int rawAtHigh, int screenLow, int screenHigh) const {
    if (rawAtHigh == rawAtLow) return screenLow;
    long num = static_cast<long>(raw - rawAtLow) * (screenHigh - screenLow);
    long den = rawAtHigh - rawAtLow;
    return screenLow + static_cast<int>(num / den);
}

TouchPoint XPT2046Soft::read() {
    TouchPoint out;
    RawTouchPoint raw = readRaw();
    if (!raw.pressed || !calValid_) return out;
    int sxRaw = swapAxes_ ? raw.y : raw.x;
    int syRaw = swapAxes_ ? raw.x : raw.y;
    int x = mapAxis(sxRaw, rawXLow_, rawXHigh_, 20, 300);
    int y = mapAxis(syRaw, rawYLow_, rawYHigh_, 20, 220);
    x = constrain(x, 0, hw::EXT_W - 1);
    y = constrain(y, 0, hw::EXT_H - 1);
    out.x = static_cast<int16_t>(x);
    out.y = static_cast<int16_t>(y);
    out.pressure = raw.pressure;
    out.pressed = true;
    return out;
}

bool XPT2046Soft::loadCalibration() {
    Preferences prefs;
    if (!prefs.begin("pc-touch", true)) return false;
    calValid_ = prefs.getBool("valid", false);
    if (calValid_) {
        swapAxes_ = prefs.getBool("swap", false);
        rawXLow_  = prefs.getInt("xl", 300);
        rawXHigh_ = prefs.getInt("xh", 3800);
        rawYLow_  = prefs.getInt("yl", 300);
        rawYHigh_ = prefs.getInt("yh", 3800);
    }
    prefs.end();
    return calValid_;
}

void XPT2046Soft::clearCalibration() {
    Preferences prefs;
    if (prefs.begin("pc-touch", false)) {
        prefs.clear();
        prefs.end();
    }
    calValid_ = false;
}

void XPT2046Soft::saveFourPointCalibration(const RawTouchPoint raw[4]) {
    auto avg2 = [](int a, int b) { return (a + b) / 2; };
    int leftRx   = avg2(raw[0].x, raw[3].x);
    int rightRx  = avg2(raw[1].x, raw[2].x);
    int topRx    = avg2(raw[0].x, raw[1].x);
    int bottomRx = avg2(raw[3].x, raw[2].x);
    int leftRy   = avg2(raw[0].y, raw[3].y);
    int rightRy  = avg2(raw[1].y, raw[2].y);
    int topRy    = avg2(raw[0].y, raw[1].y);
    int bottomRy = avg2(raw[3].y, raw[2].y);
    int xCorrelationRawX = std::abs(rightRx - leftRx);
    int xCorrelationRawY = std::abs(rightRy - leftRy);
    swapAxes_ = xCorrelationRawY > xCorrelationRawX;
    if (!swapAxes_) {
        rawXLow_ = leftRx;
        rawXHigh_ = rightRx;
        rawYLow_ = topRy;
        rawYHigh_ = bottomRy;
    } else {
        rawXLow_ = leftRy;
        rawXHigh_ = rightRy;
        rawYLow_ = topRx;
        rawYHigh_ = bottomRx;
    }
    Preferences prefs;
    if (prefs.begin("pc-touch", false)) {
        prefs.putBool("swap", swapAxes_);
        prefs.putInt("xl", rawXLow_);
        prefs.putInt("xh", rawXHigh_);
        prefs.putInt("yl", rawYLow_);
        prefs.putInt("yh", rawYHigh_);
        prefs.putBool("valid", true);
        prefs.end();
        calValid_ = true;
    }
}
