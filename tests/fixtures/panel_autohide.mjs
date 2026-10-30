// Read-only Shell observer. Input and preferences are controlled by the host test.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const output = Gio.File.new_for_path('/tmp/anduinos-panel-autohide.json');
const stop = Gio.File.new_for_path('/tmp/anduinos-panel-autohide.stop');
const report = {complete: false, error: null, sequence: 0, current: null, events: []};
const started = GLib.get_monotonic_time();
let previous = '';

function save() {
    output.replace_contents(JSON.stringify(report), null, false,
        Gio.FileCreateFlags.REPLACE_DESTINATION, null);
}

function sample() {
    const [x, y, modifiers] = global.get_pointer();
    const panels = global.dashToPanel?.panels ?? [];
    const panel = panels.length === 1 ? panels[0] : null;
    const actor = panel?.panelBox;
    const bounds = actor ? [...actor.get_transformed_position(), ...actor.get_transformed_size()] : [];
    const monitor = panel?.monitor;
    const ready = bounds.length === 4 && bounds.every(Number.isFinite) &&
        bounds[2] > 0 && bounds[3] > 0 && monitor?.width > 0 && monitor?.height > 0;
    const onscreen = ready && actor.visible && actor.mapped &&
        Math.min(bounds[0] + bounds[2], monitor.x + monitor.width) - Math.max(bounds[0], monitor.x) > 0.5 &&
        Math.min(bounds[1] + bounds[3], monitor.y + monitor.height) - Math.max(bounds[1], monitor.y) > 0.5;
    const current = {
        ready: !!ready,
        pointer: [x, y],
        leftDown: !!(modifiers & Clutter.ModifierType.BUTTON1_MASK),
        overview: Main.overview.visible,
        locked: Main.sessionMode.isLocked,
        bottom: panel?.geom?.position === St.Side.BOTTOM,
        fullscreen: !!monitor?.inFullscreen,
        monitor: monitor ? [monitor.x, monitor.y, monitor.width, monitor.height] : null,
        bounds,
        onscreen: !!onscreen,
        enabled: panel?.intellihide?.enabled === true,
    };
    report.sequence++;
    report.current = current;
    const signature = JSON.stringify(current);
    if (signature !== previous) {
        report.events.push({seconds: (GLib.get_monotonic_time() - started) / 1000000, ...current});
        previous = signature;
    }
    save();
}

try {
    Main.lookingGlass.close();
    GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
        try {
            sample();
            if (stop.query_exists(null)) {
                report.complete = true;
                save();
                return GLib.SOURCE_REMOVE;
            }
            if (GLib.get_monotonic_time() - started > 180000000)
                throw new Error('Panel auto-hide observation timed out');
        } catch (error) {
            report.error = String(error);
            save();
            return GLib.SOURCE_REMOVE;
        }
        return GLib.SOURCE_CONTINUE;
    });
} catch (error) {
    report.error = String(error);
    save();
}
