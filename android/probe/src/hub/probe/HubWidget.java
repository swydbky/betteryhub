package hub.probe;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.widget.RemoteViews;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 桌面小组件（RemoteViews 版，不用 Gradle/Compose）。
 *
 * 数据来源：HubService 每次上报成功后顺手 GET 一次 /state，缓存到 SharedPreferences。
 * 小组件只负责把缓存画出来，不自己发网络请求（省电、也不会在 doze 里卡住）。
 */
public class HubWidget extends AppWidgetProvider {

    public static final String ACTION_RENDER = "hub.probe.WIDGET_RENDER";
    static final String PREFS = "hubprobe";
    static final String KEY_STATE = "state";

    /** 面板地址取地址清单里的第一条（去掉 /report 换成 /） */
    static String panelUrl(Context ctx) {
        try {
            int id = ctx.getResources().getIdentifier("hub_urls", "string", ctx.getPackageName());
            String s = id == 0 ? "" : ctx.getString(id);
            if (s != null && !s.trim().isEmpty()) {
                return s.split(",")[0].trim().replace("/report", "/");
            }
        } catch (Throwable ignored) {
        }
        return "";
    }

    @Override
    public void onUpdate(Context ctx, AppWidgetManager mgr, int[] ids) {
        render(ctx, mgr, ids);
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        super.onReceive(ctx, intent);
        if (ACTION_RENDER.equals(intent.getAction())) {
            AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
            render(ctx, mgr, mgr.getAppWidgetIds(new ComponentName(ctx, HubWidget.class)));
        }
    }

    static void refresh(Context ctx) {
        try {
            AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
            render(ctx, mgr, mgr.getAppWidgetIds(new ComponentName(ctx, HubWidget.class)));
        } catch (Throwable ignored) {
        }
    }

    private static int rid(Context c, String name, String type) {
        return c.getResources().getIdentifier(name, type, c.getPackageName());
    }

