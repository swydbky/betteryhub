package hub.probe;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 只负责两件事：申请权限、拉起常驻服务。
 * 另外提供一个「中枢地址」输入框：换网/IP 变了直接在手机上改，不用重新打包 APK。
 */
public class ProbeActivity extends Activity {

    private EditText urlBox;
    private TextView status;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.parseColor("#0b0f17"));
        root.setPadding(56, 72, 56, 56);

        TextView t1 = new TextView(this);
        t1.setText("电量中枢");
        t1.setTextSize(26);
        t1.setTextColor(Color.parseColor("#e8eefc"));
        t1.setGravity(Gravity.CENTER);
        root.addView(t1);

        TextView t2 = new TextView(this);
        t2.setText("常驻服务已在后台运行。\n中枢地址变了（换网/IP 变）就在这里改，多条用英文逗号分隔，\n按顺序尝试，第一个通的就用。");
        t2.setTextSize(13);
        t2.setTextColor(Color.parseColor("#8fa0bb"));
        t2.setGravity(Gravity.CENTER);
        t2.setPadding(0, 20, 0, 20);
        root.addView(t2);

        urlBox = new EditText(this);
        urlBox.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        urlBox.setTextColor(Color.parseColor("#e8eefc"));
        urlBox.setTextSize(13);
        urlBox.setHint("http://10.0.0.1:18080/report");
        urlBox.setMinLines(3);
        urlBox.setText(currentUrls());
        root.addView(urlBox, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        Button save = new Button(this);
        save.setText("保存并重启上报");
        save.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                saveUrls();
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = 24;
        root.addView(save, lp);

        status = new TextView(this);
        status.setTextSize(12);
        status.setTextColor(Color.parseColor("#6f8ab0"));
        status.setGravity(Gravity.CENTER);
        status.setPadding(0, 16, 0, 0);
        status.setText("当前地址条数：" + countUrls());
        root.addView(status);

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

    /** 已保存的覆盖值优先，没有就显示打包时注入的内置清单 */
    private String currentUrls() {
        SharedPreferences p = getSharedPreferences("hubprobe", MODE_PRIVATE);
        String s = p.getString(HubService.KEY_URLS, "");
        if (s != null && !s.trim().isEmpty()) return s;
        int id = getResources().getIdentifier("hub_urls", "string", getPackageName());
        return id == 0 ? "" : getString(id);
    }

    private int countUrls() {
        String s = currentUrls();
        if (s == null || s.trim().isEmpty()) return 0;
        int n = 0;
        for (String part : s.split(",")) if (!part.trim().isEmpty()) n++;
        return n;
    }

    private void saveUrls() {
        String s = urlBox.getText() == null ? "" : urlBox.getText().toString().trim();
        if (s.isEmpty()) {
            Toast.makeText(this, "地址不能为空；想恢复内置清单请重装 APK", Toast.LENGTH_LONG).show();
            return;
        }
        StringBuilder clean = new StringBuilder();
        int n = 0;
        for (String part : s.split(",")) {
            String p = part.trim();
            if (p.isEmpty()) continue;
            if (!p.startsWith("http://") && !p.startsWith("https://")) {
                Toast.makeText(this, "地址必须以 http:// 或 https:// 开头：" + p, Toast.LENGTH_LONG).show();
                return;
            }
            if (n > 0) clean.append(',');
            clean.append(p);
            n++;
        }
        if (n == 0) {
            Toast.makeText(this, "没有有效地址", Toast.LENGTH_LONG).show();
            return;
        }
        getSharedPreferences("hubprobe", MODE_PRIVATE).edit()
                .putString(HubService.KEY_URLS, clean.toString()).apply();
        urlBox.setText(clean.toString());
        status.setText("已保存 " + n + " 条地址，正在重启上报服务…");
        Toast.makeText(this, "已保存，稍等几秒会上报", Toast.LENGTH_SHORT).show();
        restartService();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        startService();
    }

    private void restartService() {
        try {
            stopService(new Intent(this, HubService.class));
        } catch (Throwable ignored) {
        }
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
