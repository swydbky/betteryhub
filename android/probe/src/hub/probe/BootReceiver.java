package hub.probe;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * 开机自启 + 覆盖安装后自启。
 *
 * 为什么需要它：
 *   START_STICKY 只能救"被系统杀死"，救不了"APK 被覆盖安装"——
 *   后者会把进程直接干掉，且不会再拉起来，表现就是"数据一直不更新"。
 */
public class BootReceiver extends BroadcastReceiver {

    private static final String TAG = "HUBPROBE";

    @Override
    public void onReceive(Context ctx, Intent intent) {
        String a = intent == null ? "" : intent.getAction();
        Log.i(TAG, "BootReceiver: " + a);
        if (Intent.ACTION_BOOT_COMPLETED.equals(a)
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)
                || "android.intent.action.QUICKBOOT_POWERON".equals(a)) {
            try {
                ctx.startForegroundService(new Intent(ctx, HubService.class));
            } catch (Throwable t) {
                try {
                    ctx.startService(new Intent(ctx, HubService.class));
                } catch (Throwable ignored) {
                }
            }
        }
    }
}
