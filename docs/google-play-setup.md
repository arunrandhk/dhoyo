# Google Play and Play Games setup

This repository contains an Android application and a separate Google Play Games Services (PGS) connection. A test APK has been built and checked as described below. It does not create a Play Console listing, buy an organisation account, publish a release or invent Google project IDs. Production setup belongs to the organisation that will own the application.

Google Play distributes Android apps. PGS supplies gaming identity, achievements and leaderboards for Android games; it does not replace Dhoyo's activated accounts or required profile form. A sports booking/tournament management website is not automatically a game because it has badges. Assess the actual product against Google's current game requirements before enabling PGS. This is an integration limitation inferred from Google's game-specific documentation. Dhoyo's own rankings and badges remain available independently. [PGS overview](https://developer.android.com/games/pgs/overview), [Android game server support](https://developer.android.com/games/pgs/android/server-access).

## Organisation ownership and publication

1. The authorised organisation representative creates or uses an **Organisation** Play Console developer account. Google currently charges a US$25 one-time registration fee; the representative reviews the Developer Distribution Agreement and completes Google's identity checks. [Developer registration](https://support.google.com/googleplay/android-developer/answer/6112435?hl=en).
2. Prepare the organisation's D-U-N-S number, legal identity/address, organisation website and working contact email/phone details. Complete the verification requested for the actual organisation and country. [Organisation account requirements](https://support.google.com/googleplay/android-developer/answer/13628312?hl=en).
3. Choose the permanent Android package name before the first upload. In Play Console, create the app with its real app/game classification and complete the store listing, screenshots, support details and content declarations. The owner reviews and accepts any console agreements. Use an internal test release before requesting a production review. [Create and set up an app](https://support.google.com/googleplay/android-developer/answer/9859152?hl=en).
4. Deploy the current website/backend changes to the organisation's public **HTTPS** origin, currently `https://byte-ring-demo.onrender.com`. A phone cannot reach this development container's `localhost`. Configure the Android application's website origin to that deployment. Retain the existing activation, phone/profile completion and account protections. An older hosted deployment must be updated before it can serve the new PGS and onboarding endpoints.
5. Configure an organisation-controlled upload keystore, keep its passwords outside source control, and sign the release AAB. With Play App Signing, Google uses the app signing certificate for distributed APKs; its SHA-1 is different from the upload certificate's SHA-1. [App signing](https://developer.android.com/studio/publish/app-signing).

Prepare an accurate privacy policy, Data safety declarations and account-deletion experience before submission. Apps offering account creation must meet Google's deletion requirements, including an accessible external deletion-request resource. This integration does not itself add a complete account-deletion workflow. [Account deletion requirements](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en).

Paid tournament participation combined with cash or valuable prizes requires a specific policy review of the product and countries before distribution. Do not assume a general sports listing or PGS integration authorises those features. [Real-money games and contests policy](https://support.google.com/googleplay/android-developer/answer/9877032?hl=en).

## Google Play Games project

For an eligible game, create a PGS game project under the organisation's Play Console and link its Google Cloud project. Configure its consent screen and add PGS testers or the relevant test release track. A Cloud OAuth client alone is insufficient: it must be linked as a credential to the PGS game. [PGS console setup](https://developer.android.com/games/pgs/console/setup).

Create these credentials for the same project:

| Credential | Configuration |
| --- | --- |
| Android OAuth client | Exact Android package name and SHA-1 of the certificate signing the installed build. |
| Additional Android test credential | Same package with the debug certificate SHA-1 when testing local debug builds. |
| Game server credential | A Web application OAuth client, linked as a **Game server** credential in PGS. Its client secret stays on the Flask server. |

For Play-distributed builds, copy the **app signing certificate** SHA-1 from Play Console. For local builds, print the relevant debug certificate using `keytool -list -v -keystore /path/to/debug.keystore`; do not paste keystore passwords into shell history. [Android credential setup](https://developer.android.com/games/pgs/console/setup).

The Android SDK requests a single-use server authorisation code for the game server's **Web client ID**. The backend exchanges that code and verifies the authenticated PGS player with Google before linking it to the signed-in Dhoyo account. A PGS player ID must never be trusted just because a phone submits it. [Server-side access](https://developer.android.com/games/pgs/android/server-access).

### Server settings

Provide these through private deployment settings, not checked-in files:

| Setting | Value |
| --- | --- |
| `PLAY_GAMES_WEB_CLIENT_ID` | The PGS-linked game server Web OAuth client ID. |
| `PLAY_GAMES_WEB_CLIENT_SECRET` | Its Web OAuth client secret; server-only. |
| `PLAY_GAMES_APPLICATION_ID` | The numeric PGS project/game application ID from Play Console, not the Android package name. |
| `PLAY_GAMES_LEADERBOARD_ID` | Optional published PGS leaderboard ID for the configured score integration. |
| `PLAY_GAMES_ACHIEVEMENTS_JSON` | Optional JSON mapping of supported Dhoyo badge keys to the achievement IDs created in this PGS game. |
| `ANDROID_PACKAGE_NAME` | Website configuration for the Android package; defaults to `com.dhoyo.app`. Keep it equal to the actual released package. |
| `PLAY_STORE_URL` | Optional real `https://play.google.com/store/apps/details?id=...` listing URL, added only after the owner has created that listing. |

These credentials serve PGS separately from regular website Google sign-in (`GOOGLE_CLIENT_ID` and its associated configuration). Android build configuration contains only public project/client/leaderboard identifiers; a client secret must never be bundled in the APK, AAB, JavaScript, resources or Gradle properties committed to the repository.

Define standard achievements and the intended leaderboard in Play Console before supplying IDs. Keep Dhoyo milestones mapped only to matching achievements, and publish PGS resources separately from the store release. The Google leaderboard's configured reset periods need not match Dhoyo's quarterly seasonal ranking rules. [PGS achievements](https://developer.android.com/games/pgs/android/achievements), [PGS leaderboards](https://developer.android.com/games/pgs/android/leaderboards).

The implemented server supports these optional **standard**, non-incremental achievement mapping keys: `first-team`, `first-tournament`, `five-tournaments` and `multi-sport`. Omit a key to leave that badge local to Dhoyo. For example, the following shows the mapping shape with deliberately invented placeholder IDs; replace each value with its actual Console resource ID before deployment:

```json
{
  "first-team": "PLACEHOLDER_GOOGLE_ID_FIRST_TEAM",
  "first-tournament": "PLACEHOLDER_GOOGLE_ID_FIRST_TOURNAMENT",
  "five-tournaments": "PLACEHOLDER_GOOGLE_ID_FIVE_TOURNAMENTS",
  "multi-sport": "PLACEHOLDER_GOOGLE_ID_MULTI_SPORT"
}
```

For `PLAY_GAMES_LEADERBOARD_ID`, create a **numeric**, **LargerIsBetter** leaderboard. The backend submits the authenticated player's **lifetime completed-tournament count**, with one completed tournament adding one to the count. It does not submit Dhoyo points, wins or the quarterly ranking score. Dhoyo's quarterly, UTC seasonal tables remain separate.

Google achievement unlocks persist; this integration does not revoke a previously unlocked Google achievement. Dhoyo can remove its local `first-team` badge after a withdrawal, while a previously unlocked Google achievement remains earned. Prefer completion-based mappings if that difference is unsuitable for the organisation's game rules.

Linking can operate with the three core settings even when no achievement/leaderboard IDs exist. An invalid achievement mapping disables configuration rather than silently using an unintended ID. Players request linking or a fresh sync explicitly from the application. The backend does not retain refresh tokens for ongoing background sync. Partial external updates are reported with `syncComplete: false`, allowing the user to retry with fresh authorisation. Do not claim a live PGS connection until a real tester has completed that flow against the deployed backend.

Start the connection with **Connect & sync with Dhoyo** in the Android app. The
website approves that request and displays its status. Its **Check connection
status** button reloads status; it does not submit achievements. Browser approval
links expire after five minutes. The website removes an expired link and requires
another explicit approval before offering a replacement.

The backend uses a 60-second total budget for Google calls, each limited to at
most 10 seconds and the remaining budget. Android allows 75 seconds to read the
result; Gunicorn allows 90 seconds for the request. A deadline stops further
updates and reports successful partial work accurately. Retrying requires fresh
approval and Google authorisation; an interrupted request may already have
updated Google. The timeout fixes alone do not configure Google credentials or
deploy local changes.

## Deploy the backend

For the existing Render service at `https://byte-ring-demo.onrender.com`:

1. Deploy a reviewed source revision containing the new Flask modules, static scripts and Docker build inputs. A locally running app does not update the hosted service.
2. Select the service in Render Dashboard, open **Environment**, and add the uppercase settings above. Store the Web client secret privately. Keep the existing database, persistent `AUTH_JWT_SECRET`, HTTPS/cookie and configured activation-mail settings. Set `PASSWORD_RESET_BASE_URL` to the deployed website URL used by the account activation/recovery flow, such as `https://byte-ring-demo.onrender.com/sportspace`.
3. Choose the dashboard action that rebuilds and deploys the source together with its settings. **Save only** does not apply changed settings until a later deployment. [Render environment settings](https://render.com/docs/configure-environment-variables).
4. Check `/health`, then `/api/play-games/config`. The latter should return a configuration object rather than 404, with `playGamesEnabled: true` only when the core credentials and optional mappings are valid. It exposes no secret. Sign in normally to test `/ring#google-play`, required onboarding and actual native connection/sync.
5. Leave `PLAY_STORE_URL` unset until the real listing exists. The website then shows the app as unpublished instead of generating an install link.

The existing EC2 deployment script accepts the same settings from the deployment's private Secrets Manager JSON using these lowercase fields:

| Environment variable | Secrets Manager JSON field |
| --- | --- |
| `PLAY_GAMES_APPLICATION_ID` | `play_games_application_id` |
| `PLAY_GAMES_WEB_CLIENT_ID` | `play_games_web_client_id` |
| `PLAY_GAMES_WEB_CLIENT_SECRET` | `play_games_web_client_secret` |
| `PLAY_GAMES_LEADERBOARD_ID` | `play_games_leaderboard_id` |
| `PLAY_GAMES_ACHIEVEMENTS_JSON` | `play_games_achievements_json` |
| `ANDROID_PACKAGE_NAME` | `android_package_name` |
| `PLAY_STORE_URL` | `play_store_url` |
| `GOOGLE_CLIENT_ID` | `google_client_id` |

`play_games_achievements_json` must be a JSON **string containing the mapping**, rather than a nested object, because `scripts/deploy_ec2.sh` writes optional settings into Docker's literal environment file. Existing required database fields and `auth_jwt_secret` remain required. Adding optional values does not deploy an image by itself; run the organisation's existing reviewed deployment workflow for its intended service.

## Local Android build tools

The development tools for this session live only in `/tmp/dhoyo-android-tools`, outside the application source. They are temporary and do not become part of the deployed website. The Android project pins Gradle 8.13, Android Gradle Plugin 8.13.2, JDK 17, Android platform 36 and SDK Build Tools 35.0.0.

Google SDK command-line tools and Gradle archives are verified against their published SHA-256 checksums. JDK archives are verified against the checksum returned by the official Eclipse Adoptium release metadata. [Google SDK tools downloads](https://developer.android.com/studio), [Gradle checksums](https://gradle.org/release-checksums/), [Eclipse Temurin](https://adoptium.net/temurin/releases/).

Review Android SDK licences interactively before installing licensed packages:

```sh
export JAVA_HOME=/tmp/dhoyo-android-tools/jdk17
export ANDROID_HOME=/tmp/dhoyo-android-tools/sdk
export ANDROID_USER_HOME=/tmp/dhoyo-android-tools/android-user-home
export GRADLE_USER_HOME=/tmp/dhoyo-android-tools/gradle-user-home
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_HOME" --licenses
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_HOME" 'platforms;android-36' 'build-tools;35.0.0' 'platform-tools'
```

The first command displays Google's agreements for the operator to review. In this session, the initial install stopped at the licence prompt. The owner then explicitly authorised **“Accept the SDK terms and build the test app”**. Only the reviewed Android SDK License Agreement was accepted for the three targeted packages above; unrelated SDK agreements were not accepted. A fresh environment still needs its operator's licence review. [SDK manager and licence acceptance](https://developer.android.com/tools/sdkmanager), [Android SDK terms](https://developer.android.com/studio/terms).

The targeted SDK installation completed successfully: platform `android-36` revision 2, Build Tools 35.0.0 and Platform Tools 37.0.1 are installed under the temporary SDK directory. Download checksum records are in `/tmp/dhoyo-android-tools/verified-downloads.json`; the targeted install log is `/tmp/dhoyo-android-tools/sdk-install-authorized.log`.

From the repository's Android directory, use the checked-in Gradle wrapper to run assembly, unit tests, lint and release bundle generation. See `android/README.md` for the exact public configuration properties and signing environment expected by the final Android project. A debug APK is for testing, and an unsigned release bundle cannot be uploaded as a production release. Device testing and live PGS connection still require a correctly configured project, compatible Android device/Google Play services, authorised tester and valid credentials.

## Verified test build

On 15 October 2026, the official checked-in wrapper completed these tasks successfully with the installed tools:

```sh
cd android
./gradlew --no-daemon :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

The build executed 50 tasks, passed all 4 JUnit tests, and completed lint with **0 errors and 3 warnings**. The warnings concern the pinned Gradle version, Android 12 data-extraction rules and a monochrome round launcher icon. The unit tests cover PKCE and callback/origin validation. This was a compiled test build, not a device instrumentation test or a live Google project connection.

The debug APK is available at `/tmp/dhoyo-android-artifacts/app-debug.apk` (3,289,275 bytes). Its SHA-256 is:

```text
b4a66c7c599445d5493f817045fc07782c2d279364e028f9107f6195def41f94
```

Build output, the JUnit report and the lint HTML report are in the same temporary artifacts directory. The APK has a valid Android debug signature. The merged and packaged manifests were inspected to confirm the PGS library's automatic initialization provider was removed; the application's guarded initialization keeps PGS disabled while game IDs are blank.

The test build opens `https://byte-ring-demo.onrender.com` for the website. Deploy the new backend there and supply the organisation's real PGS configuration before testing the complete native/browser/server linking flow. No Play Console publication or production-signed release bundle was performed.
