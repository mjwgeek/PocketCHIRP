package com.wg5eek.pocketchirp.engine;

import com.wg5eek.pocketchirp.IPocketChirpTransport;

import android.os.RemoteException;

/**
 * GPL-engine-side minimal serial proxy.
 *
 * <p>Contains no Android USB/BLE implementation and intentionally exposes no
 * BLE candidate/profile/retry controls. Proprietary PocketCHIRP configures the
 * physical transport before each CHIRP protocol attempt.</p>
 */
final class PocketChirpBinderTransportProxy {
    private final IPocketChirpTransport remote;

    PocketChirpBinderTransportProxy(IPocketChirpTransport remote) {
        if (remote == null) throw new IllegalArgumentException("Transport binder is required");
        this.remote = remote;
    }

    public byte[] readBytes(int requested) throws java.io.IOException { return call(() -> remote.readBytes(requested)); }
    public int writeBytes(byte[] data) throws java.io.IOException { return call(() -> remote.writeBytes(data)); }
    public int availableBytes() throws java.io.IOException { return call(remote::availableBytes); }
    public void setTimeoutMs(int value) { run(() -> remote.setTimeoutMs(value)); }
    public void setWriteTimeoutMs(int value) { run(() -> remote.setWriteTimeoutMs(value)); }
    public void setBaudRate(int value) throws java.io.IOException { callVoid(() -> remote.setBaudRate(value)); }
    public void setSerialParameters(int baud, int bits, double stop, String parity) throws java.io.IOException {
        callVoid(() -> remote.setSerialParameters(baud, bits, stop, parity));
    }
    public void setRts(boolean value) throws java.io.IOException { callVoid(() -> remote.setRts(value)); }
    public void setDtr(boolean value) throws java.io.IOException { callVoid(() -> remote.setDtr(value)); }
    public boolean setRtsCtsFlowControl(boolean enabled) throws java.io.IOException {
        return call(() -> remote.setRtsCtsFlowControl(enabled));
    }
    public void clearInputBuffer() throws java.io.IOException { callVoid(remote::clearInputBuffer); }
    public void clearOutputBuffer() throws java.io.IOException { callVoid(remote::clearOutputBuffer); }
    public void flushOutput() throws java.io.IOException { callVoid(remote::flushOutput); }
    public void onChirpProgress(String message, int current, int maximum) {
        run(() -> remote.onChirpProgress(message, current, maximum));
    }
    public String resetProbeSession(int baudRate, String family) throws java.io.IOException {
        return call(() -> remote.resetProbeSession(baudRate, family));
    }
    public int getProbeResetCount() { return safe(0, remote::getProbeResetCount); }
    public String getProbeResetMode() { return safe("unknown", remote::getProbeResetMode); }
    public boolean hasHardProbeReset() { return safe(false, remote::hasHardProbeReset); }

    public boolean isBleTransport() { return safe(false, remote::isBleTransport); }
    public boolean isNativeUsbBulkTransport() { return safe(false, remote::isNativeUsbBulkTransport); }
    public int getNativeUsbVendorId() { return safe(-1, remote::getNativeUsbVendorId); }
    public int getNativeUsbProductId() { return safe(-1, remote::getNativeUsbProductId); }

    private interface RemoteCall<T> { T run() throws RemoteException; }
    private interface RemoteVoid { void run() throws RemoteException; }
    private static <T> T call(RemoteCall<T> c) throws java.io.IOException {
        try { return c.run(); }
        catch (RemoteException e) { throw new java.io.IOException("Transport Binder failed", e); }
    }
    private static void callVoid(RemoteVoid c) throws java.io.IOException {
        try { c.run(); }
        catch (RemoteException e) { throw new java.io.IOException("Transport Binder failed", e); }
    }
    private static void run(RemoteVoid c) {
        try { c.run(); } catch (RemoteException ignored) { }
    }
    private static <T> T safe(T fallback, RemoteCall<T> c) {
        try { return c.run(); } catch (RemoteException ignored) { return fallback; }
    }
}
