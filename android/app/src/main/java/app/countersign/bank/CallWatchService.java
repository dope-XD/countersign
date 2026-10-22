package app.countersign.bank;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.telephony.TelephonyCallback;
import android.telephony.TelephonyManager;
import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;

/**
 * Runs while call alerts are on.
 *
 * Calls: a normal call shows up as the telephony call state going off-hook; an internet call
 * (WhatsApp, Meet, ...) as the phone's audio mode switching to "in communication". Either way
 * the service only tells the engine that a call started or ended, and what kind it was. It
 * never reads the number, the contact or the audio, and Android wouldn't let it hear the call.
 *
 * Notifications: it keeps the customer's app event stream open (/ws/events with the device
 * token) and turns approval requests and alerts into notifications, so they reach the phone
 * with the bank pages closed.
 */
public class CallWatchService extends Service {
    private static final String TAG = "CallWatch";
    private static final String CH_WATCH = "watch";
    private static final String CH_APPROVALS = "approvals";
    private static final int WATCH_ID = 1;
    private static final MediaType JSON = MediaType.get("application/json");

    private final Handler main = new Handler(Looper.getMainLooper());
    private final OkHttpClient http = new OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).build();
    private Prefs prefs;
    private AudioManager audio;
    private TelephonyManager phone;
    private TelephonyCallback phoneCallback;
    private AudioManager.OnModeChangedListener modeListener;
    private int callState = TelephonyManager.CALL_STATE_IDLE;
    private boolean onCall;
    private String kind = "phone";
    private WebSocket events;
    private int retries;
    private boolean stopped;

    static void start(Context c) {
        c.startForegroundService(new Intent(c, CallWatchService.class));
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, CallWatchService.class));
    }

    private final Runnable poll = new Runnable() {
        @Override
        public void run() {
            update(); // the mode listener can miss a change on some phones; this catches it within 2 s
            main.postDelayed(this, 2000);
        }
    };

    private final Runnable heartbeat = new Runnable() {
        @Override
        public void run() {
            if (events != null) events.send("hb"); // the engine counts the app as open while these arrive
            main.postDelayed(this, 20_000);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = new Prefs(this);
        channels();
        if (Build.VERSION.SDK_INT >= 34) startForeground(WATCH_ID, watchNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(WATCH_ID, watchNotification());
        audio = getSystemService(AudioManager.class);
        phone = getSystemService(TelephonyManager.class);
        watchCalls();
        connect();
        main.postDelayed(heartbeat, 20_000);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (!prefs.linked()) stopSelf();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        stopped = true;
        main.removeCallbacksAndMessages(null);
        if (phoneCallback != null) phone.unregisterTelephonyCallback(phoneCallback);
        if (modeListener != null) audio.removeOnModeChangedListener(modeListener);
        if (events != null) events.close(1000, "call alerts off");
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // ------------------------------------------------------------------ calls

    private class PhoneState extends TelephonyCallback implements TelephonyCallback.CallStateListener {
        @Override
        public void onCallStateChanged(int state) {
            callState = state;
            update();
        }
    }

    private void watchCalls() {
        if (checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED) {
            phoneCallback = new PhoneState();
            phone.registerTelephonyCallback(getMainExecutor(), phoneCallback);
        }
        modeListener = mode -> update();
        audio.addOnModeChangedListener(getMainExecutor(), modeListener);
        main.post(poll);
    }

    private void update() {
        int mode = audio.getMode();
        boolean normal = callState == TelephonyManager.CALL_STATE_OFFHOOK || mode == AudioManager.MODE_IN_CALL;
        boolean internet = mode == AudioManager.MODE_IN_COMMUNICATION || (Build.VERSION.SDK_INT >= 33 && mode == AudioManager.MODE_COMMUNICATION_REDIRECT);
        boolean now = normal || internet;
        if (now == onCall) return;
        onCall = now;
        if (now) kind = normal ? "phone" : "internet";
        report(now ? "active" : "ended", kind);
        getSystemService(NotificationManager.class).notify(WATCH_ID, watchNotification());
    }

    private void report(String state, String kind) {
        String body = "{\"state\":\"" + state + "\",\"kind\":\"" + kind + "\"}";
        Request req = authed(prefs.server() + "/api/app/" + prefs.customer() + "/call-state").post(RequestBody.create(body, JSON)).build();
        http.newCall(req).enqueue(new Callback() {
            @Override
            public void onFailure(Call call, IOException e) {
                Log.w(TAG, "call state not sent: " + e);
            }

            @Override
            public void onResponse(Call call, Response r) {
                Log.i(TAG, "call " + state + " (" + kind + "): HTTP " + r.code());
                r.close();
            }
        });
    }

    // ------------------------------------------------------------------ app events -> notifications

    private void connect() {
        if (stopped || !prefs.linked()) return;
        String ws = prefs.server().replaceFirst("^http", "ws") + "/ws/events?topics=app:" + prefs.customer();
        events = http.newWebSocket(authed(ws).build(), new WebSocketListener() {
            @Override
            public void onOpen(WebSocket s, Response r) {
                retries = 0;
            }

            @Override
            public void onMessage(WebSocket s, String text) {
                main.post(() -> onEvent(text));
            }

            @Override
            public void onFailure(WebSocket s, Throwable t, Response r) {
                Log.w(TAG, "events dropped: " + t);
                reconnect();
            }

            @Override
            public void onClosed(WebSocket s, int code, String reason) {
                reconnect();
            }
        });
    }

    private void reconnect() {
        if (stopped) return;
        long delay = Math.min(30, 1L << Math.min(retries++, 5));
        main.postDelayed(this::connect, delay * 1000);
    }

    private void onEvent(String text) {
        try {
            JSONObject e = new JSONObject(text);
            String type = e.optString("type");
            if ("approval".equals(type)) {
                JSONObject a = e.getJSONObject("approval");
                JSONObject s = a.optJSONObject("summary");
                String question = s == null ? "Did you ask for this?" : s.optString("question", "Did you ask for this?");
                String detail = s == null ? "" : s.optString("detail", "");
                notify(a.optString("id").hashCode(), question, detail.isEmpty() ? "Tap to approve or decline in CS Bank." : detail);
            } else if ("alert".equals(type)) {
                notify(text.hashCode(), e.optString("title"), e.optString("body"));
            }
        } catch (JSONException ex) {
            Log.w(TAG, "bad event: " + ex);
        }
    }

    // ------------------------------------------------------------------ notifications

    private void channels() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CH_WATCH, "Call alerts", NotificationManager.IMPORTANCE_LOW));
        NotificationChannel approvals = new NotificationChannel(CH_APPROVALS, "Approval requests", NotificationManager.IMPORTANCE_HIGH);
        approvals.enableVibration(true);
        nm.createNotificationChannel(approvals);
    }

    private PendingIntent openBank(int requestCode) {
        Intent i = new Intent(this, MainActivity.class).putExtra(MainActivity.EXTRA_OPEN, true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return PendingIntent.getActivity(this, requestCode, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    private Notification watchNotification() {
        String text = onCall
                ? ("internet".equals(kind) ? "On an internet call. " : "On a call. ") + "Payments to new payees will be paused."
                : "Watching for calls. The bank never gets the number or the audio.";
        return new Notification.Builder(this, CH_WATCH)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle("CS Bank call alerts are on")
                .setContentText(text)
                .setOngoing(true)
                .setContentIntent(openBank(0))
                .build();
    }

    /** Android 12 has no notification permission: apps may post unless the user turned them off. */
    static boolean canNotify(Context c) {
        return Build.VERSION.SDK_INT < 33 || c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    private void notify(int id, String title, String body) {
        if (!canNotify(this)) return;
        Notification n = new Notification.Builder(this, CH_APPROVALS)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setCategory(Notification.CATEGORY_MESSAGE)
                .setAutoCancel(true)
                .setContentIntent(openBank(id))
                .build();
        getSystemService(NotificationManager.class).notify(id, n);
    }

    private Request.Builder authed(String url) {
        return new Request.Builder()
                .url(url)
                .header("X-Device-Token", prefs.token() == null ? "" : prefs.token())
                .header("ngrok-skip-browser-warning", "1"); // ngrok's free tier otherwise answers with its warning page
    }
}
