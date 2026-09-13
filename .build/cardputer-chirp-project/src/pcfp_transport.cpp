#include "pcfp_transport.h"

static PcfpTransport* g_transport = nullptr;

class PCFPScanCallbacks final : public NimBLEScanCallbacks {
    void onResult(const NimBLEAdvertisedDevice* dev) override {
        if (g_transport) g_transport->onScanResult(dev);
    }
    void onScanEnd(const NimBLEScanResults&, int) override {
        if (g_transport) g_transport->onScanEnd();
    }
};

class PCFPClientCallbacks final : public NimBLEClientCallbacks {
    void onDisconnect(NimBLEClient*, int reason) override {
        if (g_transport) g_transport->onDisconnected(reason);
    }
};

static PCFPScanCallbacks g_scanCallbacks;
static PCFPClientCallbacks g_clientCallbacks;

static void rxNotifyCB(NimBLERemoteCharacteristic*, uint8_t* data, size_t len, bool) {
    if (g_transport) g_transport->onRxNotify(data, len);
}

static void controlNotifyCB(NimBLERemoteCharacteristic*, uint8_t* data, size_t len, bool) {
    if (g_transport) g_transport->onControlNotify(data, len);
}

PcfpTransport::PcfpTransport() { g_transport = this; }

void PcfpTransport::setStatus(State s, const String& text) {
    state_ = s;
    status_ = text;
    Serial.printf("[PCFP] %s\n", text.c_str());
}

void PcfpTransport::begin() {
    NimBLEDevice::init("CardputerCHIRP");
    NimBLEDevice::setPower(3);
    NimBLEScan* scan = NimBLEDevice::getScan();
    scan->setScanCallbacks(&g_scanCallbacks, false);
    scan->setInterval(100);
    scan->setWindow(80);
    scan->setActiveScan(true);
    setStatus(State::Idle, "PCFP disconnected");
}

void PcfpTransport::startScan(uint32_t durationMs) {
    if (state_ == State::Scanning || state_ == State::Connecting) return;
    found_ = nullptr;
    setStatus(State::Scanning, "Scanning for PCFP...");
    NimBLEDevice::getScan()->start(durationMs, false, true);
}

void PcfpTransport::onScanResult(const NimBLEAdvertisedDevice* dev) {
    bool match = false;
    if (dev->isAdvertisingService(NimBLEUUID(PC_UUID_SERVICE_STR))) match = true;
    if (!match && dev->haveName()) {
        std::string name = dev->getName();
        if (name == PC_BRIDGE_NAME || name.find("PocketCHIRP") != std::string::npos) match = true;
    }
    if (!match) return;
    found_ = dev;
    NimBLEDevice::getScan()->stop();
    setStatus(State::Connecting, "PCFP found; connecting...");
}

void PcfpTransport::onScanEnd() {
    if (state_ == State::Scanning && !found_) setStatus(State::Error, "PCFP not found");
}

void PcfpTransport::poll() {
    if (state_ == State::Connecting && found_) {
        if (!connectFound()) setStatus(State::Error, "PCFP connection failed");
    }
}

bool PcfpTransport::connectFound() {
    client_ = NimBLEDevice::createClient();
    if (!client_) return false;
    client_->setClientCallbacks(&g_clientCallbacks, false);
    client_->setConnectionParams(12, 24, 0, 200);
    client_->setConnectTimeout(6000);
    if (!client_->connect(found_)) {
        NimBLEDevice::deleteClient(client_);
        client_ = nullptr;
        return false;
    }
    if (!discoverBridge()) {
        client_->disconnect();
        return false;
    }
    setStatus(State::Connected, "PCFP connected");
    return true;
}

bool PcfpTransport::discoverBridge() {
    NimBLERemoteService* svc = client_->getService(PC_UUID_SERVICE_STR);
    if (!svc) return false;
    dataTx_ = svc->getCharacteristic(PC_UUID_DATA_TX_STR);
    dataRx_ = svc->getCharacteristic(PC_UUID_DATA_RX_STR);
    control_ = svc->getCharacteristic(PC_UUID_CONTROL_STR);
    if (!dataTx_ || !dataRx_ || !control_) return false;
    bool rxOk = false;
    if (dataRx_->canNotify()) rxOk = dataRx_->subscribe(true, rxNotifyCB);
    else if (dataRx_->canIndicate()) rxOk = dataRx_->subscribe(false, rxNotifyCB);
    if (!rxOk) return false;
    bool ctlOk = false;
    if (control_->canNotify()) ctlOk = control_->subscribe(true, controlNotifyCB);
    else if (control_->canIndicate()) ctlOk = control_->subscribe(false, controlNotifyCB);
    if (!ctlOk) return false;
    return true;
}

bool PcfpTransport::waitControl(uint8_t expectedCommand, uint32_t timeoutMs, uint8_t* statusOut) {
    uint32_t deadline = millis() + timeoutMs;
    while (static_cast<int32_t>(millis() - deadline) < 0) {
        bool ready = false;
        size_t n = 0;
        uint8_t b0 = 0;
        uint8_t b1 = 0xFF;
        portENTER_CRITICAL(&controlMux_);
        if (controlReady_) {
            n = controlLen_;
            b0 = n > 0 ? controlBuf_[0] : 0;
            b1 = n > 1 ? controlBuf_[1] : 0xFF;
            controlReady_ = false;
            ready = true;
        }
        portEXIT_CRITICAL(&controlMux_);
        if (ready && b0 == static_cast<uint8_t>(expectedCommand | 0x80)) {
            if (statusOut) *statusOut = b1;
            return n >= 2;
        }
        delay(2);
    }
    return false;
}

