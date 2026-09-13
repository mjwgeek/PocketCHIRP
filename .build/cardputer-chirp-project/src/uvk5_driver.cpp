#include "uvk5_driver.h"
#include <cstring>

static const uint8_t UVK5_XOR_TABLE[16] = {
    22, 108, 20, 230, 46, 145, 13, 64,
    33, 53, 213, 64, 19, 3, 233, 128
};

uint16_t UVK5Driver::crc16Xmodem(const uint8_t* data, size_t len) {
    uint16_t crc = 0;
    for (size_t i = 0; i < len; ++i) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (int bit = 0; bit < 8; ++bit) {
            crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
                                 : static_cast<uint16_t>(crc << 1);
        }
    }
    return crc;
}

void UVK5Driver::xorArray(uint8_t* data, size_t len) {
    for (size_t i = 0; i < len; ++i) data[i] ^= UVK5_XOR_TABLE[i & 0x0F];
}

size_t UVK5Driver::makeCommand(const uint8_t* payload, size_t payloadLen,
                               uint8_t* out, size_t outCapacity) {
    size_t total = 4 + payloadLen + 2 + 2;
    if (!payload || !out || payloadLen > 255 || outCapacity < total) return 0;
    out[0] = 0xAB;
    out[1] = 0xCD;
    out[2] = static_cast<uint8_t>(payloadLen);
    out[3] = 0x00;
    memcpy(out + 4, payload, payloadLen);
    uint16_t crc = crc16Xmodem(payload, payloadLen);
    out[4 + payloadLen] = static_cast<uint8_t>(crc & 0xFF);
    out[5 + payloadLen] = static_cast<uint8_t>((crc >> 8) & 0xFF);
    xorArray(out + 4, payloadLen + 2);
    out[6 + payloadLen] = 0xDC;
    out[7 + payloadLen] = 0xBA;
    return total;
}

bool UVK5Driver::sendCommand(const uint8_t* payload, size_t len) {
    uint8_t packet[300];
    size_t n = makeCommand(payload, len, packet, sizeof(packet));
    if (!n) {
        lastError_ = "UV-K5 command encoding failed";
        return false;
    }
    if (!transport_.writeBytes(packet, n)) {
        lastError_ = "Transport write failed";
        return false;
    }
    return true;
}

bool UVK5Driver::receiveReply(uint8_t* out, size_t outCap, size_t& outLen, uint32_t timeoutMs) {
    outLen = 0;
    uint8_t header[4];
    if (!transport_.readExact(header, 4, timeoutMs)) {
        lastError_ = "No response from UV-K5/K6";
        return false;
    }
    if (header[0] != 0xAB || header[1] != 0xCD || header[3] != 0x00) {
        lastError_ = "Bad UV-K5 response header";
        return false;
    }
    size_t bodyLen = header[2];
    if (bodyLen > outCap) {
        lastError_ = "UV-K5 reply too large";
        return false;
    }
    if (!transport_.readExact(out, bodyLen, timeoutMs)) {
        lastError_ = "Short UV-K5 response body";
        return false;
    }
    uint8_t footer[4];
    if (!transport_.readExact(footer, 4, timeoutMs)) {
        lastError_ = "Short UV-K5 response footer";
        return false;
    }
    if (footer[2] != 0xDC || footer[3] != 0xBA) {
        lastError_ = "Bad UV-K5 response footer";
        return false;
    }
    xorArray(out, bodyLen);
    outLen = bodyLen;
    return true;
}

bool UVK5Driver::hello(String& firmware) {
    static const uint8_t helloPacket[] = {0x14,0x05,0x04,0x00,0x6A,0x39,0x57,0x64};
    uint8_t reply[128];
    for (int attempt = 0; attempt < 5; ++attempt) {
        transport_.clearRx();
        if (!sendCommand(helloPacket, sizeof(helloPacket))) return false;
        size_t n = 0;
        if (!receiveReply(reply, sizeof(reply), n, 800)) {
            delay(80);
            continue;
        }
        if (n >= 2 && reply[0] == 0x18 && reply[1] == 0x05) {
            lastError_ = "Radio is in firmware-programming mode; reboot normally";
            return false;
        }
        firmware = "";
        for (size_t i = 4; i < n && i < 28; ++i) {
            if (reply[i] < 0x20 || reply[i] > 0x7E) break;
            firmware += static_cast<char>(reply[i]);
        }
        if (firmware.length()) return true;
    }
    lastError_ = "Failed to initialize UV-K5/K6";
    return false;
}

