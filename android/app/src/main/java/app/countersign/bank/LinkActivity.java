package app.countersign.bank;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * Receives the device token from the bank page ("Turn on call alerts"), asks for the phone-state
 * and notification permissions, starts {@link CallWatchService} and goes back to the page.
 *
 * Any website could fire this link, so it is only accepted for the server and customer the user
 * chose on the setup screen: a stranger's page can't point the app at its own server.
 */
public class LinkActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Prefs prefs = new Prefs(this);
        Uri u = getIntent().getData();
        String token = u == null ? null : u.getQueryParameter("token");
        String customer = u == null ? null : u.getQueryParameter("customer");
        String base = u == null ? null : Prefs.normalise(u.getQueryParameter("base"));
        if (token == null || token.isEmpty() || !prefs.accepts(customer) || !prefs.server().equals(base)) {
            Toast.makeText(this, "This link is for a different bank server or account. Open the bank from the CS Bank app.", Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        prefs.link(customer, token);

        List<String> ask = new ArrayList<>();
        if (checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) ask.add(Manifest.permission.READ_PHONE_STATE);
        if (Build.VERSION.SDK_INT >= 33 && !CallWatchService.canNotify(this)) ask.add(Manifest.permission.POST_NOTIFICATIONS);
        if (ask.isEmpty()) done();
        else requestPermissions(ask.toArray(new String[0]), 1);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        done();
    }

    private void done() {
        CallWatchService.start(this);
        boolean phone = checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED;
        Toast.makeText(this, phone ? "Call alerts are on" : "Call alerts are on for internet calls. Allow phone access for normal calls too.", Toast.LENGTH_LONG).show();
        finish();
    }
}
