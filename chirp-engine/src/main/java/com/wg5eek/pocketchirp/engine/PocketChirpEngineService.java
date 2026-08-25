package com.wg5eek.pocketchirp.engine;

// PocketCHIRP 2.x architecture:
// This is the separate GPL CHIRP runtime/driver process. CHIRP and Python stay
// in this companion package and must not be re-embedded into the proprietary
// PocketCHIRP application APK. Communication crosses the defined AIDL/Binder
// boundary only.

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.wg5eek.pocketchirp.IPocketChirpEngine;
import com.wg5eek.pocketchirp.IPocketChirpTransport;

import java.io.ByteArrayOutputStream;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/** GPL companion service. No PocketCHIRP UI, billing, cloud, USB or BLE code. */
public final class PocketChirpEngineService extends Service {
    public static final int IPC_VERSION = 4;
    private static final int MAX_IMAGE_BYTES = 32 * 1024 * 1024;
    private static final int MAX_DRIVER_BYTES = 2 * 1024 * 1024;

    @Override public void onCreate() {
        super.onCreate();
        if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
        bridge();
    }

    private final IPocketChirpEngine.Stub binder = new IPocketChirpEngine.Stub() {
        @Override public int getPocketChirpApiVersion() { return IPC_VERSION; }
        @Override public String requestJson(String requestJson) { return callString("pocketchirp_engine_request_json", requestJson); }
        @Override public ParcelFileDescriptor getWorkingImage() { return pipeForBytes(callBytes("get_last_image_bytes")); }
        @Override public String loadImage(ParcelFileDescriptor image) { return callString("load_editor_image_bytes", readAll(image, MAX_IMAGE_BYTES)); }
        @Override public String previewImageConversion(ParcelFileDescriptor image) { return callString("preview_image_conversion_bytes", readAll(image, MAX_IMAGE_BYTES)); }
        @Override public String validateImage(ParcelFileDescriptor image) { return callString("validate_current_image_bytes", readAll(image, MAX_IMAGE_BYTES)); }
        @Override public String identifyImage(ParcelFileDescriptor image) { return callString("identify_image_bytes_json", readAll(image, MAX_IMAGE_BYTES)); }
        @Override public String imageCompatibility(ParcelFileDescriptor image) { return callString("image_compatibility_bytes_json", readAll(image, MAX_IMAGE_BYTES)); }

        @Override public String registerCustomDriver(ParcelFileDescriptor source, String filename,
                                                     boolean selectLoaded, String sha256) {
            byte[] bytes = readAll(source, MAX_DRIVER_BYTES);
            String expected = sha256 == null ? "" : sha256.trim().toLowerCase(Locale.US);
            String actual = sha256(bytes);
            if (!expected.isEmpty() && !expected.equals(actual)) {
                throw new IllegalArgumentException("Custom driver SHA-256 mismatch");
            }
            String text = new String(bytes, StandardCharsets.UTF_8);
            return callString("load_custom_driver_source_json", text, filename, selectLoaded, actual);
        }

        @Override public String getBleDriverFacts() {
            return callString("selected_ble_driver_facts_json");
        }
        @Override public String autoProbe(IPocketChirpTransport transport, String transportKind) {
            return callString("radio_auto_probe_json", proxy(transport), transportKind);
        }
        @Override public String downloadRadioOnce(IPocketChirpTransport transport, int attempt, String transportKind) {
            return callString("download_selected_editor_once_result_json", proxy(transport), attempt, transportKind);
        }
        @Override public ParcelFileDescriptor backupRadioOnce(IPocketChirpTransport transport) {
            return pipeForBytes(callBytes("backup_connected_radio_once_bytes", proxy(transport)));
        }
        @Override public String writeRadioOnce(IPocketChirpTransport transport,
                                               ParcelFileDescriptor image,
                                               String transportContextJson) {
            return callString("controlled_write_current_once_bytes", proxy(transport),
                    readAll(image, MAX_IMAGE_BYTES), transportContextJson);
        }
    };

    @Override public IBinder onBind(Intent intent) { return binder; }

    private PocketChirpBinderTransportProxy proxy(IPocketChirpTransport transport) {
        return new PocketChirpBinderTransportProxy(transport);
    }

    private PyObject bridge() { return Python.getInstance().getModule("bridge"); }
    private String callString(String name, Object... args) {
        try { return bridge().callAttr(name, args).toString(); }
        catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException(name + " failed: " + e, e); }
    }
    private byte[] callBytes(String name, Object... args) {
        PyObject out = bridge().callAttr(name, args);
        byte[] bytes = out == null ? null : out.toJava(byte[].class);
        return bytes == null ? new byte[0] : bytes;
    }

    private static byte[] readAll(ParcelFileDescriptor pfd, int maxBytes) {
        if (pfd == null) return new byte[0];
        try (ParcelFileDescriptor closeable = pfd;
             InputStream in = new FileInputStream(closeable.getFileDescriptor());
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16384];
            int total = 0;
            int n;
            while ((n = in.read(buffer)) > 0) {
                total += n;
                if (total > maxBytes) throw new IllegalArgumentException("Input exceeds engine size limit");
                out.write(buffer, 0, n);
            }
            return out.toByteArray();
        } catch (Exception e) {
            throw new IllegalStateException("Could not read engine input stream: " + e.getMessage(), e);
        }
    }

    private static ParcelFileDescriptor pipeForBytes(byte[] bytes) {
        try {
            ParcelFileDescriptor[] pipe = ParcelFileDescriptor.createPipe();
            ParcelFileDescriptor readSide = pipe[0];
            ParcelFileDescriptor writeSide = pipe[1];
            byte[] copy = bytes == null ? new byte[0] : bytes.clone();
            Thread writer = new Thread(() -> {
                try (ParcelFileDescriptor closeable = writeSide;
                     FileOutputStream out = new FileOutputStream(closeable.getFileDescriptor())) {
                    out.write(copy);
                    out.flush();
                } catch (Exception ignored) { }
            }, "PocketCHIRP-engine-pipe");
            writer.setDaemon(true);
            writer.start();
            return readSide;
        } catch (Exception e) {
            throw new IllegalStateException("Could not create engine output pipe", e);
        }
    }

    private static String sha256(byte[] bytes) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(bytes == null ? new byte[0] : bytes);
            StringBuilder out = new StringBuilder(hash.length * 2);
            for (byte b : hash) out.append(String.format(Locale.US, "%02x", b & 0xff));
            return out.toString();
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
