package hub.probe;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.os.BatteryManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * 常驻前台服务：扫描蓝牙电量 -> 上报 hub。
 *
 * 存活策略
 *   - 前台服务 + 常驻低优先级通知（Android 15 需声明 connectedDevice 类型）
 *   - START_STICKY：被系统杀掉后自动重建
 *   - 电池广播触发"立即上报"
 *
 * 显示规则
 *   配对表里的设备全报；带"最近一次测到的电量"；从没测到过就报 null。
 */
public class HubService extends Service {

    private static final String TAG = "HUBPROBE";
    private static final String CHANNEL = "hub";
    private static final int NOTI_ID = 1001;
    private static final int INTERVAL_MS = 15000;

    private static final String ACT_BATTERY_LEVEL_CHANGED =
            "android.bluetooth.device.action.BATTERY_LEVEL_CHANGED";
    private static final String EXTRA_BATTERY_LEVEL =
            "android.bluetooth.device.extra.BATTERY_LEVEL";
    private static final String EXTRA_DEVICE =
            "android.bluetooth.device.extra.DEVICE";

    // 8080 被校园网封了，换 18080；第二条是 adb reverse 隧道（USB 或 WiFi adb 都行）
    // 地址列表跑在 res/values/strings.xml 的 hub_urls 里（逗号分隔，按顺序尝试）
    private String[] hubs = new String[0];

    private void loadHubs() {
        try {
            int id = getResources().getIdentifier("hub_urls", "string", getPackageName());
            String s = id == 0 ? "" : getString(id);
            if (s != null && !s.trim().isEmpty()) {
                hubs = s.split(",");
            }
        } catch (Throwable t) {
            Log.w(TAG, "读 hub_urls 失败", t);
        }
        for (int i = 0; i < hubs.length; i++) hubs[i] = hubs[i].trim();
    }
    // 同一个 APK 装到手机和平板上，靠机型自动区分节点
    private static final String NODE_ID = deriveId();
    private static final String NODE_NAME = deriveName();
    private static final String PREFS = "hubprobe";
    private static final String KEY_LAST = "last";

    private static class Per {
        String name, mac;
        int pct;
        boolean connected;
        int cls;   // BluetoothClass.getDeviceClass()，用来判断键鼠/耳机

        Per(String name, String mac, int pct, boolean connected, int cls) {
            this.name = name;
            this.mac = mac;
            this.pct = pct;
            this.connected = connected;
            this.cls = cls;
        }
    }

    private static String sanitize(String s) {
        if (s == null) return "";
        return s.toLowerCase().replaceAll("[^a-z0-9]+", "-").replaceAll("(^-+)|(-+$)", "");
    }

    private static String deriveId() {
        String m = android.os.Build.MODEL == null ? "" : android.os.Build.MODEL;
        String lower = m.toLowerCase();
        if (lower.contains("2314")) return "iqooz8";       // iQOO Z8 (V2314A)
        String s = sanitize(m);
        return s.isEmpty() ? "device" : s;
    }

    private static String deriveName() {
        String m = android.os.Build.MODEL == null ? "?" : android.os.Build.MODEL;
        String lower = m.toLowerCase();
        if (lower.contains("2314")) return "iQOO Z8";
        String brand = android.os.Build.MANUFACTURER == null ? "" : android.os.Build.MANUFACTURER;
        String n = (brand + " " + m).trim();
        return n.isEmpty() ? m : n;
    }

    private final List<Per> devices = new ArrayList<>();
    private Handler handler;
    private SharedPreferences prefs;
    private BroadcastReceiver batteryRx;
    private int lastReportedPct = -1;

