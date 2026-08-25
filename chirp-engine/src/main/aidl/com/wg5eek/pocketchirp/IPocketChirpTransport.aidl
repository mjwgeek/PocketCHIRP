package com.wg5eek.pocketchirp;

/**
 * Minimal neutral serial/byte-stream transport owned by proprietary PocketCHIRP.
 *
 * No Android BLE candidate, GATT profile, MTU, retry, resolver or UI policy is
 * exposed to the GPL engine. Those are applied before each CHIRP clone attempt.
 */
interface IPocketChirpTransport {
    byte[] readBytes(int requested);
    int writeBytes(in byte[] data);
    int availableBytes();
    void setTimeoutMs(int value);
    void setWriteTimeoutMs(int value);
    void setBaudRate(int value);
    void setSerialParameters(int baudRate, int dataBits, double stopBits, String parity);
    void setRts(boolean value);
    void setDtr(boolean value);
    boolean setRtsCtsFlowControl(boolean enabled);
    void clearInputBuffer();
    void clearOutputBuffer();
    void flushOutput();
    void onChirpProgress(String message, int current, int maximum);

    // These are transport-shape facts needed by CHIRP compatibility adapters,
    // not Android BLE policy controls.
    boolean isBleTransport();
    boolean isNativeUsbBulkTransport();
    int getNativeUsbVendorId();
    int getNativeUsbProductId();
}
