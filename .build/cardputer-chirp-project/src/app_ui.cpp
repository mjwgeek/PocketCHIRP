#include "app_ui.h"
#include <M5Cardputer.h>

LGFX_CardputerCHIRP ExtDisplay;

void AppUI::begin() {
    ExtDisplay.init();
    ExtDisplay.setRotation(7);
    ExtDisplay.setTextWrap(false);
    ExtDisplay.fillScreen(TFT_BLACK);
    M5Cardputer.Display.setRotation(1);
    M5Cardputer.Display.setTextWrap(false);
    M5Cardputer.Display.fillScreen(TFT_BLACK);
}

void AppUI::header(const String& title, const String& right) {
    ExtDisplay.fillRect(0, 0, 320, 28, 0x18E3);
    ExtDisplay.setTextColor(TFT_WHITE, 0x18E3);
    ExtDisplay.setTextSize(2);
    ExtDisplay.setCursor(8, 7);
    ExtDisplay.print(title);
    if (right.length()) {
        ExtDisplay.setTextSize(1);
        int w = ExtDisplay.textWidth(right);
        ExtDisplay.setCursor(312 - w, 10);
        ExtDisplay.print(right);
    }
}

void AppUI::button(int x, int y, int w, int h, const String& label, bool enabled) {
    uint16_t bg = enabled ? 0x3186 : 0x2104;
    uint16_t fg = enabled ? TFT_WHITE : 0x7BEF;
    ExtDisplay.fillRoundRect(x, y, w, h, 5, bg);
    ExtDisplay.drawRoundRect(x, y, w, h, 5, enabled ? 0x7BEF : 0x4208);
    ExtDisplay.setTextColor(fg, bg);
    ExtDisplay.setTextSize(1);
    int tw = ExtDisplay.textWidth(label);
    ExtDisplay.setCursor(x + (w - tw) / 2, y + (h - 8) / 2);
    ExtDisplay.print(label);
}

void AppUI::drawHome(const PcfpTransport& transport, bool sdReady) {
    ExtDisplay.fillScreen(TFT_BLACK);
    header("CardputerCHIRP", "M1 read-only");
    ExtDisplay.setTextSize(1);
    ExtDisplay.setTextColor(0xBDF7, TFT_BLACK);
    ExtDisplay.setCursor(12, 42);
    ExtDisplay.print("Transport");
    ExtDisplay.setTextColor(TFT_WHITE, TFT_BLACK);
    ExtDisplay.setCursor(12, 58);
    ExtDisplay.print(transport.statusText());
    ExtDisplay.setTextColor(0xBDF7, TFT_BLACK);
    ExtDisplay.setCursor(12, 82);
    ExtDisplay.print("Radio driver");
    ExtDisplay.setTextColor(TFT_WHITE, TFT_BLACK);
    ExtDisplay.setCursor(12, 98);
    ExtDisplay.print("Quansheng UV-K5 / UV-K6 protocol");
    ExtDisplay.setTextColor(0xBDF7, TFT_BLACK);
    ExtDisplay.setCursor(12, 122);
    ExtDisplay.print("Storage");
    ExtDisplay.setTextColor(sdReady ? TFT_GREEN : TFT_YELLOW, TFT_BLACK);
    ExtDisplay.setCursor(12, 138);
    ExtDisplay.print(sdReady ? "microSD ready - auto backup ON" : "microSD unavailable - RAM only");
    button(8, 190, 72, 40, "CONNECT", true);
    button(86, 190, 72, 40, "READ", transport.state() == PcfpTransport::State::Connected || transport.isReady());
    button(164, 190, 72, 40, "FILES", sdReady);
    button(242, 190, 70, 40, "WRITE", false);
    drawBuiltInStatus("CardputerCHIRP M1", transport.statusText());
}

void AppUI::drawProgress(const String& title, size_t done, size_t total, const String& detail) {
    ExtDisplay.fillScreen(TFT_BLACK);
    header(title);
    int pct = total ? static_cast<int>((done * 100) / total) : 0;
    ExtDisplay.setTextColor(TFT_WHITE, TFT_BLACK);
    ExtDisplay.setTextSize(2);
    ExtDisplay.setCursor(20, 64);
    ExtDisplay.printf("%d%%", pct);
    ExtDisplay.drawRect(20, 100, 280, 24, 0x7BEF);
    int fill = total ? static_cast<int>((276ULL * done) / total) : 0;
    ExtDisplay.fillRect(22, 102, fill, 20, TFT_GREEN);
    ExtDisplay.setTextSize(1);
    ExtDisplay.setCursor(20, 142);
    ExtDisplay.printf("%u / %u bytes", static_cast<unsigned>(done), static_cast<unsigned>(total));
    if (detail.length()) {
        ExtDisplay.setCursor(20, 162);
        ExtDisplay.print(detail);
    }
    drawBuiltInStatus(title, detail, pct);
}

