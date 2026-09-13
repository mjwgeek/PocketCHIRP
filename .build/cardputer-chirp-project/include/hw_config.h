#pragma once

namespace hw {
constexpr int TFT_CS   = 5;
constexpr int TFT_RST  = 3;
constexpr int TFT_DC   = 6;
constexpr int TFT_MOSI = 14;
constexpr int TFT_SCK  = 40;

constexpr int TOUCH_CS   = 4;
constexpr int TOUCH_MOSI = 13;
constexpr int TOUCH_MISO = 39;
constexpr int TOUCH_SCK  = 15;
constexpr int TOUCH_IRQ  = -1;

constexpr int SD_CS   = 12;
constexpr int SD_MOSI = 14;
constexpr int SD_MISO = 39;
constexpr int SD_SCK  = 40;

constexpr int EXT_W = 320;
constexpr int EXT_H = 240;
} // namespace hw
