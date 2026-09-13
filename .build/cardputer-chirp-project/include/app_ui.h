#pragma once
#include <Arduino.h>
#include <array>
#include "ext_display_port.h"
#include "uvk5_driver.h"
#include "pcfp_transport.h"

class AppUI {
public:
    void begin();
    void drawHome(const PcfpTransport& transport, bool sdReady);
    void drawProgress(const String& title, size_t done, size_t total, const String& detail = "");
    void drawError(const String& title, const String& message);
    void drawChannels(const std::array<uint8_t, UVK5Driver::IMAGE_SIZE>& image,
                      const UVK5Driver& driver, int selected, int top,
                      const String& firmware);
    void drawTouchCalibrationTarget(int x, int y, int step);
    void drawTouchCalibrationMessage(const String& msg);
    void drawBuiltInStatus(const String& line1, const String& line2 = "", int progressPct = -1);

    static String formatFreq(uint32_t hz);

private:
    void header(const String& title, const String& right = "");
    void button(int x, int y, int w, int h, const String& label, bool enabled = true);
};
