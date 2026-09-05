package com.wg5eek.pocketchirp.engine;

import android.app.AppOpsManager;
import android.app.Service;
import android.content.Intent;
import android.os.Binder;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.os.Process;
import android.util.Base64;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.wg5eek.pocketchirp.IPocketChirpEngine;
import com.wg5eek.pocketchirp.IPocketChirpTransport;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/** GPL companion service. No PocketCHIRP UI, billing, cloud, USB or BLE code. */
public final class PocketChirpEngineService extends Service {
    public static final int IPC_VERSION = 6;
    private static final int MAX_IMAGE_BYTES = 32 * 1024 * 1024;
    private static final int MAX_DRIVER_BYTES = 2 * 1024 * 1024;
    private static final int MAX_EDIT_BUNDLE_BYTES = 16 * 1024 * 1024;

    /*
     * PocketCHIRP and the CHIRP Engine are separate Google Play packages and
     * can therefore have different Play App Signing certificates.
     *
     * Do not replace this with a signature-level manifest permission unless
     * both Play listings are intentionally configured to use the same signing
     * certificate. Android checks a service permission before onBind/Binder
     * dispatch, which is exactly what caused the Store-installed bind failure.
     *
     * Instead, every incoming AIDL transaction is authenticated using the UID
     * supplied by Binder. AppOpsManager.checkPackage verifies that Android has
     * assigned the exact PocketCHIRP package name to that UID; the caller
     * cannot choose or spoof this UID value.
     */
    private static final String ALLOWED_CLIENT_PACKAGE = "com.wg5eek.pocketchirp";

    @Override public void onCreate() {
        super.onCreate();
        if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
        bridge();
    }

    private void enforcePocketChirpCaller() {
        final int uid = Binder.getCallingUid();

        // Permit calls originating inside this engine process itself.
        if (uid == Process.myUid()) return;

        AppOpsManager appOps = (AppOpsManager) getSystemService(APP_OPS_SERVICE);
        if (appOps == null) {
            throw new SecurityException("Unable to verify PocketCHIRP caller");
        }

        try {
            appOps.checkPackage(uid, ALLOWED_CLIENT_PACKAGE);
        } catch (SecurityException e) {
            throw new SecurityException(
                    "CHIRP Engine rejected caller uid=" + uid +
                    "; only " + ALLOWED_CLIENT_PACKAGE + " is allowed",
                    e);
        }
    }

    private final IPocketChirpEngine.Stub binder = new IPocketChirpEngine.Stub() {
        @Override public int getPocketChirpApiVersion() {
            enforcePocketChirpCaller();
            return IPC_VERSION;
        }

        @Override public String requestJson(String requestJson) {
            enforcePocketChirpCaller();
            return callString("pocketchirp_engine_request_json", requestJson);
        }

        @Override public ParcelFileDescriptor requestJsonStream(String requestJson) {
            enforcePocketChirpCaller();
            // LARGE-DOCUMENT IPC REGRESSION GUARD:
            // Never return radio documents or other bulk JSON as a Binder String.
            // Android's Binder transaction buffer is shared and finite; large
            // radios can exceed it even though the underlying radio read succeeds.
            String result = callString("pocketchirp_engine_request_json", requestJson);
            return pipeForBytes(result.getBytes(StandardCharsets.UTF_8));
        }

        @Override public ParcelFileDescriptor getWorkingImage() {
            enforcePocketChirpCaller();
            return pipeForBytes(callBytes("get_last_image_bytes"));
        }

        @Override public ParcelFileDescriptor loadImage(ParcelFileDescriptor image) {
            enforcePocketChirpCaller();
            // load_editor_image_bytes returns the complete neutral Radio Document.
            // Stream that document instead of returning it as a Binder String.
            String document = callString(
                    "load_editor_image_bytes", readAll(image, MAX_IMAGE_BYTES));
            return pipeForBytes(document.getBytes(StandardCharsets.UTF_8));
        }

        @Override public ParcelFileDescriptor previewImageConversion(ParcelFileDescriptor image) {
            enforcePocketChirpCaller();
            String preview = callString(
                    "preview_image_conversion_bytes", readAll(image, MAX_IMAGE_BYTES));
            return pipeForBytes(preview.getBytes(StandardCharsets.UTF_8));
        }

        @Override public String validateImage(ParcelFileDescriptor image) {
            enforcePocketChirpCaller();
            return callString("validate_current_image_bytes", readAll(image, MAX_IMAGE_BYTES));
        }

        @Override public String identifyImage(ParcelFileDescriptor image) {
            enforcePocketChirpCaller();
            return callString("identify_image_bytes_json", readAll(image, MAX_IMAGE_BYTES));
        }

        @Override public String imageCompatibility(ParcelFileDescriptor image) {
            enforcePocketChirpCaller();
            return callString("image_compatibility_bytes_json", readAll(image, MAX_IMAGE_BYTES));
        }

        @Override public ParcelFileDescriptor materializeEditorEdits(
                ParcelFileDescriptor baseImage, ParcelFileDescriptor editBundle) {
            enforcePocketChirpCaller();
            // Local PocketCHIRP edits cross the process boundary only at an
            // explicit materialization point (Save / Write / driver operation).
            // Both payloads use file descriptors so Binder never carries the
            // potentially-large editor state or image inline.
            byte[] base = readAll(baseImage, MAX_IMAGE_BYTES);
            byte[] edits = readAll(editBundle, MAX_EDIT_BUNDLE_BYTES);
            byte[] materialized = callBytes("materialize_editor_edits_bytes", base, edits);

            // MATERIALIZATION IPC REGRESSION GUARD:
            // A valid base image can never legitimately materialize to zero bytes.
            // callBytes historically mapped a null Chaquopy byte[] conversion to an
            // empty Java array, hiding the distinction between an engine result and
            // an interop conversion failure. Retry through a string-only base64
            // boundary before failing closed. This fallback never touches radio I/O.
            if (materialized.length == 0 && base.length != 0) {
                String encoded = callString("materialize_editor_edits_b64", base, edits);
                if (encoded != null && !encoded.isEmpty()) {
                    materialized = Base64.decode(encoded, Base64.DEFAULT);
                }
            }
            if (materialized.length == 0) {
                throw new IllegalStateException(
                        "CHIRP Engine materialized an empty image from a non-empty base image");
            }
            return fileForBytes(materialized);
        }

        @Override public String registerCustomDriver(ParcelFileDescriptor source, String filename,
                                                     boolean selectLoaded, String sha256) {
            enforcePocketChirpCaller();
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
            enforcePocketChirpCaller();
            return callString("selected_ble_driver_facts_json");
        }

        @Override public String autoProbe(IPocketChirpTransport transport, String transportKind) {
            enforcePocketChirpCaller();
            return callString("radio_auto_probe_json", proxy(transport), transportKind);
        }

        @Override public String downloadRadioOnce(IPocketChirpTransport transport, int attempt,
                                                  String transportKind) {
            enforcePocketChirpCaller();
            return callString("download_selected_editor_once_result_json",
                    proxy(transport), attempt, transportKind);
        }

        @Override public ParcelFileDescriptor backupRadioOnce(IPocketChirpTransport transport) {
            enforcePocketChirpCaller();
            return pipeForBytes(callBytes("backup_connected_radio_once_bytes", proxy(transport)));
        }

        @Override public String writeRadioOnce(IPocketChirpTransport transport,
                                               ParcelFileDescriptor image,
                                               String transportContextJson) {
            enforcePocketChirpCaller();
            return callString("controlled_write_current_once_bytes", proxy(transport),
                    readAll(image, MAX_IMAGE_BYTES), transportContextJson);
        }
    };

