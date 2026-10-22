package app.countersign.bank;

import android.content.Context;
import android.content.SharedPreferences;

/** What the app remembers: the bank server, whose phone this is, and the device token for call alerts. */
final class Prefs {
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

    String customer() {
        return p.getString("customer", "sunita");
    }

    String token() {
        return p.getString("token", null);
    }

    boolean linked() {
        return token() != null;
    }

    /** A different server or customer invalidates the device token: it was issued for the old pair. */
    void setup(String server, String customer) {
        String s = normalise(server);
        SharedPreferences.Editor e = p.edit().putString("server", s).putString("customer", customer);
        if (!s.equals(server()) || !customer.equals(customer())) e.remove("token");
        e.apply();
    }

    void link(String token) {
        p.edit().putString("token", token).apply();
    }

    void unlink() {
        p.edit().remove("token").apply();
    }

    /** The bank pages, opened in Chrome. `app=android` tells the page it can offer call alerts. */
    String bankUrl() {
        return server() + "/bank/" + customer() + "?app=android";
    }
}