bool UVK5Driver::readMem(uint16_t offset, uint8_t len, uint8_t* out) {
    uint8_t cmd[12] = {
        0x1B,0x05,0x08,0x00,
        static_cast<uint8_t>(offset & 0xFF),
        static_cast<uint8_t>((offset >> 8) & 0xFF),
        len,0x00,
        0x6A,0x39,0x57,0x64
    };
    if (!sendCommand(cmd, sizeof(cmd))) return false;
    uint8_t reply[192];
    size_t n = 0;
    if (!receiveReply(reply, sizeof(reply), n, 1000)) return false;
    if (n < static_cast<size_t>(8 + len)) {
        lastError_ = "UV-K5 memory reply was incomplete";
        return false;
    }
    memcpy(out, reply + 8, len);
    return true;
}

bool UVK5Driver::download(std::array<uint8_t, IMAGE_SIZE>& image,
                           String& firmware,
                           std::function<void(size_t,size_t)> progress) {
    if (!transport_.isReady()) {
        lastError_ = "Radio transport is not ready";
        return false;
    }
    if (!hello(firmware)) return false;
    for (size_t addr = 0; addr < IMAGE_SIZE; addr += BLOCK_SIZE) {
        if (!readMem(static_cast<uint16_t>(addr), static_cast<uint8_t>(BLOCK_SIZE), image.data() + addr)) {
            lastError_ += String(" at 0x") + String(static_cast<unsigned>(addr), HEX);
            return false;
        }
        if (progress) progress(addr + BLOCK_SIZE, IMAGE_SIZE);
        delay(1);
    }
    return true;
}

uint32_t UVK5Driver::le32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) |
           (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

UVK5Channel UVK5Driver::decodeChannel(const std::array<uint8_t, IMAGE_SIZE>& image, int index0) const {
    UVK5Channel ch;
    if (index0 < 0 || index0 >= 200) return ch;
    ch.number = static_cast<uint16_t>(index0 + 1);
    size_t base = static_cast<size_t>(index0) * 16;
    uint32_t rawFreq = le32(image.data() + base);
    uint32_t rawOffset = le32(image.data() + base + 4);
    if (rawFreq == 0 || rawFreq == 0xFFFFFFFF) {
        ch.empty = true;
        return ch;
    }
    ch.empty = false;
    ch.rxHz = rawFreq * 10UL;
    ch.offsetHz = rawOffset * 10UL;
    uint8_t flags1 = image[base + 11];
    uint8_t flags2 = image[base + 12];
    uint8_t shift = flags1 & 0x03;
    if (rawOffset == 0) ch.duplex = ' ';
    else if (shift == 0x02) {
        if (rawFreq == rawOffset) { ch.txOff = true; ch.duplex = 'X'; }
        else ch.duplex = '-';
    } else if (shift == 0x01) ch.duplex = '+';
    else ch.duplex = ' ';
    bool am = (flags1 & 0x10) != 0;
    bool narrow = (flags2 & 0x02) != 0;
    ch.mode = am ? (narrow ? "NAM" : "AM") : (narrow ? "NFM" : "FM");
    uint8_t pwr = (flags2 >> 2) & 0x03;
    ch.power = pwr == 2 ? "H" : (pwr == 1 ? "M" : "L");
    size_t nameBase = 0x0F50 + static_cast<size_t>(index0) * 16;
    String name;
    for (int i = 0; i < 16; ++i) {
        uint8_t c = image[nameBase + i];
        if (c == 0x00 || c == 0xFF) break;
        if (c >= 0x20 && c <= 0x7E) name += static_cast<char>(c);
    }
    name.trim();
    ch.name = name;
    return ch;
}