    @Override public IBinder onBind(Intent intent) {
        return binder;
    }

    private PocketChirpBinderTransportProxy proxy(IPocketChirpTransport transport) {
        return new PocketChirpBinderTransportProxy(transport);
    }

    private PyObject bridge() {
        return Python.getInstance().getModule("bridge");
    }

    private String callString(String name, Object... args) {
        try {
            return bridge().callAttr(name, args).toString();
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException(name + " failed: " + e, e);
        }
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
                if (total > maxBytes) {
                    throw new IllegalArgumentException("Input exceeds engine size limit");
                }
                out.write(buffer, 0, n);
            }
            return out.toByteArray();
        } catch (Exception e) {
            throw new IllegalStateException(
                    "Could not read engine input stream: " + e.getMessage(), e);
        }
    }

    /**
     * Return materialized image bytes through a synchronous file-backed PFD.
     *
     * Unlike pipeForBytes(), this does not depend on an asynchronous writer
     * thread after the Binder method returns, so a writer failure cannot be
     * mistaken by the app for a legitimate zero-byte materialized image.
     */
    private ParcelFileDescriptor fileForBytes(byte[] bytes) {
        byte[] copy = bytes == null ? new byte[0] : bytes.clone();
        if (copy.length == 0) {
            throw new IllegalStateException(
                    "Cannot return an empty materialized image");
        }

        File temp = null;
        try {
            temp = File.createTempFile(
                    "pc-engine-materialized-", ".img", getCacheDir());
            try (FileOutputStream out = new FileOutputStream(temp)) {
                out.write(copy);
                out.flush();
                out.getFD().sync();
            }

            ParcelFileDescriptor pfd = ParcelFileDescriptor.open(
                    temp, ParcelFileDescriptor.MODE_READ_ONLY);

            // Android/Linux keeps the opened descriptor valid after unlink.
            // If unlink fails, leaving one cache file is preferable to losing
            // the materialized image; Android may reclaim cache files later.
            //noinspection ResultOfMethodCallIgnored
            temp.delete();
            return pfd;
        } catch (Exception e) {
            if (temp != null) {
                //noinspection ResultOfMethodCallIgnored
                temp.delete();
            }
            throw new IllegalStateException(
                    "Could not create materialized-image output descriptor", e);
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
                } catch (Exception ignored) {
                }
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
            for (byte b : hash) {
                out.append(String.format(Locale.US, "%02x", b & 0xff));
            }
            return out.toString();
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