    @Override
    public void onCreate() {
        super.onCreate();
        handler = new Handler(Looper.getMainLooper());
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        loadHubs();

        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        NotificationChannel ch = new NotificationChannel(
                CHANNEL, "电量上报", NotificationManager.IMPORTANCE_LOW);
        ch.setDescription("常驻运行，把电量同步到桌面面板");
        ch.setShowBadge(false);
        nm.createNotificationChannel(ch);
        startForeground(NOTI_ID, buildNotification("正在启动"));

        batteryRx = new BroadcastReceiver() {
            @Override
            public void onReceive(Context ctx, Intent it) {
                try {
                    int level = it.getIntExtra(EXTRA_BATTERY_LEVEL, -1);
                    android.os.Parcelable p = it.getParcelableExtra(EXTRA_DEVICE);
                    String name = "?", mac = "?";
                    if (p instanceof BluetoothDevice) {
                        BluetoothDevice d = (BluetoothDevice) p;
                        try {
                            name = d.getName();
                        } catch (SecurityException ignored) {
                        }
                        mac = d.getAddress();
                    }
                    Log.i(TAG, "BROADCAST level=" + level + " name=" + name);
                    if (level >= 0) {
                        saveLast(mac, name, level);
                        tick();
                    }
                } catch (Throwable t) {
                    Log.w(TAG, "广播解析失败", t);
                }
            }
        };
        registerReceiver(batteryRx, new IntentFilter(ACT_BATTERY_LEVEL_CHANGED),
                Context.RECEIVER_EXPORTED);

        tick();
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                tick();
                handler.postDelayed(this, INTERVAL_MS);
            }
        }, INTERVAL_MS);
        Log.i(TAG, "服务已启动");
    }

    private Notification buildNotification(String text) {
        return new Notification.Builder(this, CHANNEL)
                .setContentTitle("电量中枢")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setOngoing(true)
                .build();
    }

    private void tick() {
        try {
            scan();
            publish();
        } catch (Throwable t) {
            Log.w(TAG, "tick 失败", t);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        try {
            unregisterReceiver(batteryRx);
        } catch (Throwable ignored) {
        }
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private JSONObject loadLast() {
        try {
            return new JSONObject(prefs.getString(KEY_LAST, "{}"));
        } catch (Throwable e) {
            return new JSONObject();
        }
    }

    private void saveLast(String mac, String name, int pct) {
        try {
            JSONObject o = loadLast();
            JSONObject e = new JSONObject();
            e.put("pct", pct);
            e.put("name", name);
            e.put("ts", System.currentTimeMillis() / 1000);
            o.put(mac, e);
            prefs.edit().putString(KEY_LAST, o.toString()).apply();
        } catch (Throwable t) {
            Log.w(TAG, "saveLast 失败", t);
        }
    }

    private void scan() {
        BluetoothManager bm = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter ad = bm == null ? null : bm.getAdapter();
        if (ad == null) {
            return;
        }
        Set<BluetoothDevice> bonded;
        try {
            bonded = ad.getBondedDevices();
        } catch (SecurityException e) {
            Log.w(TAG, "getBondedDevices 被拒", e);
            return;
        }
        JSONObject last = loadLast();
        List<Per> fresh = new ArrayList<>();
        int live = 0, hist = 0;

        for (BluetoothDevice d : bonded) {
            String name;
            try {
                name = d.getName();
            } catch (SecurityException e) {
                name = "?";
            }
            String mac = d.getAddress();
            // 设备类型（键盘/鼠标/耳机靠它判断，比名字靠谱）
            int cls = -1;
            try {
                android.bluetooth.BluetoothClass bc = d.getBluetoothClass();
                if (bc != null) cls = bc.getDeviceClass();
            } catch (Throwable ignored) {
            }
            int pct = -1;
            try {
                java.lang.reflect.Method m = BluetoothDevice.class.getMethod("getBatteryLevel");
                Object v = m.invoke(d);
                if (v instanceof Integer) pct = (Integer) v;
            } catch (Throwable t) {
                Log.w(TAG, "reflect 失败 " + mac + " : " + t);
            }

            if (pct >= 0) {
                saveLast(mac, name, pct);
                fresh.add(new Per(name, mac, pct, true, cls));
                live++;
            } else {
                JSONObject e = last.optJSONObject(mac);
                int old = e == null ? -1 : e.optInt("pct", -1);
                String oldName = e == null ? name : e.optString("name", name);
                if (old >= 0) hist++;
                fresh.add(new Per(oldName == null || oldName.isEmpty() ? name : oldName,
                        mac, old, false, cls));
            }
        }
        devices.clear();
        devices.addAll(fresh);
        Log.i(TAG, String.format("配对 %d / 在线 %d / 历史 %d", bonded.size(), live, hist));
    }

    private void publish() {
        final String body = buildJson();
        final int pct = currentPct();
        if (pct != lastReportedPct) {
            lastReportedPct = pct;
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            String txt = pct >= 0
                    ? ("本机 " + pct + "% / 外设 " + devices.size() + " 台")
                    : ("外设 " + devices.size() + " 台");
            nm.notify(NOTI_ID, buildNotification(txt));
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                for (String hub : hubs) {
                    HttpURLConnection c = null;
                    try {
                        c = (HttpURLConnection) new URL(hub).openConnection();
                        c.setRequestMethod("POST");
                        c.setConnectTimeout(3000);
                        c.setReadTimeout(3000);
                        c.setDoOutput(true);
                        c.setRequestProperty("Content-Type", "application/json");
                        OutputStream os = c.getOutputStream();
                        os.write(body.getBytes(StandardCharsets.UTF_8));
                        os.close();
                        int code = c.getResponseCode();
                        Log.i(TAG, "POST " + hub + " -> " + code);
                        if (code == 200) {
                            fetchState(hub.replace("/report", "/state"));
                        }
                        return;
                    } catch (Throwable t) {
                        Log.w(TAG, "POST 失败 " + hub + " : " + t.getMessage());
                    } finally {
                        if (c != null) c.disconnect();
                    }
                }
            }
        }).start();
    }

    private int currentPct() {        Intent batt = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (batt == null) return -1;
        int lvl = batt.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = batt.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
        return scale > 0 ? (int) (lvl * 100.0 / scale) : -1;
    }

    /** 上报成功后再拉一次全网快照，缓存给桌面小组件用。 */
    private void fetchState(String url) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(3000);
            c.setReadTimeout(3000);
            java.io.InputStream is = c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) > 0 && bo.size() < 65536) {
                bo.write(buf, 0, n);
            }
            is.close();
            prefs.edit().putString("state", bo.toString("UTF-8")).apply();
            HubWidget.refresh(this);
        } catch (Throwable t) {
            Log.w(TAG, "GET state 失败: " + t.getMessage());
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private String buildJson() {
        try {
            JSONObject o = new JSONObject();
            o.put("node", NODE_ID);
            o.put("name", NODE_NAME);
            o.put("ts", System.currentTimeMillis() / 1000);

            Intent batt = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            int pct = -1, status = -1, plugged = -1;
            if (batt != null) {
                int lvl = batt.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
                int scale = batt.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
                pct = scale > 0 ? (int) (lvl * 100.0 / scale) : -1;
                status = batt.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                plugged = batt.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1);
            }
            JSONObject bb = new JSONObject();
            bb.put("pct", pct >= 0 ? pct : JSONObject.NULL);
            bb.put("charging", status == BatteryManager.BATTERY_STATUS_CHARGING);
            bb.put("ac", plugged > 0);
            o.put("battery", bb);

            JSONArray per = new JSONArray();
            for (Per p : devices) {
                JSONObject x = new JSONObject();
                x.put("id", p.mac.replace(":", "").toLowerCase());
                x.put("name", p.name);
                x.put("pct", p.pct >= 0 ? p.pct : JSONObject.NULL);
                x.put("connected", p.connected);
                x.put("cls", p.cls);
                per.put(x);
            }
            o.put("peripherals", per);
            return o.toString();
        } catch (Throwable t) {
            Log.w(TAG, "buildJson 失败", t);
            return "{\"node\":\"iqooz8\"}";
        }
    }
}
