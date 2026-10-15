package com.dhoyo.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import androidx.browser.customtabs.CustomTabsIntent;

import com.google.android.gms.games.GamesSignInClient;
import com.google.android.gms.games.PlayGames;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import javax.net.ssl.HttpsURLConnection;

/** Native Play Games entry point. All website authentication stays in the browser. */
public final class MainActivity extends Activity {
    private static final int GOOGLE_UI_REQUEST = 7001;
    private static final long PENDING_LIFETIME_MS = 10 * 60 * 1000;
    private static final int INK = Color.rgb(239, 246, 235);
    private static final int MUTED = Color.rgb(171, 193, 185);
    private static final int ACCENT = Color.rgb(212, 250, 98);

    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private String origin;
    private String pendingVerifier;
    private long pendingStartedAt;
    private boolean busy;
    private TextView status;
    private Button signIn;
    private Button achievements;
    private Button leaderboard;
    private Button sync;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        origin = ConnectionSecurity.origin(BuildConfig.APP_BASE_URL);
        if (savedInstanceState != null) {
            String saved = savedInstanceState.getString("pendingVerifier");
            long started = savedInstanceState.getLong("pendingStartedAt", 0);
            if (ConnectionSecurity.validVerifier(saved) && fresh(started)) {
                pendingVerifier = saved;
                pendingStartedAt = started;
            }
        }
        createContent();
        if (savedInstanceState != null && savedInstanceState.getBoolean("operationInProgress")) {
            showStatus("The previous connection was interrupted. Check Dhoyo in your browser or start a new sync.");
        } else if (pendingVerifier != null) {
            showStatus("Finish confirming your Dhoyo account in the browser, then return here.");
        } else if (gamesReady()) {
            showStatus("Sign in to Play Games to view your official achievements and leaderboard.");
        }
        consumeIncomingIntent(getIntent());
    }

    private void createContent() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(24), dp(28), dp(24), dp(32));
        scroll.addView(content, new ScrollView.LayoutParams(-1, -2));
        scroll.setBackgroundColor(Color.rgb(12, 23, 29));
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            int top;
            int bottom;
            int left;
            int right;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                top = bars.top;
                bottom = bars.bottom;
                left = bars.left;
                right = bars.right;
            } else {
                top = insets.getSystemWindowInsetTop();
                bottom = insets.getSystemWindowInsetBottom();
                left = insets.getSystemWindowInsetLeft();
                right = insets.getSystemWindowInsetRight();
            }
            view.setPadding(left, top, right, bottom);
            return insets;
        });
        addText(content, "DHOYO", 13, ACCENT, true);
        addText(content, "Your people.\nYour game.", 36, INK, true);
        addText(content, "Find your team, enter tournaments and keep track of your next game.", 16, MUTED, false);

        Button website = addButton(content, "Open Dhoyo", true);
        website.setEnabled(origin != null);
        website.setOnClickListener(view -> openBrowser(origin + "/ring#ring"));
        if (origin == null) {
            addText(content, "Dhoyo’s website is not connected in this build yet. Ask your organisation for an updated app.", 14, MUTED, false);
        } else {
            addText(content, "Website: " + origin + "\nYour browser handles Dhoyo sign-in, activation and phone details.", 13, MUTED, false);
        }

        addText(content, "Google Play Games", 24, INK, true);
        addText(content, "Your Play Games profile and Dhoyo account are separate. Connecting them requires your confirmation in Dhoyo.", 14, MUTED, false);
        if (BuildConfig.PLAY_GAMES_APPLICATION_ID.isEmpty()) {
            addText(content, "Play Games is not available in this build yet. You can still use Dhoyo in your browser.", 14, MUTED, false);
        } else if (!gamesReady()) {
            addText(content, "Play Games could not start on this device. You can still use Dhoyo in your browser.", 14, MUTED, false);
        }

        signIn = addButton(content, "Sign in to Play Games", false);
        signIn.setOnClickListener(view -> signIntoGames());
        achievements = addButton(content, "View official achievements", false);
        achievements.setOnClickListener(view -> openAchievements());
        leaderboard = addButton(content, "View official leaderboard", false);
        leaderboard.setOnClickListener(view -> openLeaderboard());
        if (BuildConfig.PLAY_GAMES_LEADERBOARD_ID.isEmpty()) {
            addText(content, "The official Play Games leaderboard is not available in this build yet.", 13, MUTED, false);
        }
        sync = addButton(content, "Connect & sync with Dhoyo", true);
        sync.setOnClickListener(view -> startConnection());
        if (BuildConfig.PLAY_GAMES_WEB_CLIENT_ID.isEmpty()) {
            addText(content, "Account connection is not available in this build yet. You can still use Dhoyo in your browser.", 13, MUTED, false);
        }

        status = addText(content, "Open Dhoyo to use tournaments, achievements and reminders on the website.", 14, INK, false);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        status.setPadding(dp(16), dp(16), dp(16), dp(16));
        GradientDrawable box = new GradientDrawable();
        box.setColor(Color.rgb(25, 45, 45));
        box.setCornerRadius(dp(12));
        box.setStroke(dp(1), Color.rgb(62, 89, 78));
        status.setBackground(box);
        setContentView(scroll);
        updateButtons();
    }

    private TextView addText(LinearLayout parent, String value, int size, int color, boolean bold) {
        TextView text = new TextView(this);
        text.setText(value);
        text.setTextSize(size);
        text.setTextColor(color);
        text.setLineSpacing(dp(3), 1);
        if (bold) text.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.bottomMargin = dp(18);
        parent.addView(text, layout);
        return text;
    }

    private Button addButton(LinearLayout parent, String label, boolean primary) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextColor(primary ? Color.rgb(20, 32, 14) : INK);
        button.setTextSize(15);
        button.setMinHeight(dp(52));
        button.setPadding(dp(15), dp(12), dp(15), dp(12));
        GradientDrawable background = new GradientDrawable();
        background.setColor(primary ? ACCENT : Color.rgb(29, 49, 51));
        background.setCornerRadius(dp(10));
        if (!primary) background.setStroke(dp(1), Color.rgb(72, 99, 86));
        button.setBackground(background);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.bottomMargin = dp(12);
        parent.addView(button, layout);
        return button;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private boolean alive() {
        return !isFinishing() && !isDestroyed();
    }

    private boolean gamesReady() {
        return ((DhoyoApplication) getApplication()).isPlayGamesInitialized();
    }

    private void updateButtons() {
        boolean available = gamesReady() && !busy;
        signIn.setEnabled(available);
        achievements.setEnabled(available);
        leaderboard.setEnabled(available && !BuildConfig.PLAY_GAMES_LEADERBOARD_ID.isEmpty());
        sync.setEnabled(available && origin != null && !BuildConfig.PLAY_GAMES_WEB_CLIENT_ID.isEmpty());
        sync.setText(pendingVerifier == null ? "Connect & sync with Dhoyo" : "Start a new connection & sync");
        for (Button button : new Button[]{signIn, achievements, leaderboard, sync}) {
            button.setAlpha(button.isEnabled() ? 1f : 0.45f);
        }
    }

    private void setBusy(boolean value) {
        busy = value;
        if (alive()) updateButtons();
    }

    private void showStatus(String message) {
        if (alive()) status.setText(message);
    }

    private void signIntoGames() {
        if (busy || !gamesReady()) return;
        setBusy(true);
        showStatus("Opening Google Play Games sign-in…");
        PlayGames.getGamesSignInClient(this).signIn().addOnCompleteListener(task -> {
            if (!alive()) return;
            setBusy(false);
            showStatus(task.isSuccessful() && task.getResult().isAuthenticated()
                    ? "Signed in to Play Games. Your Dhoyo account has not been linked by this sign-in."
                    : "Play Games sign-in did not complete. Check your connection and try again, or use Dhoyo in your browser.");
        });
    }

    private void openAchievements() {
        if (busy || !gamesReady()) return;
        setBusy(true);
        PlayGames.getAchievementsClient(this).getAchievementsIntent()
                .addOnSuccessListener(intent -> launchGoogleUi(intent))
                .addOnFailureListener(error -> googleUiFailed());
    }

    private void openLeaderboard() {
        if (busy || !gamesReady() || BuildConfig.PLAY_GAMES_LEADERBOARD_ID.isEmpty()) return;
        setBusy(true);
        PlayGames.getLeaderboardsClient(this).getLeaderboardIntent(BuildConfig.PLAY_GAMES_LEADERBOARD_ID)
                .addOnSuccessListener(intent -> launchGoogleUi(intent))
                .addOnFailureListener(error -> googleUiFailed());
    }

    private void launchGoogleUi(Intent intent) {
        if (!alive()) return;
        setBusy(false);
        try {
            startActivityForResult(intent, GOOGLE_UI_REQUEST);
        } catch (ActivityNotFoundException unavailable) {
            googleUiFailed();
        }
    }

    private void googleUiFailed() {
        if (!alive()) return;
        setBusy(false);
        showStatus("Google Play Games could not open this screen. Sign in or try again later.");
    }

    private void startConnection() {
        if (busy || !gamesReady() || origin == null || BuildConfig.PLAY_GAMES_WEB_CLIENT_ID.isEmpty()) return;
        pendingVerifier = ConnectionSecurity.newVerifier();
        pendingStartedAt = SystemClock.elapsedRealtime();
        String challenge = ConnectionSecurity.challenge(pendingVerifier);
        showStatus("Sign in to Dhoyo in the browser and confirm which account to connect. Return to this app when prompted. This connection expires in 10 minutes.");
        updateButtons();
        if (!openBrowser(origin + "/ring#google-play/connect/" + challenge)) {
            pendingVerifier = null;
            pendingStartedAt = 0;
            updateButtons();
        }
    }

    private boolean openBrowser(String destination) {
        if (origin == null || !destination.startsWith(origin + "/")) {
            showStatus("Dhoyo’s website is not available in this build yet. Ask your organisation for an updated app.");
            return false;
        }
        try {
            CustomTabsIntent browser = new CustomTabsIntent.Builder()
                    .setShowTitle(true).setColorScheme(CustomTabsIntent.COLOR_SCHEME_DARK).build();
            browser.launchUrl(this, Uri.parse(destination));
            return true;
        } catch (ActivityNotFoundException unavailable) {
            showStatus("Install or enable a browser to open Dhoyo and finish signing in.");
            return false;
        }
    }

    @Override
    protected void onNewIntent(Intent incoming) {
        super.onNewIntent(incoming);
        consumeIncomingIntent(incoming);
    }

    private boolean fresh(long started) {
        long elapsed = SystemClock.elapsedRealtime() - started;
        return started > 0 && elapsed >= 0 && elapsed <= PENDING_LIFETIME_MS;
    }

    private void consumeIncomingIntent(Intent incoming) {
        // Do not retain a server ticket in the Activity's launch intent or state.
        setIntent(new Intent(this, MainActivity.class).setAction(Intent.ACTION_MAIN));
        if (incoming == null || !Intent.ACTION_VIEW.equals(incoming.getAction())) return;
        String ticket = ConnectionSecurity.callbackTicket(incoming.getDataString());
        incoming.setData(null);
        if (ticket == null) {
            showStatus("This connection link is invalid. Start a new connection from this app.");
            return;
        }
        if (busy) return;
        if (origin == null || !gamesReady() || BuildConfig.PLAY_GAMES_WEB_CLIENT_ID.isEmpty()) {
            showStatus("Play Games connection is not available in this build yet. You can still use Dhoyo in your browser.");
            return;
        }
        if (!ConnectionSecurity.validVerifier(pendingVerifier) || !fresh(pendingStartedAt)) {
            pendingVerifier = null;
            pendingStartedAt = 0;
            updateButtons();
            showStatus("Start a new connection from this app. The previous request expired or the app was restarted.");
            return;
        }
        final String verifier = pendingVerifier;
        pendingVerifier = null;
        pendingStartedAt = 0;
        setBusy(true);
        showStatus("Verifying your Play Games account and syncing with the Dhoyo account you confirmed…");
        GamesSignInClient games = PlayGames.getGamesSignInClient(this);
        games.isAuthenticated().addOnCompleteListener(task -> {
            if (!alive()) return;
            if (task.isSuccessful() && task.getResult().isAuthenticated()) {
                requestServerCode(ticket, verifier);
            } else {
                games.signIn().addOnCompleteListener(signedIn -> {
                    if (!alive()) return;
                    if (signedIn.isSuccessful() && signedIn.getResult().isAuthenticated()) {
                        requestServerCode(ticket, verifier);
                    } else {
                        setBusy(false);
                        showStatus("Play Games sign-in did not complete. Start a new connection when you are ready.");
                    }
                });
            }
        });
    }

    private void requestServerCode(String ticket, String verifier) {
        PlayGames.getGamesSignInClient(this)
                .requestServerSideAccess(BuildConfig.PLAY_GAMES_WEB_CLIENT_ID, false)
                .addOnCompleteListener(task -> {
                    if (!alive()) return;
                    String code = task.isSuccessful() ? task.getResult() : null;
                    if (code == null || code.isEmpty()) {
                        setBusy(false);
                        showStatus("Google could not authorize this connection. Start a new connection and try again, or contact your organisation.");
                        return;
                    }
                    network.execute(() -> {
                        String result;
                        try {
                            result = connect(ticket, verifier, code);
                        } catch (IOException | JSONException error) {
                            result = "The connection could not be confirmed. Check your connection and Dhoyo account, then start a new sync. A request may already have reached the server.";
                        }
                        final String message = result;
                        runOnUiThread(() -> {
                            if (!alive()) return;
                            setBusy(false);
                            showStatus(message);
                        });
                    });
                });
    }

    private String connect(String ticket, String verifier, String code) throws IOException, JSONException {
        URL endpoint = new URL(origin + "/api/play-games/connect");
        HttpsURLConnection connection = (HttpsURLConnection) endpoint.openConnection();
        try {
            connection.setRequestMethod("POST");
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(75000);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("X-Dhoyo-Request", "1");
            connection.setDoOutput(true);
            JSONObject payload = new JSONObject();
            payload.put("ticket", ticket);
            payload.put("verifier", verifier);
            payload.put("serverAuthCode", code);
            byte[] encoded = payload.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(encoded.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(encoded);
            }
            int statusCode = connection.getResponseCode();
            if (statusCode >= 300 && statusCode < 400) {
                return "Dhoyo could not finish this connection. Please use the latest app from your organisation and start a new sync.";
            }
            String type = connection.getContentType();
            if (type == null || !type.toLowerCase(java.util.Locale.ROOT).startsWith("application/json")) {
                return "Dhoyo could not confirm this connection. Try again later or contact your organisation.";
            }
            InputStream stream = statusCode >= 400 ? connection.getErrorStream() : connection.getInputStream();
            if (stream == null) throw new IOException("Missing response");
            JSONObject result;
            try (InputStream input = stream; ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[2048];
                int length;
                while ((length = input.read(buffer)) != -1) {
                    if (bytes.size() + length > 16384) throw new IOException("Response too large");
                    bytes.write(buffer, 0, length);
                }
                result = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            }
            if (statusCode < 200 || statusCode >= 300 || !result.optBoolean("linked", false)) {
                return safeMessage(result.optString("error", ""),
                        "Dhoyo could not confirm this connection. Check your account and start a new sync, or contact your organisation.");
            }
            String message = safeMessage(result.optString("message", ""),
                    result.optBoolean("syncComplete", false)
                            ? "Your Play Games account is connected and sync completed."
                            : "Your Play Games account is connected. Some progress could not be synced yet; start a new sync to retry.");
            int achievementCount = result.optInt("syncedAchievements", -1);
            if (achievementCount >= 0) message += "\nAchievements synced: " + achievementCount + ".";
            Object score = result.opt("submittedScore");
            if (score instanceof Number && ((Number) score).longValue() >= 0) {
                message += "\nLeaderboard score submitted: " + ((Number) score).longValue() + ".";
            }
            return message;
        } finally {
            connection.disconnect();
        }
    }

    private static String safeMessage(String supplied, String fallback) {
        if (supplied == null || supplied.trim().isEmpty() || supplied.length() > 500) return fallback;
        for (int index = 0; index < supplied.length(); index++) {
            if (Character.isISOControl(supplied.charAt(index))) return fallback;
        }
        return supplied;
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        if (ConnectionSecurity.validVerifier(pendingVerifier) && fresh(pendingStartedAt)) {
            outState.putString("pendingVerifier", pendingVerifier);
            outState.putLong("pendingStartedAt", pendingStartedAt);
        }
        outState.putBoolean("operationInProgress", busy);
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onDestroy() {
        network.shutdownNow();
        super.onDestroy();
    }
}
