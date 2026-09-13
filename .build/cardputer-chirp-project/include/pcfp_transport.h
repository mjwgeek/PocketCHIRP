#pragma once
#include <NimBLEDevice.h>
#include "radio_transport.h"
#include "bridge_protocol.h"

class PcfpTransport : public RadioTransport {
public:
    enum class State { Idle, Scanning, Connecting, Connected, SessionReady, Error };

    PcfpTransport();
    void begin();
    void startScan(uint32_t durationMs = 6000);
    void poll();
    bool startSession(uint32_t baud, uint8_t dataBits = 8,
                      uint8_t stopCode = 0, uint8_t parityCode = 0,
                      bool dtr = false, bool rts = false);
    void endSession();
    void disconnect();

    State state() const { return state_; }
    const String& statusText() const { return status_; }
    int rssi() const;

    bool isReady() const override { return state_ == State::SessionReady; }
    bool writeBytes(const uint8_t* data, size_t len) override;
    size_t available() override;
    int readByte(uint32_t timeoutMs) override;
    void clearRx() override;

    void onScanResult(const NimBLEAdvertisedDevice* dev);
    void onScanEnd();
    void onDisconnected(int reason);
    void onRxNotify(const uint8_t* data, size_t len);
    void onControlNotify(const uint8_t* data, size_t len);

private:
    bool connectFound();
    bool discoverBridge();
    bool waitControl(uint8_t expectedCommand, uint32_t timeoutMs, uint8_t* statusOut = nullptr);
    void setStatus(State s, const String& text);

    static constexpr size_t RX_CAP = 8192;
    uint8_t rx_[RX_CAP]{};
    size_t rxHead_ = 0;
    size_t rxTail_ = 0;
    portMUX_TYPE rxMux_ = portMUX_INITIALIZER_UNLOCKED;

    bool controlReady_ = false;
    uint8_t controlBuf_[64]{};
    size_t controlLen_ = 0;
    portMUX_TYPE controlMux_ = portMUX_INITIALIZER_UNLOCKED;

    State state_ = State::Idle;
    String status_ = "Idle";
    const NimBLEAdvertisedDevice* found_ = nullptr;
    NimBLEClient* client_ = nullptr;
    NimBLERemoteCharacteristic* dataTx_ = nullptr;
    NimBLERemoteCharacteristic* dataRx_ = nullptr;
    NimBLERemoteCharacteristic* control_ = nullptr;
};
