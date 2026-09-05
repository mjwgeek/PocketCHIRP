package com.wg5eek.pocketchirp.engine;

import android.app.Activity;
import android.os.Bundle;

/**
 * Launcher stub for the PocketCHIRP CHIRP Engine.
 *
 * The engine is a companion/service APK and has no standalone UI. If a user
 * launches its icon directly, close the launcher task immediately and quietly.
 * This does not start, stop, bind, or otherwise alter PocketChirpEngineService.
 */
public final class EngineInfoActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Remove the launcher task completely so there is no blank Activity
        // left behind in Recents and no visible error/UI for direct launches.
        finishAndRemoveTask();
    }
}
