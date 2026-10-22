package app.countersign.bank;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;

import com.google.androidbrowserhelper.trusted.TwaLauncher;

/**
 * Setup and status. Picks the bank server and whose phone this is, then opens the bank pages in
 * Chrome as a Trusted Web Activity, so passkeys work exactly as in the browser. Notifications
 * open this activity with {@link #EXTRA_OPEN}, which goes straight to the bank pages.
 */
public class MainActivity extends Activity {
    static final String EXTRA_OPEN = "open_bank";
    private static final int BRAND = 0xFF1F3F94;

    private Prefs prefs;
    private TwaLauncher launcher;
    private EditText server;
    private RadioGroup who;
    private TextView status;
    private Button alertsOff;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = new Prefs(this);
        setContentView(buildUi());
        if (prefs.linked()) CallWatchService.start(this);
        handle(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handle(intent);
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    @Override
    protected void onDestroy() {
        if (launcher != null) launcher.destroy();
        super.onDestroy();
    }

    private void handle(Intent intent) {
        if (intent != null && intent.getBooleanExtra(EXTRA_OPEN, false)) {
            intent.removeExtra(EXTRA_OPEN);
            openBank();
        }
    }

    private void openBank() {
        String customer = who.getCheckedRadioButtonId() == R.id.rahul ? "rahul" : "sunita";
        prefs.setup(server.getText().toString(), customer);
        if (!prefs.linked()) CallWatchService.stop(this);
        if (launcher != null) launcher.destroy();
        launcher = new TwaLauncher(this);
        launcher.launch(Uri.parse(prefs.bankUrl()));
    }

    private void refresh() {
        boolean on = prefs.linked();
        String name = "rahul".equals(prefs.customer()) ? "Rahul" : "Sunita";
        status.setText(on
                ? "Call alerts are on for " + name + ". When this phone is on a call, normal or WhatsApp, the bank is told that a call is happening. Never the number, never the audio."
                : "Call alerts are off. Open the bank, go to Security and tap \"Turn on call alerts\".");
        alertsOff.setVisibility(on ? View.VISIBLE : View.GONE);
    }

    private View buildUi() {
        int pad = dp(24);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(pad, dp(48), pad, pad);

        TextView title = text("CS Bank", 28);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextColor(BRAND);
        col.addView(title);
        col.addView(text("Countersign demo bank app", 14));

        col.addView(label("Bank server"));
        server = new EditText(this);
        server.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        server.setSingleLine(true);
        server.setText(prefs.server());
        col.addView(server);

        col.addView(label("This phone belongs to"));
        who = new RadioGroup(this);
        who.addView(radio(R.id.rahul, "Rahul Sharma"));
        who.addView(radio(R.id.sunita, "Sunita Sharma"));
        who.check("rahul".equals(prefs.customer()) ? R.id.rahul : R.id.sunita);
        col.addView(who);

        Button open = new Button(this);
        open.setText("Open my bank");
        open.setOnClickListener(v -> openBank());
        col.addView(open, matchWidth(dp(16)));

        status = text("", 14);
        col.addView(status, matchWidth(dp(24)));

        alertsOff = new Button(this);
        alertsOff.setText("Turn off call alerts");
        alertsOff.setOnClickListener(v -> {
            prefs.unlink();
            CallWatchService.stop(this);
            refresh();
        });
        col.addView(alertsOff, matchWidth(dp(8)));

        ScrollView scroll = new ScrollView(this);
        scroll.addView(col);
        return scroll;
    }

    private RadioButton radio(int id, String label) {
        RadioButton b = new RadioButton(this);
        b.setId(id);
        b.setText(label);
        return b;
    }

    private TextView label(String s) {
        TextView t = text(s, 13);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setPadding(0, dp(20), 0, 0);
        return t;
    }

    private TextView text(String s, int sp) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        return t;
    }

    private LinearLayout.LayoutParams matchWidth(int top) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = top;
        return lp;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