void AppUI::drawError(const String& title, const String& message) {
    ExtDisplay.fillScreen(TFT_BLACK);
    header(title);
    ExtDisplay.setTextColor(TFT_RED, TFT_BLACK);
    ExtDisplay.setTextSize(2);
    ExtDisplay.setCursor(12, 48);
    ExtDisplay.print("ERROR");
    ExtDisplay.setTextColor(TFT_WHITE, TFT_BLACK);
    ExtDisplay.setTextSize(1);
    ExtDisplay.setCursor(12, 82);
    ExtDisplay.setTextWrap(true);
    ExtDisplay.print(message);
    ExtDisplay.setTextWrap(false);
    button(110, 188, 100, 38, "BACK", true);
    drawBuiltInStatus("ERROR", message);
}

String AppUI::formatFreq(uint32_t hz) {
    char buf[20];
    snprintf(buf, sizeof(buf), "%lu.%05lu",
             static_cast<unsigned long>(hz / 1000000UL),
             static_cast<unsigned long>((hz % 1000000UL) / 10UL));
    return String(buf);
}

void AppUI::drawChannels(const std::array<uint8_t, UVK5Driver::IMAGE_SIZE>& image,
                         const UVK5Driver& driver, int selected, int top,
                         const String& firmware) {
    ExtDisplay.fillScreen(TFT_BLACK);
    header("UV-K5/K6 Memories", firmware);
    ExtDisplay.setTextSize(1);
    constexpr int rowH = 19;
    constexpr int rows = 8;
    for (int r = 0; r < rows; ++r) {
        int idx = top + r;
        if (idx >= 200) break;
        UVK5Channel ch = driver.decodeChannel(image, idx);
        int y = 34 + r * rowH;
        bool sel = idx == selected;
        uint16_t bg = sel ? 0x39E7 : TFT_BLACK;
        if (sel) ExtDisplay.fillRect(4, y - 2, 312, rowH, bg);
        ExtDisplay.setTextColor(sel ? TFT_YELLOW : TFT_WHITE, bg);
        ExtDisplay.setCursor(7, y);
        ExtDisplay.printf("%03d", idx + 1);
        ExtDisplay.setCursor(37, y);
        if (ch.empty) {
            ExtDisplay.setTextColor(0x7BEF, bg);
            ExtDisplay.print("<empty>");
            continue;
        }
        String name = ch.name.length() ? ch.name : "-";
        if (name.length() > 10) name = name.substring(0, 10);
        ExtDisplay.printf("%-10s", name.c_str());
        ExtDisplay.setCursor(116, y);
        ExtDisplay.print(formatFreq(ch.rxHz));
        ExtDisplay.setCursor(214, y);
        ExtDisplay.printf("%c %-3s %s", ch.duplex, ch.mode.c_str(), ch.power.c_str());
    }
    button(8, 194, 72, 36, "HOME", true);
    button(86, 194, 72, 36, "UP", selected > 0);
    button(164, 194, 72, 36, "DOWN", selected < 199);
    button(242, 194, 70, 36, "EDIT", false);
    drawBuiltInStatus(String("CH ") + (selected + 1), firmware);
}

void AppUI::drawTouchCalibrationTarget(int x, int y, int step) {
    ExtDisplay.fillScreen(TFT_BLACK);
    header("Touch calibration", String(step) + "/4");
    ExtDisplay.setTextColor(TFT_WHITE, TFT_BLACK);
    ExtDisplay.setTextSize(1);
    ExtDisplay.setCursor(10, 38);
    ExtDisplay.print("Touch and hold the crosshair. ENTER skips touch.");
    ExtDisplay.drawCircle(x, y, 12, TFT_YELLOW);
    ExtDisplay.drawFastHLine(x - 18, y, 36, TFT_YELLOW);
    ExtDisplay.drawFastVLine(x, y - 18, 36, TFT_YELLOW);
    drawBuiltInStatus("Touch calibration", String(step) + "/4");
}

void AppUI::drawTouchCalibrationMessage(const String& msg) {
    ExtDisplay.fillScreen(TFT_BLACK);
    header("Touch calibration");
    ExtDisplay.setTextColor(TFT_WHITE, TFT_BLACK);
    ExtDisplay.setTextSize(2);
    ExtDisplay.setCursor(20, 90);
    ExtDisplay.print(msg);
    drawBuiltInStatus("Touch", msg);
}

void AppUI::drawBuiltInStatus(const String& line1, const String& line2, int progressPct) {
    auto& d = M5Cardputer.Display;
    d.fillScreen(TFT_BLACK);
    d.setTextColor(TFT_GREEN, TFT_BLACK);
    d.setTextSize(1);
    d.setCursor(6, 8);
    d.print(line1);
    d.setTextColor(TFT_WHITE, TFT_BLACK);
    d.setCursor(6, 30);
    String l2 = line2;
    if (l2.length() > 35) l2 = l2.substring(0, 35);
    d.print(l2);
    if (progressPct >= 0) {
        d.drawRect(6, 58, 228, 16, 0x7BEF);
        d.fillRect(8, 60, (224 * constrain(progressPct, 0, 100)) / 100, 12, TFT_GREEN);
        d.setCursor(6, 84);
        d.printf("%d%%", progressPct);
    } else {
        d.setCursor(6, 84);
        d.print("R=read  C=connect");
    }
}
