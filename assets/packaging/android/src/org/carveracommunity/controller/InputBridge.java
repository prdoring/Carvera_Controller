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
import android.view.ViewTreeObserver;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.util.HashMap;
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
    private static Window.Callback originalCallback;
    private static InputManager inputManager;
    private static InputManager.InputDeviceListener inputListener;
    private static View decorView;
    private static ViewTreeObserver.OnGlobalLayoutListener layoutListener;
    private static int keyboardHeight;
    private static int left, top, right, bottom;
    private static int slop;
    private static int hold;
    private static float density;
    private static final HashMap<Integer, float[]> starts = new HashMap<>();

    public static void install(Activity owner) {
        owner.runOnUiThread(() -> {
            if (activity == owner) return;
            detach();
            activity = owner;
            focused = owner.hasWindowFocus();
            density = owner.getResources().getDisplayMetrics().density;
            slop = ViewConfiguration.get(owner).getScaledTouchSlop();
            hold = ViewConfiguration.getLongPressTimeout();
            Window window = owner.getWindow();
            Window.Callback original = window.getCallback();
            originalCallback = original;
            window.setCallback((Window.Callback) Proxy.newProxyInstance(
                Window.Callback.class.getClassLoader(), new Class<?>[]{Window.Callback.class},
                (proxy, method, args) -> {
                    if (method.getName().equals("dispatchTouchEvent")) {
                        record((MotionEvent) args[0]);
                    } else if (method.getName().equals("onWindowFocusChanged")) {
                        synchronized (lock) {
                            focused = (Boolean) args[0];
                            if (!focused) { interrupted = true; starts.clear(); }
                        }
                    }
                    try {
                        return method.invoke(original, args);
                    } catch (InvocationTargetException error) {
                        throw error.getCause();
                    }
                }));
            View decor = window.getDecorView();
            decorView = decor;
            layoutListener = () -> updateInsets(decor);
            decor.getViewTreeObserver().addOnGlobalLayoutListener(layoutListener);
            InputManager inputs = (InputManager) owner.getSystemService(Activity.INPUT_SERVICE);
            inputManager = inputs;
            inputListener = new InputManager.InputDeviceListener() {
                public void onInputDeviceAdded(int id) {}
                public void onInputDeviceChanged(int id) {}
                public void onInputDeviceRemoved(int id) {
                    synchronized (lock) { interrupted = true; }
                }
            };
            inputs.registerInputDeviceListener(inputListener, null);
            updateInsets(decor);
        });
    }

    private static void detach() {
        if (activity != null && originalCallback != null) activity.getWindow().setCallback(originalCallback);
        if (decorView != null && layoutListener != null && decorView.getViewTreeObserver().isAlive()) {
            decorView.getViewTreeObserver().removeOnGlobalLayoutListener(layoutListener);
        }
        if (inputManager != null && inputListener != null) inputManager.unregisterInputDeviceListener(inputListener);
        activity = null;
        originalCallback = null;
        decorView = null;
        layoutListener = null;
        inputManager = null;
        inputListener = null;
        synchronized (lock) {
            starts.clear();
            edges = new JSONArray();
            interrupted = true;
        }
    }

    public static void uninstall() {
        Activity owner = activity;
        if (owner != null) owner.runOnUiThread(InputBridge::detach);
    }

    private static void record(MotionEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_TOUCHSCREEN) != InputDevice.SOURCE_TOUCHSCREEN) return;
        int action = event.getActionMasked();
        synchronized (lock) {
            for (int i = 0; i < event.getPointerCount(); i++) {
                float[] start = starts.get(event.getPointerId(i));
                if (start != null) start[2] = Math.max(start[2], (float) Math.hypot(event.getX(i) - start[0], event.getY(i) - start[1]));
            }
            if (action == MotionEvent.ACTION_MOVE) return;
            if (edges.length() > 256) {
                edges = new JSONArray();
                interrupted = true;
            }
            if (action == MotionEvent.ACTION_CANCEL) {
                for (int i = 0; i < event.getPointerCount(); i++) addEdge(event, i, "cancel");
            } else if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
                int i = event.getActionIndex();
                starts.put(event.getPointerId(i), new float[]{event.getX(i), event.getY(i), 0});
                addEdge(event, i, "down");
            } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
                addEdge(event, event.getActionIndex(), "up");
            }
        }
    }

    private static void addEdge(MotionEvent event, int index, String action) {
        int id = event.getPointerId(index);
        float[] start = starts.get(id);
        int width = Math.max(1, decorView.getWidth());
        int height = Math.max(1, decorView.getHeight());
        try {
            edges.put(new JSONArray().put(id).put(action).put(start == null ? 0 : (int) Math.ceil(start[2]))
                .put(event.getX(index) / width).put(1 - event.getY(index) / height).put(event.getEventTime()));
        } catch (org.json.JSONException error) {
            throw new IllegalStateException(error);
        }
        if (!action.equals("down")) starts.remove(id);
    }

    private static void updateInsets(View decor) {
        synchronized (lock) {
            if (Build.VERSION.SDK_INT >= 30) {
                WindowInsets insets = decor.getRootWindowInsets();
                if (insets == null) return;
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                left = bars.left; top = bars.top; right = bars.right; bottom = bars.bottom;
                keyboardHeight = insets.isVisible(WindowInsets.Type.ime()) ? insets.getInsets(WindowInsets.Type.ime()).bottom : 0;
                if (keyboardHeight != 0) bottom = 0;
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
