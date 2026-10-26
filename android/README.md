# Dhoyo for Android

This Java Android app opens the organisation’s Dhoyo website in a browser Custom Tab and provides native Google Play Games Services v2 entry points. It uses package `com.dhoyo.app` and targets Android 16 / API 36, with Android 7 / API 24 as its minimum supported version.

The configured website is the public origin supplied by the owner: `https://byte-ring-demo.onrender.com`. The app does not include a WebView or JavaScript bridge. Website Google sign-in, required phone/profile details and email activation continue to run in the browser using the existing Dhoyo account service.

Google Play Games setup is **not complete** while the game IDs are blank. The native app honestly shows that setup is required and disables those actions. Dhoyo’s website badges, quarterly rankings and reminders work independently of Play Games. No Google account, store listing, published app or live game connection is created by this source project.

Dhoyo is currently a sports tournament and booking service. Play Games is designed for eligible games; adding a browser app and website badges does not establish game eligibility. The organisation must determine an appropriate game integration and complete Google’s actual game setup before enabling these APIs. See [organisation and Google setup](../docs/google-play-setup.md), [Play Games overview](https://developer.android.com/games/pgs/overview) and [game server support](https://developer.android.com/games/pgs/android/server-access).

## Public app configuration

Edit `gradle.properties` or provide these Gradle properties through your local Gradle configuration. `gradle.properties.example` shows the supported values. These are public configuration identifiers included in the APK; never put an OAuth client secret, password, session cookie, access token or signing password here.

| Property | Meaning | Default / when absent |
| --- | --- | --- |
| `APP_BASE_URL` | Trusted HTTPS website **origin**, without a path, query, fragment or URL credentials. | `https://byte-ring-demo.onrender.com`; explicitly blank disables browser and sync actions. |
| `PLAY_GAMES_APPLICATION_ID` | Numeric Games services project ID from the PGS configuration, not the Android package. | Blank; no Play Games SDK initialization or calls. |
| `PLAY_GAMES_WEB_CLIENT_ID` | Public OAuth **Web application** client ID linked as the PGS game-server credential. Must match the backend. | Blank; connection/sync is disabled. |
| `PLAY_GAMES_LEADERBOARD_ID` | PGS leaderboard resource ID configured for this game. | Blank; official leaderboard button is disabled. |

The organisation must configure the exact Android package and signing certificate SHA-1 in its Android OAuth credential, connect the game-server Web credential, publish/test the appropriate PGS resources and add authorised testers. Website Google sign-in credentials are a separate integration. Server secrets stay in private deployment settings. Follow the [setup guide](../docs/google-play-setup.md) for server environment names and achievement mapping.

This application always opens and sends connection requests to the build’s configured origin. Browser callbacks cannot supply another host. HTTP origins, embedded credentials, subpaths and redirects on the sensitive connection POST are rejected. A phone needs a reachable HTTPS deployment containing the current backend and browser integration; this development environment’s localhost is not a phone deployment.

## Build and inspect

Pinned tools and dependencies:

- Android Gradle Plugin **8.13.2**, Gradle **8.13**, JDK **17**.
- Android SDK platform **36** and SDK Build Tools **35.0.0**.
- `androidx.browser:browser:1.10.0` and `com.google.android.gms:play-services-games-v2:22.1.0`.

Open `android/` in Android Studio or use the checked-in wrapper with JDK 17. Install the required SDK packages with the SDK Manager after the operator has reviewed the SDK licences. Set `ANDROID_HOME` to your SDK directory, or put its path in ignored `local.properties` as `sdk.dir=/absolute/path/to/sdk`.

```sh
./gradlew --no-daemon :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
./gradlew --no-daemon :app:bundleRelease
```

The debug APK is `app/build/outputs/apk/debug/app-debug.apk`. The release bundle is `app/build/outputs/bundle/release/app-release.aab`. A release bundle is **unsigned** until the upload-signing environment below is supplied. Debug builds are for local testing and must not be uploaded as the organisation’s release.

For an Android device or emulator, install a debug APK using `adb install -r app/build/outputs/apk/debug/app-debug.apk`. The app can open the configured website without any PGS IDs. Real PGS sign-in additionally requires Google Play services and the correct game/tester/certificate configuration. Test the actual game connection on an authorised device before claiming it works against Google.

The unit tests cover the standard SHA-256 PKCE vector, random verifier format, exact callback validation and rejection of untrusted website origins. Android assembly and lint require the installed SDK; unit-test helpers can also be compiled directly with JDK 17 and JUnit 4. No test substitutes a fake Google sign-in success for real project setup.

Verified on 15 October 2026 after the owner accepted the SDK terms: `assembleDebug`, `testDebugUnitTest` and `lintDebug` completed successfully (50 tasks; 4 tests passed; lint reported 0 errors). Three nonblocking lint suggestions concern the pinned AGP version, optional data-extraction rules and a monochrome launcher icon. APK inspection confirmed package `com.dhoyo.app`, minimum API 24, target API 36 and a valid Android Debug signature. The SDK’s unconditional `PlayGamesInitProvider` is explicitly removed; its absence was checked in both merged and packaged manifests so blank game IDs cannot trigger that initializer.

The latest tested APK includes the 75-second sync read timeout and is copied outside source control to `/tmp/dhoyo-android-artifacts/app-debug.apk` (3,305,398 bytes), with SHA-256 `7355a225611c2fd75527983d2cabe62e5cbc3dd8f22ebdc281a69f3361b60b80`. The same directory contains its checksum file, build log, lint report and test results. It opens the supplied Dhoyo website; real Play Games sign-in and sync remain unavailable until the organisation supplies its project IDs and tests an authorised device/account.

The tool versions were checked against the official [AGP compatibility table](https://developer.android.com/build/releases/agp-8-13-0-release-notes), [Browser releases](https://developer.android.com/jetpack/androidx/releases/browser) and [Play services release notes](https://developers.google.com/android/guides/releases). API 36 meets the [new-app target API requirement effective August 2026](https://developer.android.com/google/play/requirements/target-sdk); recheck requirements before submitting a future release.

## Release signing

Configure an organisation-controlled upload keystore outside the repository and supply **all four** environment variables when building a signed release:

```text
DHOYO_UPLOAD_STORE_FILE=/absolute/path/to/organisation-upload.jks
DHOYO_UPLOAD_STORE_PASSWORD=<private environment value>
DHOYO_UPLOAD_KEY_ALIAS=<upload key alias>
DHOYO_UPLOAD_KEY_PASSWORD=<private environment value>
```

The release build uses these only for upload signing. Partial signing configuration fails the build; no signing configuration means an unsigned release bundle. The app never uses the debug key for release signing. Keystores, local SDK paths and build output are ignored by Git. Keep passwords in private environment/CI settings rather than shell history or committed property files. With Play App Signing, use the **app signing certificate** SHA-1 for Play-distributed OAuth credentials, which differs from the upload certificate. [Android app signing](https://developer.android.com/studio/publish/app-signing).

Building the bundle does not publish or upload it. Store submission, required privacy/account-deletion declarations and policy eligibility remain with the organisation.

## Explicit account connection and sync

Native **Sign in to Play Games** authenticates only the Play Games profile. It does not create, activate or link a Dhoyo account. Official achievements and leaderboard buttons open Google’s own interfaces; no client scores or unlocks are fabricated.

**Connect & sync with Dhoyo** performs this explicit flow:

1. The app generates a random 86-character URL-safe verifier and its 43-character SHA-256 challenge. It opens the configured website at `/ring#google-play/connect/<challenge>`.
2. The browser authenticates the Dhoyo account through the existing sign-in/onboarding process. The user reviews and confirms the account to connect. The website issues a short-lived, single-use server ticket bound to the challenge and opens `dhoyo://play-games?ticket=<ticket>`.
3. Android accepts only that exact scheme/authority, empty or root path, a single correctly shaped ticket query and no fragment. It requires its matching unexpired pending verifier. An unsolicited or expired callback asks the user to start again.
4. The app checks Play Games authentication and obtains a single-use server auth code with `requestServerSideAccess(webClientId, false)`. It POSTs `{ticket, verifier, serverAuthCode}` as JSON with `X-Dhoyo-Request: 1` to the configured origin’s `/api/play-games/connect` over HTTPS.
5. The backend independently verifies the Google player and links only the Dhoyo account approved in the browser. It derives achievements and score from authoritative server progress. Android displays the actual returned sync counts and partial/completed state. No access or refresh tokens are returned to the app or put in links.

The verifier and creation time live in Activity memory and `savedInstanceState` only; they are not written to preferences or files. Tickets and server auth codes stay in memory, are removed from the Activity’s held intent, are never saved in instance state and are not logged. `singleTask` routes a browser return to the existing Activity while Custom Tabs is above it. Configuration recreation can restore a pending verifier; if the app is restarted without recoverable pending state, it asks for a fresh flow. An interrupted network request reports an uncertain outcome instead of inventing a success or assuming the server received nothing.

The native connection request runs on a background executor with a 15-second connection timeout and a 75-second read timeout, bounded JSON responses, standard TLS certificate validation and redirects disabled. The read timeout allows the backend’s bounded 60-second Google verification/sync work to return a real completed or partial result. An interrupted or timed-out connection still reports an uncertain outcome because the server may have received the request. The app does not transmit browser cookies or website passwords. Linking and re-syncing require explicit user action and fresh Google authorisation; no background account linking or token storage is implemented.
