package com.wg5eek.pocketchirp.engine;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.Space;
import android.widget.TextView;

/**
 * Minimal launcher information screen for the PocketCHIRP CHIRP Engine.
 *
 * The Engine is a companion/service APK and is not a standalone application.
 * This Activity intentionally does not start, stop, bind, or otherwise alter
 * PocketChirpEngineService. It only explains the companion relationship and
 * lets the user close the launcher task.
 */
public final class EngineInfoActivity extends Activity {

    private int dp(float value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(28), dp(48), dp(28), dp(32));
        root.setBackgroundColor(Color.WHITE);

        ImageView icon = new ImageView(this);
        icon.setImageResource(R.mipmap.ic_launcher);
        icon.setContentDescription("PocketCHIRP CHIRP Engine");
        LinearLayout.LayoutParams iconParams = new LinearLayout.LayoutParams(dp(96), dp(96));
        iconParams.bottomMargin = dp(24);
        root.addView(icon, iconParams);

        TextView title = new TextView(this);
        title.setText("PocketCHIRP CHIRP Engine");
        title.setTextColor(Color.rgb(24, 24, 24));
        title.setTextSize(24);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        root.addView(title, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        TextView message = new TextView(this);
        message.setText("This companion engine requires the PocketCHIRP main app.\n\n"
                + "It provides CHIRP radio-driver support to PocketCHIRP and does not operate as a standalone app.");
        message.setTextColor(Color.rgb(72, 72, 72));
        message.setTextSize(17);
        message.setGravity(Gravity.CENTER);
        message.setLineSpacing(0f, 1.15f);
        LinearLayout.LayoutParams messageParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        messageParams.topMargin = dp(18);
        root.addView(message, messageParams);

        Space spacer = new Space(this);
        root.addView(spacer, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        Button close = new Button(this);
        close.setText("Close");
        close.setTextSize(17);
        close.setAllCaps(false);
        close.setOnClickListener(v -> finishAndRemoveTask());
        LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(52));
        buttonParams.topMargin = dp(28);
        root.addView(close, buttonParams);

        setContentView(root);
    }

    @Override
    public void onBackPressed() {
        finishAndRemoveTask();
    }
}
