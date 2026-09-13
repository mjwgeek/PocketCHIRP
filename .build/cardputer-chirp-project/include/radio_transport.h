#pragma once
#include <Arduino.h>

class RadioTransport {
public:
    virtual ~RadioTransport() = default;
    virtual bool isReady() const = 0;
    virtual bool writeBytes(const uint8_t* data, size_t len) = 0;
    virtual size_t available() = 0;
    virtual int readByte(uint32_t timeoutMs) = 0;
    virtual void clearRx() = 0;

    bool readExact(uint8_t* out, size_t len, uint32_t timeoutMs) {
        uint32_t deadline = millis() + timeoutMs;
        size_t got = 0;
        while (got < len) {
            int b = readByte(5);
            if (b >= 0) {
                out[got++] = static_cast<uint8_t>(b);
                continue;
            }
            if (static_cast<int32_t>(millis() - deadline) >= 0) return false;
            delay(1);
        }
        return true;
    }
};
