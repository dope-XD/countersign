package app.countersign.bank;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * What the app remembers: the bank server, whose phone this is, and the device token for call alerts.
 *
 * Mode "try" (the default) is a judge's phone: the app opens /try, which makes a private demo
 * account. "rahul" and "sunita" are the team's phones for the scripted demo.
 */
final class Prefs {
    static final String TRY = "try";
    private final SharedPreferences p;

    Prefs(Context c) {
        p = c.getSharedPreferences("countersign", Context.MODE_PRIVATE);
    }

    static String normalise(String url) {
        String u = url == null ? "" : url.trim();
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    String server() {
        return p.getString("server", BuildConfig.DEFAULT_SERVER);
    }

    String mode() {
        return p.getString("mode", TRY);
    }

    /** The customer whose call alerts are on (a judge's sandbox id in try mode). */
    String linkedCustomer() {
        return p.getString("linked", null);
    }

    String token() {
        return p.getString("token", null);
    }

    boolean linked() {
        return token() != null && linkedCustomer() != null;
    }

    /** Would the app take a call-alerts link for this customer? */
    boolean accepts(String customer) {
        if (customer == null) return false;
        return TRY.equals(mode()) ? customer.startsWith("judge-") : mode().equals(customer);
    }

    /** A different server or mode invalidates the device token: it was issued for the old pair. */
    void setup(String server, String mode) {
        String s = normalise(server);
        SharedPreferences.Editor e = p.edit().putString("server", s).putString("mode", mode);
        if (!s.equals(server()) || !mode.equals(mode())) e.remove("token").remove("linked");
        e.apply();
    }

    void link(String customer, String token) {
        p.edit().putString("linked", customer).putString("token", token).apply();
    }

    void unlink() {
        p.edit().remove("token").remove("linked").apply();
    }

    /** The pages the app opens, in Chrome. `app=android` tells them they can offer call alerts. */
    String bankUrl() {
        return TRY.equals(mode()) ? server() + "/try?app=android" : server() + "/bank/" + mode() + "?app=android";
    }
}
