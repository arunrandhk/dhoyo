package com.dhoyo.app;

import android.app.Application;
import com.google.android.gms.games.PlayGamesSdk;

public final class DhoyoApplication extends Application {
    private boolean playGamesInitialized;

    @Override
    public void onCreate() {
        super.onCreate();
        if (!BuildConfig.PLAY_GAMES_APPLICATION_ID.matches("[1-9][0-9]{0,29}")) return;
        try {
            PlayGamesSdk.initialize(this);
            playGamesInitialized = true;
        } catch (RuntimeException unavailable) {
            // Configuration or Google Play services may be unavailable. Keep the
            // website usable without displaying, persisting, or logging secrets.
            playGamesInitialized = false;
        }
    }

    boolean isPlayGamesInitialized() {
        return playGamesInitialized;
    }
}
