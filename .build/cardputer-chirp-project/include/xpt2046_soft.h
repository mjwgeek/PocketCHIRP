#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include "hw_config.h"

struct TouchPoint {
    int16_t x = -1;
    int16_t y = -1;
    uint16_t pressure = 0;
    bool pressed = false;
};

struct RawTouchPoint {
    uint16_t x = 0;
    uint16_t y = 0;
    uint16_t pressure = 0;
    bool pressed = false;
};

class XPT2046Soft {
public:
    void begin();
    RawTouchPoint readRaw();
    TouchPoint read();

    bool loadCalibration();
    void clearCalibration();
    bool calibrated() const { return calValid_; }

    void saveFourPointCalibration(const RawTouchPoint raw[4]);

private:
    uint8_t transfer8(uint8_t v);
    uint16_t read12(uint8_t command);
    uint16_t median5(uint16_t* values);
    int mapAxis(int raw, int rawAtLow, int rawAtHigh, int screenLow, int screenHigh) const;

    bool calValid_ = false;
    bool swapAxes_ = false;
    int rawXLow_ = 300, rawXHigh_ = 3800;
    int rawYLow_ = 300, rawYHigh_ = 3800;
};
