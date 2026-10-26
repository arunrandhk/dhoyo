# Accounts, connections and photo posts

The home screen and **Teams & players** navigation show all team and player cards.
Team cards open the roster, captain and match details. Player cards open their profile,
connections, photos and activity. Static assets use no-store caching to avoid stale UI.

## Accounts

Create an account on the sign-in screen using a name, email, password (10–128
characters), sport, city, region and country. Sign out from the top bar.
Each account has a separate player ID, profile, preferences, likes and saved posts.
Posts, stories and comments use the signed-in author's identity. Other accounts
cannot edit your profile. Historical demo players remain as sample content and
cannot be claimed through registration.

Choose **Home → Edit profile** or **Profile → Edit profile** to update your own
name, location, sport, bio and photo privacy. The form saves through the profile
API to the same database used by your account; reloading retrieves those saved
details. Profile edit controls appear before the connection map.

Regular player accounts discover published tournaments under **Tournaments**.
After registering a team, **Edit registration** updates its name before the
registration deadline. The saved entry appears in **Saved & activity**, and
only its registering player can edit it. Draft tournaments remain private to
the organisation that created them until published. See
[database verification](sportspace-database.md) to inspect saved records.

Login and sign-up use password-manager autocomplete hints. After successful
authentication, supported browsers on HTTPS (or localhost) receive a request to
save the submitted credentials through their own password manager. Browser settings
and user choice control saving; unsupported browsers use the normal form and
navigation signals. Declining or failing to save a password still completes sign-in.

Browser credential requests are encrypted before transmission; see
[encrypted account payloads](auth-payload-encryption.md) for the wire format,
one-use challenges and browser visibility limits. Names, emails and passwords
are not placed in session-token claims.

Passwords use Werkzeug scrypt hashes. Session cookies are HttpOnly and SameSite=Lax;
the database stores hashes of session tokens, expires them after seven days,
and revokes them on logout. JSON mutations require the X-Dhoyo-Request header and
reject cross-origin requests. The old demo organizer header grants no permissions.
For an HTTPS deployment, set AUTH_COOKIE_SECURE=1 (especially behind a TLS proxy).
Registration currently does not verify email ownership. **Forgot password? Reset
password** sends a six-digit email verification code that expires after ten
minutes and can be used once. Existing reset links continue to work. Resetting the password
revokes existing sessions and clears login lockouts, then returns the player to
the login form. **Profile → Password & security** also supports a password
change with the current password and a request for a recovery code. Configure
the sender using the [password recovery setup](password-reset.md).
Organizer administration is not implemented.

The existing PostgreSQL sportspace_state JSONB row stores accounts, sessions,
userPreferences and sports content. No migration deletes or replaces the existing
sports data. This retains the current project's document storage design; all writes
serialize through its transaction lock. Legacy users is not an authentication table.
Account and session fields are never included in public API responses.

## Photos

Open a player from a public post or use the main search to find registered
players. Choose **Add friend** on their profile to send a request.
**Manage friends** on your own profile shows requests to accept
or decline and the accepted friends list. Sample profiles cannot receive
requests. Sending works even if the friend-list refresh fails; the app offers
a retry when a request cannot be sent.

Use **Profile → Edit profile → Who can see your photos? → Friends only → Save
changes** to restrict profile photos, photo posts and stories, including existing
photos. Only you and accepted friends can see them. Pending requests, followers
and teammates do not grant access. Your name, sporting results and text posts stay
visible. Removing a friendship revokes photo access. The app checks access on the
server and clears cached photos when the friendship changes. New accounts and
existing accounts without a saved choice default to **Friends only**; an explicit
**Everyone on Ring** choice remains public. Sample profiles remain public.
People who previously viewed a public photo may
have saved a copy; changing privacy cannot remove those copies or protect the
original source of an external image URL.

Share → Add a photo uses the browser/OS file picker. The composer shows a preview,
a caption counter and removal control. Images keep their aspect ratio. The browser
resizes images and the server validates/re-encodes them with Pillow. Supported browser-
decodable photos under 5 MB are accepted; export unsupported HEIC files as JPG/PNG.
Photos are persisted in the existing PostgreSQL document as normalized image data.

Cloud sources depend on the device's configured providers:
- iPhone/iPad: Photo Library or Browse / Files (iCloud and installed file providers).
- Android: local photos and providers exposed by the system photo/file picker.
- Windows/macOS: local, downloaded or synced cloud files.
- Google Photos not exposed in the picker: download the image first and select it.

There are no direct Google Photos, Google Drive or OneDrive OAuth connections yet.
Those require provider application registration, OAuth credentials, redirect URLs,
and user consent. The UI explains the working device-picker path without displaying
nonfunctional provider buttons.

References:
- https://developers.google.com/photos/overview/authorization
- https://learn.microsoft.com/en-us/onedrive/developer/controls/file-pickers/
- https://support.apple.com/en-us/102238

## Validation

pytest app/tests covers authentication, account isolation, photo validation and
existing sports behavior. Legacy domain fixtures explicitly enable AUTH_TEST_DEMO
only inside their tests. Never enable that setting on a running website.
Browser smoke checks use a separate SQLite fixture with real registration and cookies.
Run `node --test app/tests/test_auth_ui.cjs` to check successful credential-saving
requests, recovery forms, failed authentication, and optional browser support
without storing passwords. Backend recovery tests mock mail delivery; they do not
send real emails.
