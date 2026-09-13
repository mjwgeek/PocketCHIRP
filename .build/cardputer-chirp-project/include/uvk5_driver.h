#pragma once
#include <Arduino.h>
#include <array>
#include <functional>
#include "radio_transport.h"

struct UVK5Channel {
    bool empty = true;
    uint16_t number = 0;
    String name;
    uint32_t rxHz = 0;
    uint32_t offsetHz = 0;
    char duplex = ' ';
    bool txOff = false;
    String mode;
    String power;
};

class UVK5Driver {
public:
    static constexpr size_t IMAGE_SIZE = 0x2000;
    static constexpr size_t BLOCK_SIZE = 0x80;
    static constexpr uint32_t BAUD = 38400;

    explicit UVK5Driver(RadioTransport& transport) : transport_(transport) {}

    bool download(std::array<uint8_t, IMAGE_SIZE>& image,
                  String& firmware,
                  std::function<void(size_t,size_t)> progress = {});

    UVK5Channel decodeChannel(const std::array<uint8_t, IMAGE_SIZE>& image, int index0) const;
    String lastError() const { return lastError_; }

    static size_t makeCommand(const uint8_t* payload, size_t payloadLen,
                              uint8_t* out, size_t outCapacity);

private:
    bool sendCommand(const uint8_t* payload, size_t len);
    bool receiveReply(uint8_t* out, size_t outCap, size_t& outLen, uint32_t timeoutMs = 1000);
    bool hello(String& firmware);
    bool readMem(uint16_t offset, uint8_t len, uint8_t* out);

    static uint16_t crc16Xmodem(const uint8_t* data, size_t len);
    static void xorArray(uint8_t* data, size_t len);
    static uint32_t le32(const uint8_t* p);

    RadioTransport& transport_;
    String lastError_;
};
