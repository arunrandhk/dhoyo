package com.dhoyo.app;

import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Locale;

/** Pure validation and PKCE helpers; browser data never chooses an API origin. */
final class ConnectionSecurity {
    private static final char[] URL_ALPHABET =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".toCharArray();

    private ConnectionSecurity() {}

    static String origin(String setting) {
        if (setting == null || setting.trim().isEmpty()) return null;
        try {
            URI value = new URI(setting.trim());
            String path = value.getRawPath();
            if (!"https".equals(value.getScheme()) || value.getHost() == null ||
                    value.getHost().isEmpty() || value.getRawUserInfo() != null ||
                    value.getRawQuery() != null || value.getRawFragment() != null ||
                    (path != null && !path.isEmpty() && !"/".equals(path)) ||
                    (value.getPort() != -1 && (value.getPort() < 1 || value.getPort() > 65535))) {
                return null;
            }
            return new URI("https", null, value.getHost().toLowerCase(Locale.ROOT),
                    value.getPort(), null, null, null).toASCIIString();
        } catch (URISyntaxException | IllegalArgumentException ignored) {
            return null;
        }
    }

    static boolean validVerifier(String verifier) {
        return verifier != null && verifier.matches("[A-Za-z0-9_-]{43,128}");
    }

    static String newVerifier() {
        byte[] bytes = new byte[64];
        new SecureRandom().nextBytes(bytes);
        return base64Url(bytes);
    }

    static String challenge(String verifier) {
        if (!validVerifier(verifier)) throw new IllegalArgumentException("Invalid verifier");
        try {
            return base64Url(MessageDigest.getInstance("SHA-256")
                    .digest(verifier.getBytes(StandardCharsets.US_ASCII)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is required by Android", impossible);
        }
    }

    static String callbackTicket(String callback) {
        if (callback == null || callback.length() > 512) return null;
        try {
            URI value = new URI(callback);
            String path = value.getRawPath();
            if (!"dhoyo".equals(value.getScheme()) || !"play-games".equals(value.getRawAuthority()) ||
                    value.getRawFragment() != null ||
                    (path != null && !path.isEmpty() && !"/".equals(path))) return null;
            String query = value.getRawQuery();
            if (query == null || !query.matches("ticket=[A-Za-z0-9_-]{43,128}")) return null;
            return query.substring("ticket=".length());
        } catch (URISyntaxException ignored) {
            return null;
        }
    }

    private static String base64Url(byte[] input) {
        StringBuilder encoded = new StringBuilder((input.length * 8 + 5) / 6);
        int remaining = 0;
        int buffer = 0;
        for (byte value : input) {
            buffer = (buffer << 8) | (value & 255);
            remaining += 8;
            while (remaining >= 6) {
                remaining -= 6;
                encoded.append(URL_ALPHABET[(buffer >>> remaining) & 63]);
            }
        }
        if (remaining > 0) encoded.append(URL_ALPHABET[(buffer << (6 - remaining)) & 63]);
        return encoded.toString();
    }
}
