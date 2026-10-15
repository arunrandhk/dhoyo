package com.dhoyo.app;

import org.junit.Test;
import static org.junit.Assert.*;

public class ConnectionSecurityTest {
    @Test
    public void onlyExplicitHttpsOriginsAreAccepted() {
        assertEquals("https://byte-ring-demo.onrender.com", ConnectionSecurity.origin("https://byte-ring-demo.onrender.com/"));
        assertEquals("https://dhoyo.example:8443", ConnectionSecurity.origin("https://DHOYO.example:8443"));
        for (String bad : new String[]{"", "http://dhoyo.example", "javascript:alert(1)",
                "https://user:password@dhoyo.example", "https://dhoyo.example/ring",
                "https://dhoyo.example?next=https://attacker.example", "https://dhoyo.example#fragment",
                "https://dhoyo.example:0", "https://dhoyo.example:70000", "//dhoyo.example"}) {
            assertNull(bad, ConnectionSecurity.origin(bad));
        }
    }

    @Test
    public void verifierUsesRandomUrlSafeBytesAndStandardSha256PkceChallenge() {
        String first = ConnectionSecurity.newVerifier();
        String second = ConnectionSecurity.newVerifier();
        assertTrue(ConnectionSecurity.validVerifier(first));
        assertEquals(86, first.length());
        assertNotEquals(first, second);
        assertEquals(43, ConnectionSecurity.challenge(first).length());
        assertEquals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                ConnectionSecurity.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"));
    }

    @Test
    public void malformedOrWeakVerifiersAreRejected() {
        for (String bad : new String[]{"", "too-short", "a".repeat(129), "a".repeat(42),
                "a".repeat(42) + "+", "a".repeat(42) + "/"}) {
            assertFalse(ConnectionSecurity.validVerifier(bad));
            try {
                ConnectionSecurity.challenge(bad);
                fail("Invalid verifier accepted");
            } catch (IllegalArgumentException expected) {
                // Invalid verifiers never reach the browser or server.
            }
        }
    }

    @Test
    public void callbackMustHaveExactSchemeAuthorityAndOneOpaqueTicket() {
        String ticket = "a".repeat(43);
        assertEquals(ticket, ConnectionSecurity.callbackTicket("dhoyo://play-games?ticket=" + ticket));
        assertEquals(ticket, ConnectionSecurity.callbackTicket("dhoyo://play-games/?ticket=" + ticket));
        for (String bad : new String[]{
                "https://play-games?ticket=" + ticket,
                "dhoyo://attacker.example?ticket=" + ticket,
                "dhoyo://user@play-games?ticket=" + ticket,
                "dhoyo://play-games:443?ticket=" + ticket,
                "dhoyo://play-games/other?ticket=" + ticket,
                "dhoyo://play-games?ticket=" + ticket + "&ticket=" + ticket,
                "dhoyo://play-games?ticket=" + ticket + "&redirect=https://attacker.example",
                "dhoyo://play-games?ticket=" + ticket + "#fragment",
                "dhoyo://play-games?ticket=short",
                "dhoyo://play-games?ticket=%61" + "a".repeat(42),
                "dhoyo://play-games?ticket=" + "a".repeat(129)}) {
            assertNull(bad, ConnectionSecurity.callbackTicket(bad));
        }
    }
}