    private static void render(Context ctx, AppWidgetManager mgr, int[] ids) {
        if (ids == null || ids.length == 0) return;
        int layout = rid(ctx, "widget", "layout");
        if (layout == 0) return;

        SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        JSONArray nodes = new JSONArray();
        long hubTs = 0;
        try {
            JSONObject root = new JSONObject(sp.getString(KEY_STATE, "{}"));
            nodes = root.optJSONArray("nodes");
            hubTs = root.optLong("hub_ts", 0);
            if (nodes == null) nodes = new JSONArray();
        } catch (Throwable ignored) {
        }

        for (int id : ids) {
            RemoteViews rv = new RemoteViews(ctx.getPackageName(), layout);

            // 点一下打开网页面板
            String panel = panelUrl(ctx);
            Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse(panel));
            open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            PendingIntent pi = PendingIntent.getActivity(ctx, 0, open,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            int rootId = rid(ctx, "w_root", "id");
            if (rootId != 0) rv.setOnClickPendingIntent(rootId, pi);

            int timeId = rid(ctx, "w_time", "id");
            if (timeId != 0) {
                String t = hubTs > 0 ? ago((System.currentTimeMillis() / 1000) - hubTs) : "无数据";
                rv.setTextViewText(timeId, t);
            }

            for (int i = 0; i < 3; i++) {
                int rowId = rid(ctx, "w_row" + i, "id");
                int nameId = rid(ctx, "w_name" + i, "id");
                int pctId = rid(ctx, "w_pct" + i, "id");
                int barId = rid(ctx, "w_bar" + i, "id");
                int perId = rid(ctx, "w_per" + i, "id");

                if (i >= nodes.length()) {
                    if (rowId != 0) rv.setViewVisibility(rowId, android.view.View.GONE);
                    if (barId != 0) rv.setViewVisibility(barId, android.view.View.GONE);
                    if (perId != 0) rv.setViewVisibility(perId, android.view.View.GONE);
                    continue;
                }
                JSONObject n = nodes.optJSONObject(i);
                if (n == null) continue;
                JSONObject b = n.optJSONObject("battery");
                int pct = b == null ? -1 : b.optInt("pct", -1);
                boolean online = n.optBoolean("online", false);
                boolean ac = b != null && b.optBoolean("ac", false);
                String name = n.optString("name", n.optString("node", "?"));

                if (nameId != 0) rv.setTextViewText(nameId, (online ? "" : "· ") + name);
                if (pctId != 0) {
                    String s = (pct < 0 ? "—" : pct + "%") + (ac && online ? " ⚡" : "");
                    rv.setTextViewText(pctId, s);
                }
                if (nameId != 0) rv.setTextColor(nameId, online ? 0xFFE8EEFC : 0xFF5F6B7F);
                if (pctId != 0) rv.setTextColor(pctId, online ? 0xFFE8EEFC : 0xFF5F6B7F);

                int icoId = rid(ctx, "w_ico" + i, "id");
                if (icoId != 0) {
                    String ic = iconName(name, -1);
                    int res = ctx.getResources().getIdentifier(ic, "drawable", ctx.getPackageName());
                    if (res != 0) rv.setImageViewResource(icoId, res);
                    rv.setInt(icoId, "setColorFilter", online ? 0xFFE8EEFC : 0xFF5F6B7F);
                }
                if (barId != 0) {
                    rv.setViewVisibility(barId, android.view.View.VISIBLE);
                    rv.setProgressBar(barId, 100, Math.max(0, pct), false);
                }
                if (perId != 0) {
                    // 每个外设一行；没连上的整行变灰
                    SpannableStringBuilder sb = new SpannableStringBuilder();
                    JSONArray per = n.optJSONArray("peripherals");
                    if (per != null) {
                        for (int k = 0; k < per.length(); k++) {
                            JSONObject p = per.optJSONObject(k);
                            if (p == null) continue;
                            boolean on = p.optBoolean("connected", true);
                            int pp = p.optInt("pct", -1);
                            String line = (on ? "" : "· ") + p.optString("name", "?")
                                    + "  " + (pp < 0 ? "—" : pp + "%");
                            int start = sb.length();
                            if (start > 0) sb.append("\n");
                            start = sb.length();
                            sb.append(line);
                            int col = on ? 0xFFC2CEE2 : 0xFF5F6B7F;
                            sb.setSpan(new ForegroundColorSpan(col), start, sb.length(),
                                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                        }
                    }
                    rv.setTextViewText(perId, sb);
                    rv.setViewVisibility(perId, sb.length() == 0 ? android.view.View.GONE
                            : android.view.View.VISIBLE);
                }
            }
            mgr.updateAppWidget(id, rv);
        }
    }

    private static String iconName(String name, int cls) {
        int major = cls > 0 ? (cls & 0x1F00) : 0;
        int minor = cls > 0 ? (cls & 0x00FC) : 0;
        String s = name == null ? "" : name.toLowerCase();

        if (major == 0x0500) {
            if (minor == 0x40) return "ic_kb";
            if (minor == 0x80) return "ic_mouse";
            if (minor == 0xC0) return "ic_kb";
        }
        if (major == 0x0400) {
            if (s.contains("buds") || s.contains("tws") || s.contains("豆")
                    || s.contains("耳机") || s.contains("anc")) return "ic_earbuds";
            return "ic_headphone";
        }
        if (major == 0x0100) return "ic_laptop";
        if (major == 0x0200) return "ic_phone";

        if (s.contains("平板") || s.contains("pad") || s.contains("tablet")) return "ic_tablet";
        if (s.contains("笔电") || s.contains("笔记本") || s.contains("laptop")
                || s.contains("win10") || s.contains("win11") || s.contains("电脑")) return "ic_laptop";
        if (s.contains("iqoo") || s.contains("phone") || s.contains("手机")) return "ic_phone";
        if (s.contains("耳机") || s.contains("buds") || s.contains("airpods")) return "ic_earbuds";
        if (s.contains("头戴")) return "ic_headphone";
        if (s.contains("键盘") || s.contains("keyboard")) return "ic_kb";
        if (s.contains("鼠标") || s.contains("mouse")) return "ic_mouse";
        if (s.matches(".*\\bk\\d{3}\\b.*")) return "ic_kb";
        if (s.matches(".*\\bm\\d{3}\\b.*")) return "ic_mouse";
        return "ic_generic";
    }

    private static String ago(long sec) {
        if (sec < 60) return sec + " 秒前";
        if (sec < 3600) return (sec / 60) + " 分钟前";
        if (sec < 86400) return (sec / 3600) + " 小时前";
        return (sec / 86400) + " 天前";
    }
}
