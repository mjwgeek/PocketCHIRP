package com.wg5eek.pocketchirp;

import android.os.ParcelFileDescriptor;
import com.wg5eek.pocketchirp.IPocketChirpTransport;

/** Versioned cross-APK contract between PocketCHIRP and the GPL CHIRP engine. */
interface IPocketChirpEngine {
    int getPocketChirpApiVersion();
    String requestJson(String requestJson);

    ParcelFileDescriptor getWorkingImage();
    String loadImage(in ParcelFileDescriptor image);
    String previewImageConversion(in ParcelFileDescriptor image);
    String validateImage(in ParcelFileDescriptor image);
    String identifyImage(in ParcelFileDescriptor image);
    String imageCompatibility(in ParcelFileDescriptor image);

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
