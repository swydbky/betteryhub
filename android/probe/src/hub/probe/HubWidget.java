package hub.probe;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.widget.RemoteViews;

import org.json.JSONObject;

/**
 * 桌面小组件（RemoteViews + ListView 集合型）。
 *
 * 三种尺寸由三个子类提供（小 / 中 / 大），添加组件时在列表里就能选；
 * 内容用 ListView 承载，所以设备多了可以在组件里上下滑动查看。
 *
 * 数据来源：HubService 每次上报成功后顺手 GET 一次 /state，缓存到 SharedPreferences。
 * 小组件只负责把缓存画出来，不自己发网络请求（省电、也不会在 doze 里卡住）。
 */
public class HubWidget extends AppWidgetProvider {

    public static final String ACTION_RENDER = "hub.probe.WIDGET_RENDER";
    public static final String PREFS = "hubprobe";
    public static final String KEY_STATE = "state";

    /** 面板地址：优先用 App 里手填的第一条，没有才用内置清单 */
    static String panelUrl(Context ctx) {
        try {
            SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            String s = p.getString(HubService.KEY_URLS, "");
            if (s == null || s.trim().isEmpty()) {
                int id = ctx.getResources().getIdentifier("hub_urls", "string", ctx.getPackageName());
                s = id == 0 ? "" : ctx.getString(id);
            }
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
    public void onAppWidgetOptionsChanged(Context ctx, AppWidgetManager mgr, int id, Bundle opts) {
        render(ctx, mgr, new int[]{id});
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        super.onReceive(ctx, intent);
        if (ACTION_RENDER.equals(intent.getAction())) {
            AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
            render(ctx, mgr, mgr.getAppWidgetIds(new ComponentName(ctx, getClass())));
        }
    }

    /** 三种尺寸的 provider 一起刷新 */
    static void refresh(Context ctx) {
        AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
        Class<?>[] kinds = {HubWidget.class, HubWidgetSmall.class, HubWidgetLarge.class};
        for (Class<?> k : kinds) {
            try {
                int[] ids = mgr.getAppWidgetIds(new ComponentName(ctx, k));
                if (ids != null && ids.length > 0) render(ctx, mgr, ids);
            } catch (Throwable ignored) {
            }
        }
    }

    static int rid(Context c, String name, String type) {
        return c.getResources().getIdentifier(name, type, c.getPackageName());
    }

    private static void render(Context ctx, AppWidgetManager mgr, int[] ids) {
        if (ids == null || ids.length == 0) return;
        int layout = rid(ctx, "widget", "layout");
        if (layout == 0) return;

        SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long hubTs = 0;
        try {
            hubTs = new JSONObject(sp.getString(KEY_STATE, "{}")).optLong("hub_ts", 0);
        } catch (Throwable ignored) {
        }

        int rootId = rid(ctx, "w_root", "id");
        int timeId = rid(ctx, "w_time", "id");
        int listId = rid(ctx, "w_list", "id");
        int emptyId = rid(ctx, "w_empty", "id");
        String panel = panelUrl(ctx);

        for (int id : ids) {
            RemoteViews rv = new RemoteViews(ctx.getPackageName(), layout);

            // 点一下打开网页面板
            if (rootId != 0 && panel != null && !panel.isEmpty()) {
                Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse(panel));
                open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                PendingIntent pi = PendingIntent.getActivity(ctx, 0, open,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                rv.setOnClickPendingIntent(rootId, pi);
            }

            if (timeId != 0) {
                rv.setTextViewText(timeId, hubTs > 0
                        ? ago((System.currentTimeMillis() / 1000) - hubTs) : "无数据");
            }

            // 每一行由 WidgetService 生成，ListView 自带滑动
            if (listId != 0) {
                Intent svc = new Intent(ctx, WidgetService.class);
                svc.putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id);
                svc.setData(Uri.parse(svc.toUri(Intent.URI_INTENT_SCHEME)));
                rv.setRemoteAdapter(listId, svc);
                if (emptyId != 0) rv.setEmptyView(listId, emptyId);
            }

            mgr.updateAppWidget(id, rv);
        }
        if (listId != 0) {
            try {
                mgr.notifyAppWidgetViewDataChanged(ids, listId);
            } catch (Throwable ignored) {
            }
        }
    }

    static String iconName(String name, int cls) {
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

    static String ago(long sec) {
        if (sec < 60) return sec + " 秒前";
        if (sec < 3600) return (sec / 60) + " 分钟前";
        if (sec < 86400) return (sec / 3600) + " 小时前";
        return (sec / 86400) + " 天前";
    }
}
