/* frameshot capture helper — GNOME Shell extension.
 *
 * Why this exists: on Wayland the compositor owns every pixel. No userspace
 * app — frameshot included — may read them except through the compositor's
 * consent path (XDG portal). This extension runs *inside* the compositor, so
 * it can capture exactly like GNOME's own screenshot facility does, with no
 * dialogs, and hand the pixels to frameshot's own overlay/editor.
 *
 * It exposes ONE method on the session bus:
 *   bus name: org.frameshot.Capture
 *   object:   /org/frameshot/Capture
 *   Screenshot() -> (b ok, s path_or_error)
 * On success, `path` is an absolute PNG path in $TMPDIR for frameshot to read
 * (and delete). No UI, no keybindings, no clipboard side effects.
 *
 * Capture mirrors js/ui/screenshot.js ScreenshotService._createStream +
 * ScreenshotAsync: Shell.Screenshot -> Gio stream -> close -> file path.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

Gio._promisify(Shell.Screenshot.prototype, 'screenshot');

const BUS_NAME = 'org.frameshot.Capture';
const OBJECT_PATH = '/org/frameshot/Capture';

const CaptureIface = `
<node>
  <interface name="org.frameshot.Capture">
    <method name="Screenshot">
      <arg type="b" direction="out" name="ok"/>
      <arg type="s" direction="out" name="path"/>
    </method>
  </interface>
</node>`;

class FrameCaptureService {
    constructor() {
        this._busy = false;
        const info = Gio.DBusNodeInfo.new_for_xml(CaptureIface).interfaces[0];
        this._dbus = Gio.DBusExportedObject.wrapJSObject(info, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._ownerId = Gio.DBus.session.own_name(
            BUS_NAME, Gio.BusNameOwnerFlags.REPLACE, null, null);
    }

    async _captureFullscreen() {
        const shooter = new Shell.Screenshot();
        // Same pattern as ScreenshotService._createStream (absolute branch).
        const path = GLib.build_filenamev([
            GLib.get_tmp_dir(),
            `frameshot-${Date.now()}-${Math.floor(Math.random() * 1e6)}.png`,
        ]);
        const file = Gio.File.new_for_path(path);
        const stream = file.replace(
            null, false, Gio.FileCreateFlags.NONE, null);
        try {
            await shooter.screenshot(true, stream);
        } finally {
            try {
                stream.close(null);
            } catch {
                // already closed — path below still tells frameshot the result
            }
        }
        return path;
    }

    async ScreenshotAsync(_params, invocation) {
        if (this._busy) {
            invocation.return_value(
                GLib.Variant.new('(bs)', [false, 'capture already in progress']));
            return;
        }
        this._busy = true;
        try {
            const path = await this._captureFullscreen();
            invocation.return_value(GLib.Variant.new('(bs)', [true, path]));
        } catch (e) {
            invocation.return_value(
                GLib.Variant.new('(bs)', [false, `${e?.message ?? e}`]));
        } finally {
            this._busy = false;
        }
    }

    destroy() {
        try {
            this._dbus.unexport();
        } catch {
            // already unexported during shell shutdown
        }
        try {
            Gio.DBus.session.unown_name(this._ownerId);
        } catch {
            // bus going away
        }
        this._dbus = null;
    }
}

export default class FrameCaptureExtension extends Extension {
    // NOTE: no super.enable()/super.disable() — the base Extension class
    // defines neither; enable/disable are subclass hooks the shell calls.
    enable() {
        this._service = new FrameCaptureService();
    }

    disable() {
        this._service?.destroy();
        this._service = null;
    }
}
