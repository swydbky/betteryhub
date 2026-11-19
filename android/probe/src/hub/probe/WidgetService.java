package hub.probe;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.view.View;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 给小组件的 ListView 供数据。
 *
 * 之所以要这一层：AppWidget 里的 RemoteViews 不支持 ScrollView，
 * 想“在桌面直接滑着看”只能走 ListView 集合型组件（系统帮你处理手势和回收）。
 * 数据仍然只读 SharedPreferences 缓存，不发网络请求。
 */
public class WidgetService extends RemoteViewsService {

    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new Factory(getApplicationContext());
    }

    static class Factory implements RemoteViewsService.RemoteViewsFactory {

        private final Context ctx;
        private JSONArray nodes = new JSONArray();

        Factory(Context c) {
            this.ctx = c;
        }

        @Override
        public void onCreate() {
        }

        @Override
        public void onDestroy() {
        }

        @Override
        public void onDataSetChanged() {
            try {
                SharedPreferences sp = ctx.getSharedPreferences(HubWidget.PREFS, Context.MODE_PRIVATE);
                JSONObject root = new JSONObject(sp.getString(HubWidget.KEY_STATE, "{}"));
                JSONArray a = root.optJSONArray("nodes");
                nodes = a == null ? new JSONArray() : a;
            } catch (Throwable t) {
                nodes = new JSONArray();
            }
        }

        @Override
        public int getCount() {
            return nodes.length();
        }

        @Override
        public RemoteViews getViewAt(int i) {
            JSONObject n = nodes.optJSONObject(i);
            if (n == null) return null;

            int layout = HubWidget.rid(ctx, "widget_row", "layout");
            if (layout == 0) return null;
            RemoteViews rv = new RemoteViews(ctx.getPackageName(), layout);

            JSONObject b = n.optJSONObject("battery");
            int pct = b == null ? -1 : b.optInt("pct", -1);
            boolean online = n.optBoolean("online", false);
            boolean ac = b != null && b.optBoolean("ac", false);
            String name = n.optString("name", n.optString("node", "?"));

            int icoId = HubWidget.rid(ctx, "w_ico", "id");
            int nameId = HubWidget.rid(ctx, "w_name", "id");
            int pctId = HubWidget.rid(ctx, "w_pct", "id");
            int barId = HubWidget.rid(ctx, "w_bar", "id");
            int perId = HubWidget.rid(ctx, "w_per", "id");

            if (nameId != 0) {
                rv.setTextViewText(nameId, (online ? "" : "· ") + name);
                rv.setTextColor(nameId, online ? 0xFFE8EEFC : 0xFF5F6B7F);
            }
            if (pctId != 0) {
                rv.setTextViewText(pctId, (pct < 0 ? "—" : pct + "%") + (ac && online ? " ⚡" : ""));
                rv.setTextColor(pctId, online ? 0xFFE8EEFC : 0xFF5F6B7F);
            }
            if (icoId != 0) {
                int res = ctx.getResources().getIdentifier(
                        HubWidget.iconName(name, -1), "drawable", ctx.getPackageName());
                if (res != 0) rv.setImageViewResource(icoId, res);
                rv.setInt(icoId, "setColorFilter", online ? 0xFFE8EEFC : 0xFF5F6B7F);
            }
            if (barId != 0) {
                rv.setProgressBar(barId, 100, Math.max(0, pct), false);
            }
            if (perId != 0) {
                SpannableStringBuilder sb = new SpannableStringBuilder();
                JSONArray per = n.optJSONArray("peripherals");
                if (per != null) {
                    for (int k = 0; k < per.length(); k++) {
                        JSONObject p = per.optJSONObject(k);
                        if (p == null) continue;
                        boolean on = p.optBoolean("connected", true);
                        int pp = p.optInt("pct", -1);
                        String line = (on ? "" : "· ") + p.optString("name", "?")
                                + (p.optBoolean("dual", false) ? "（双设备）" : "")
                                + "  " + (pp < 0 ? "—" : pp + "%");
                        if (sb.length() > 0) sb.append("\n");
                        int start = sb.length();
                        sb.append(line);
                        sb.setSpan(new ForegroundColorSpan(on ? 0xFFC2CEE2 : 0xFF5F6B7F),
                                start, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                    }
                }
                rv.setTextViewText(perId, sb);
                rv.setViewVisibility(perId, sb.length() == 0 ? View.GONE : View.VISIBLE);
            }
            return rv;
        }

        @Override
        public RemoteViews getLoadingView() {
            return null;
        }

        @Override
        public int getViewTypeCount() {
            return 1;
        }

        @Override
        public long getItemId(int i) {
            return i;
        }

        @Override
        public boolean hasStableIds() {
            return false;
        }
    }
}
