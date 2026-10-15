package org.carveracommunity.controller;

import android.app.Activity;
import android.graphics.Rect;
import android.hardware.input.InputManager;
import android.os.Build;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.Window;
import android.view.WindowInsets;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import org.json.JSONArray;
import org.json.JSONObject;
import org.kivy.android.PythonActivity;

/** Observes input without replacing SDL's surface or the launcher activity. */
public final class InputBridge {
    private static final Object lock = new Object();
    private static JSONArray edges = new JSONArray();
    private static boolean interrupted;
    private static boolean focused = true;
    private static Activity activity;
    private static int keyboardHeight;
    private static int left, top, right, bottom;
    private static int slop;
    private static int hold;
    private static float density;

    public static void install(Activity owner) {
        owner.runOnUiThread(() -> {
            if (activity == owner) return;
            activity = owner;
            density = owner.getResources().getDisplayMetrics().density;
            slop = ViewConfiguration.get(owner).getScaledTouchSlop();
            hold = ViewConfiguration.getLongPressTimeout();
            Window window = owner.getWindow();
            Window.Callback original = window.getCallback();
            window.setCallback((Window.Callback) Proxy.newProxyInstance(
                Window.Callback.class.getClassLoader(), new Class<?>[]{Window.Callback.class},
                (proxy, method, args) -> {
                    if (method.getName().equals("dispatchTouchEvent")) {
                        record((MotionEvent) args[0]);
                    } else if (method.getName().equals("onWindowFocusChanged")) {
                        synchronized (lock) {
                            focused = (Boolean) args[0];
                            if (!focused) interrupted = true;
                        }
                    }
                    try {
                        return method.invoke(original, args);
                    } catch (InvocationTargetException error) {
                        throw error.getCause();
                    }
                }));
            View decor = window.getDecorView();
            decor.getViewTreeObserver().addOnGlobalLayoutListener(() -> updateInsets(decor));
            InputManager inputs = (InputManager) owner.getSystemService(Activity.INPUT_SERVICE);
            inputs.registerInputDeviceListener(new InputManager.InputDeviceListener() {
                public void onInputDeviceAdded(int id) {}
                public void onInputDeviceChanged(int id) {}
                public void onInputDeviceRemoved(int id) {
                    synchronized (lock) { interrupted = true; }
                }
            }, null);
            updateInsets(decor);
        });
    }

    private static void record(MotionEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_TOUCHSCREEN) != InputDevice.SOURCE_TOUCHSCREEN) return;
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_MOVE) return;
        synchronized (lock) {
            if (edges.length() > 256) {
                edges = new JSONArray();
                interrupted = true;
            }
            if (action == MotionEvent.ACTION_CANCEL) {
                for (int i = 0; i < event.getPointerCount(); i++) addEdge(event.getPointerId(i), "cancel");
            } else if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
                addEdge(event.getPointerId(event.getActionIndex()), "down");
            } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
                addEdge(event.getPointerId(event.getActionIndex()), "up");
            }
        }
    }

    private static void addEdge(int id, String action) {
        edges.put(new JSONArray().put(id).put(action));
    }

    private static void updateInsets(View decor) {
        synchronized (lock) {
            if (Build.VERSION.SDK_INT >= 30) {
                WindowInsets insets = decor.getRootWindowInsets();
                if (insets == null) return;
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                left = bars.left; top = bars.top; right = bars.right; bottom = bars.bottom;
                keyboardHeight = insets.isVisible(WindowInsets.Type.ime()) ? insets.getInsets(WindowInsets.Type.ime()).bottom : 0;
            } else {
                Rect visible = new Rect();
                decor.getWindowVisibleDisplayFrame(visible);
                int obscured = decor.getRootView().getHeight() - visible.bottom;
                keyboardHeight = obscured > 100 * density ? obscured : 0;
                top = visible.top;
            }
        }
    }

    public static String drain() {
        synchronized (lock) {
            JSONObject result = new JSONObject();
            try {
                result.put("edges", edges);
                result.put("interrupted", interrupted);
                result.put("focused", focused);
                result.put("keyboard_height", keyboardHeight);
                result.put("insets", new JSONArray().put(left).put(top).put(right).put(bottom));
                result.put("slop", slop);
                result.put("hold_ms", hold);
                result.put("density", density);
            } catch (org.json.JSONException error) {
                throw new IllegalStateException(error);
            }
            edges = new JSONArray();
            interrupted = false;
            return result.toString();
        }
    }

    public static void setKeyboardType(int flags) {
        Activity owner = activity;
        if (owner != null) owner.runOnUiThread(() -> PythonActivity.changeKeyboard(flags));
    }
}
