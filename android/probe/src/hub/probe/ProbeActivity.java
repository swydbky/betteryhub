package hub.probe;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 只负责两件事：申请权限、拉起常驻服务。
 * 采集与上报都在 HubService 里，这里关掉也不影响。
 */
public class ProbeActivity extends Activity {

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.parseColor("#0b0f17"));
        root.setPadding(48, 48, 48, 48);

        TextView t1 = new TextView(this);
        t1.setText("电量中枢");
        t1.setTextSize(26);
        t1.setTextColor(Color.parseColor("#e8eefc"));
        t1.setGravity(Gravity.CENTER);

        TextView t2 = new TextView(this);
        t2.setText("常驻服务已启动\n可以直接返回桌面，服务继续在后台跑");
        t2.setTextSize(14);
        t2.setTextColor(Color.parseColor("#8fa0bb"));
        t2.setGravity(Gravity.CENTER);
        t2.setPadding(0, 24, 0, 0);

        root.addView(t1);
        root.addView(t2);
        setContentView(root);

        if (checkSelfPermission("android.permission.BLUETOOTH_CONNECT")
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{
                    "android.permission.BLUETOOTH_CONNECT",
                    "android.permission.BLUETOOTH_SCAN",
                    "android.permission.POST_NOTIFICATIONS"}, 1);
        }
        startService();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        startService();
    }

    private void startService() {
        try {
            startForegroundService(new Intent(this, HubService.class));
        } catch (Throwable t) {
            startService(new Intent(this, HubService.class));
        }
    }
}
