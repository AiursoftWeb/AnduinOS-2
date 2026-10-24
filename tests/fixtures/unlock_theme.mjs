// Test-only Shell observer: no theme, extension, authentication or actor changes.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const output = Gio.File.new_for_path('/tmp/anduinos-unlock-theme.json');
const stop = Gio.File.new_for_path('/tmp/anduinos-unlock-theme.stop');
const settings = new Gio.Settings({schema_id: 'org.gnome.shell.extensions.user-theme'});
const report = {complete: false, error: null, current: null, events: []};
const started = GLib.get_monotonic_time();
let previous = '';

function save() {
    output.replace_contents(JSON.stringify(report), null, false,
        Gio.FileCreateFlags.REPLACE_DESTINATION, null);
}

function sample() {
    const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
    const unlock = Main.extensionManager.lookup('unlock-theme@anduinos.com');
    const desktop = Main.extensionManager.lookup('user-theme@gnome-shell-extensions.gcampax.github.com');
    let passwordFocused = false;
    for (let actor = global.stage.get_key_focus(); actor; actor = actor.get_parent()) {
        if (actor.has_style_class_name?.('login-dialog-prompt-entry'))
            passwordFocused = true;
    }
    // GNOME's public extension state 1 is ENABLED (46), named ACTIVE in 50.
    const current = {
        pid: Number(GLib.file_read_link('/proc/self')),
        locked: Main.sessionMode.isLocked,
        greeter: Main.sessionMode.isGreeter,
        selected: settings.get_string('name'),
        application: theme.application_stylesheet?.get_path() ?? null,
        stylesheets: theme.get_custom_stylesheets().map(file => file.get_path() ?? file.get_uri()),
        unlockEnabled: unlock?.enabled === true,
        unlockActive: unlock?.state === 1,
        desktopActive: desktop?.state === 1,
        passwordFocused,
    };
    const signature = JSON.stringify(current);
    if (signature !== previous) {
        report.current = current;
        report.events.push({seconds: (GLib.get_monotonic_time() - started) / 1000000, ...current});
        previous = signature;
        save();
    }
}

try {
    sample();
    Main.lookingGlass.close();
    GLib.timeout_add(GLib.PRIORITY_DEFAULT, 200, () => {
        try {
            sample();
            if (stop.query_exists(null)) {
                report.complete = true;
                save();
                return GLib.SOURCE_REMOVE;
            }
            if (GLib.get_monotonic_time() - started > 300000000)
                throw new Error('Unlock theme observation timed out');
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
    Main.lookingGlass.close();
}
