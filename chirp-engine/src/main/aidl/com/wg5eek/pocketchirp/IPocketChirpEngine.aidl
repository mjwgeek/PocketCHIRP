package com.wg5eek.pocketchirp;

import android.os.ParcelFileDescriptor;
import com.wg5eek.pocketchirp.IPocketChirpTransport;

/** Versioned cross-APK contract between PocketCHIRP and the GPL CHIRP engine. */
interface IPocketChirpEngine {
    int getPocketChirpApiVersion();
    String requestJson(String requestJson);

    /**
     * Stream a potentially large neutral JSON response through a file descriptor.
     * This avoids Android Binder transaction-size limits for radio documents,
     * large previews, and other bulk JSON while preserving requestJson() for
     * small control messages.
     */
    ParcelFileDescriptor requestJsonStream(String requestJson);

    ParcelFileDescriptor getWorkingImage();
    /** Load an image and stream the resulting radio document back to the app. */
    ParcelFileDescriptor loadImage(in ParcelFileDescriptor image);
    /** Stream potentially large image-conversion previews. */
    ParcelFileDescriptor previewImageConversion(in ParcelFileDescriptor image);
    String validateImage(in ParcelFileDescriptor image);
    String identifyImage(in ParcelFileDescriptor image);
    String imageCompatibility(in ParcelFileDescriptor image);

    /**
     * Apply PocketCHIRP-owned local editor mutations to a base image and stream
     * the resulting concrete CHIRP image back. No radio hardware is touched.
     */
    ParcelFileDescriptor materializeEditorEdits(in ParcelFileDescriptor baseImage,
                                                in ParcelFileDescriptor editBundle);

    String registerCustomDriver(in ParcelFileDescriptor source,
                                String filename,
                                boolean selectLoaded,
                                String sha256);

    /** Neutral facts derived only from the currently selected CHIRP class. */
    String getBleDriverFacts();

    /** One CHIRP protocol attempt. Android BLE retry/profile policy is app-side. */
    String autoProbe(in IPocketChirpTransport transport, String transportKind);
    String downloadRadioOnce(in IPocketChirpTransport transport, int attempt, String transportKind);
    ParcelFileDescriptor backupRadioOnce(in IPocketChirpTransport transport);
    String writeRadioOnce(in IPocketChirpTransport transport,
                          in ParcelFileDescriptor image,
                          String transportContextJson);
}
