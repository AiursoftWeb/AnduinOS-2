// Test-only, read-only MessageTray observer. Loaded through Looking Glass,
// not installed as an extension and never included in the ISO.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const output = '/tmp/anduinos-live-notifications.json';
const started = GLib.get_monotonic_time();
const report = {complete: false, seconds: 0, notifications: [], error: null};
const connections = [];
const sources = new Set();
const notifications = new Set();

function save() {
    Gio.File.new_for_path(output).replace_contents(
        JSON.stringify(report), null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
}

function record(source, notification, phase) {
    if (notifications.has(notification))
        return;
    notifications.add(notification);
    report.notifications.push({
        phase,
        source: source.title ?? '',
        title: notification.title ?? '',
        body: notification.body ?? '',
        seconds: (GLib.get_monotonic_time() - started) / 1000000,
    });
    save();
}

function watch(source) {
    if (sources.has(source))
        return;
    sources.add(source);
    if (!Array.isArray(source.notifications))
        throw new Error('MessageTray source has no notification inventory');
    const connection = {object: source, ids: [], active: true};
    connections.push(connection);
    connection.ids.push(source.connect('destroy', () => {
        connection.active = false;
    }));
    connection.ids.push(source.connect('notification-added', (_source, notification) => {
        try {
            record(source, notification, 'new');
        } catch (error) {
            report.error = String(error);
            save();
        }
    }));
    for (const notification of source.notifications)
        record(source, notification, 'existing');
}

function disconnect() {
    for (const {object, ids, active} of connections) {
        if (!active)
            continue;
        try {
            for (const id of ids)
                object.disconnect(id);
        } catch (error) {
            report.error ??= String(error);
        }
    }
}

try {
    if (Main.sessionMode.isGreeter || Main.sessionMode.isLocked ||
        !Main.sessionMode.hasNotifications || typeof Main.messageTray?.getSources !== 'function')
        throw new Error('Live user MessageTray is not ready');
    connections.push({object: Main.messageTray, active: true, ids: [
        Main.messageTray.connect('source-added', (_tray, source) => {
            try {
                watch(source);
            } catch (error) {
                report.error = String(error);
                save();
            }
        }),
    ]});
    for (const source of Main.messageTray.getSources())
        watch(source);
    save();
    Main.lookingGlass.close();
    GLib.timeout_add(GLib.PRIORITY_DEFAULT, 10000, () => {
        report.seconds = (GLib.get_monotonic_time() - started) / 1000000;
        disconnect();
        report.complete = true;
        save();
        return GLib.SOURCE_REMOVE;
    });
} catch (error) {
    disconnect();
    report.error = String(error);
    save();
    Main.lookingGlass.close();
}
