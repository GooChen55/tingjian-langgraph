package com.atguigu.tingshu.common.access;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

public final class Passwords {
    private Passwords() {}
    private static byte[] derive(String password, byte[] salt, int iterations) throws Exception {
        var spec = new PBEKeySpec(password.toCharArray(), salt, iterations, 256);
        try { return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded(); }
        finally { spec.clearPassword(); }
    }
    public static String hash(String password) {
        try {
            byte[] salt = new byte[16]; new SecureRandom().nextBytes(salt);
            return "pbkdf2-sha256$600000$" + Base64.getEncoder().encodeToString(salt) + "$" +
                    Base64.getEncoder().encodeToString(derive(password, salt, 600000));
        } catch (Exception error) { throw new IllegalStateException("密码加密不可用", error); }
    }
    public static boolean matches(String password, String encoded) {
        try {
            var parts = encoded.split("\\$");
            int iterations = Integer.parseInt(parts[1]);
            if (!parts[0].equals("pbkdf2-sha256") || iterations < 600000 || iterations > 1000000) return false;
            return MessageDigest.isEqual(Base64.getDecoder().decode(parts[3]),
                    derive(password, Base64.getDecoder().decode(parts[2]), iterations));
        } catch (Exception error) { return false; }
    }
}