bool PcfpTransport::startSession(uint32_t baud, uint8_t dataBits,
                                 uint8_t stopCode, uint8_t parityCode,
                                 bool dtr, bool rts) {
    if (state_ != State::Connected && state_ != State::SessionReady) {
        status_ = "PCFP is not connected";
        return false;
    }
    uint8_t req[10]{};
    req[0] = PC_CMD_START_SESSION;
    req[1] = static_cast<uint8_t>(baud & 0xFF);
    req[2] = static_cast<uint8_t>((baud >> 8) & 0xFF);
    req[3] = static_cast<uint8_t>((baud >> 16) & 0xFF);
    req[4] = static_cast<uint8_t>((baud >> 24) & 0xFF);
    req[5] = dataBits;
    req[6] = stopCode;
    req[7] = parityCode;
    req[8] = dtr ? 1 : 0;
    req[9] = rts ? 1 : 0;
    portENTER_CRITICAL(&controlMux_);
    controlReady_ = false;
    controlLen_ = 0;
    portEXIT_CRITICAL(&controlMux_);
    clearRx();
    if (!control_->writeValue(req, sizeof(req), true)) {
        setStatus(State::Error, "PCFP START_SESSION write failed");
        return false;
    }
    uint8_t st = 0xFF;
    if (!waitControl(PC_CMD_START_SESSION, 2500, &st)) {
        setStatus(State::Error, "PCFP START_SESSION timeout");
        return false;
    }
    if (st != PC_ST_OK) {
        if (st == PC_ST_NO_USB) setStatus(State::Error, "PCFP: no USB cable detected");
        else setStatus(State::Error, String("PCFP session error ") + String(st));
        return false;
    }
    setStatus(State::SessionReady, String("PCFP serial ready @ ") + baud);
    return true;
}

void PcfpTransport::endSession() {
    if (!control_ || !client_ || !client_->isConnected()) return;
    uint8_t req = PC_CMD_END_SESSION;
    control_->writeValue(&req, 1, true);
    if (state_ == State::SessionReady) setStatus(State::Connected, "PCFP connected");
}

void PcfpTransport::disconnect() {
    endSession();
    if (client_ && client_->isConnected()) client_->disconnect();
    setStatus(State::Idle, "PCFP disconnected");
}

void PcfpTransport::onDisconnected(int reason) {
    dataTx_ = nullptr;
    dataRx_ = nullptr;
    control_ = nullptr;
    clearRx();
    setStatus(State::Idle, String("PCFP disconnected (") + reason + ")");
}

bool PcfpTransport::writeBytes(const uint8_t* data, size_t len) {
    if (!isReady() || !dataTx_) return false;
    if (dataTx_->canWriteNoResponse()) return dataTx_->writeValue(data, len, false);
    return dataTx_->writeValue(data, len, true);
}

void PcfpTransport::onRxNotify(const uint8_t* data, size_t len) {
    portENTER_CRITICAL(&rxMux_);
    for (size_t i = 0; i < len; ++i) {
        size_t next = (rxHead_ + 1) % RX_CAP;
        if (next == rxTail_) rxTail_ = (rxTail_ + 1) % RX_CAP;
        rx_[rxHead_] = data[i];
        rxHead_ = next;
    }
    portEXIT_CRITICAL(&rxMux_);
}

void PcfpTransport::onControlNotify(const uint8_t* data, size_t len) {
    size_t n = len < sizeof(controlBuf_) ? len : sizeof(controlBuf_);
    portENTER_CRITICAL(&controlMux_);
    for (size_t i = 0; i < n; ++i) controlBuf_[i] = data[i];
    controlLen_ = n;
    controlReady_ = true;
    portEXIT_CRITICAL(&controlMux_);
}

size_t PcfpTransport::available() {
    portENTER_CRITICAL(&rxMux_);
    size_t n = (rxHead_ + RX_CAP - rxTail_) % RX_CAP;
    portEXIT_CRITICAL(&rxMux_);
    return n;
}

int PcfpTransport::readByte(uint32_t timeoutMs) {
    uint32_t deadline = millis() + timeoutMs;
    do {
        portENTER_CRITICAL(&rxMux_);
        if (rxTail_ != rxHead_) {
            uint8_t b = rx_[rxTail_];
            rxTail_ = (rxTail_ + 1) % RX_CAP;
            portEXIT_CRITICAL(&rxMux_);
            return b;
        }
        portEXIT_CRITICAL(&rxMux_);
        delay(1);
    } while (static_cast<int32_t>(millis() - deadline) < 0);
    return -1;
}

void PcfpTransport::clearRx() {
    portENTER_CRITICAL(&rxMux_);
    rxHead_ = rxTail_ = 0;
    portEXIT_CRITICAL(&rxMux_);
}

int PcfpTransport::rssi() const {
    return client_ && client_->isConnected() ? client_->getRssi() : -127;
}
