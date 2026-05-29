#!/usr/bin/env bash
# Arch Linux (EFI + Btrfs root) | Dusky Minimalist Boot & LUKS Setup
# FORENSICALLY AUDITED (SYSTEMD-BOOT / PLYMOUTH API COMPLIANT)

set -Eeuo pipefail
export LC_ALL=C

# --- Configuration ---
readonly THEME_NAME="dusky"
readonly THEME_DIR="/usr/share/plymouth/themes/${THEME_NAME}"
readonly MKINITCPIO_CONF="/etc/mkinitcpio.conf.d/10-arch-btrfs-luks.conf"

# --- Helpers ---
fatal() { printf '\033[1;31m[FATAL]\033[0m %s\n' "$1" >&2; exit 1; }
info() { printf '\033[1;32m[INFO]\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$1" >&2; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fatal "Required command not found: $1"
}

# --- Pre-flight Checks ---
if (( EUID != 0 )); then
    fatal "Deployment halted: Root privileges are strictly required."
fi

info "Validating base dependencies..."
require_cmd pacman
require_cmd sed
require_cmd grep
require_cmd base64

# --- Execution ---
info "Ensuring Plymouth is installed..."
if ! pacman -Q plymouth >/dev/null 2>&1; then
    if ! pacman -S --needed --noconfirm plymouth; then
        fatal "The installation of 'plymouth' failed. Ensure it is in your pacstrap payload."
    fi
fi

require_cmd plymouth-set-default-theme

info "Deploying custom minimal theme: $THEME_NAME..."
mkdir -p "$THEME_DIR"

# Generate a 1x1 white pixel dynamically for the progress line (Zero external assets)
info "Generating mathematical pixel asset..."
echo "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/wcAAwAB/4O0lQAAAABJRU5ErkJggg==" | base64 -d > "${THEME_DIR}/pixel.png"

# Generate .plymouth configuration
cat << EOF > "${THEME_DIR}/${THEME_NAME}.plymouth"
[Plymouth Theme]
Name=Dusky Minimal
Description=Pure typographic LUKS prompt and splash.
ModuleName=script

[script]
ImageDir=${THEME_DIR}
ScriptFile=${THEME_DIR}/${THEME_NAME}.script
ConsoleLogBackgroundColor=0x000000
MonospaceFont=Cantarell 11
Font=Cantarell 11
EOF

# Generate .script file (The core visual logic)
cat << 'EOF' > "${THEME_DIR}/${THEME_NAME}.script"
# --- Background Setup ---
Window.SetBackgroundTopColor(0.0, 0.0, 0.0);
Window.SetBackgroundBottomColor(0.0, 0.0, 0.0);

pixel_image = Image("pixel.png");

# --- Logo & Animation Engine ---
logo_image = Image.Text("dusky", 1.0, 1.0, 1.0, 1.0, "Cantarell 36");
logo_sprite = Sprite(logo_image);
logo_sprite.SetX(Window.GetWidth() / 2 - logo_image.GetWidth() / 2);
logo_sprite.SetY(Window.GetHeight() / 2 - logo_image.GetHeight() / 2);

global.animation_time = 0.0;
global.password_dialog_active = 0;

fun refresh_callback () {
    # Animate opacity (breathing effect) only if not typing password
    if (global.password_dialog_active == 0) {
        global.animation_time += 0.025;
        # Sine wave mapped to opacity: 0.5 to 1.0
        opacity = 0.75 + (0.25 * Math.Sin(global.animation_time * 2.0));
        logo_sprite.SetOpacity(opacity);
    } else {
        logo_sprite.SetOpacity(1.0);
    }
}
Plymouth.SetRefreshFunction(refresh_callback);

# --- Minimal Progress Line (3 pixels tall) ---
progress_sprite = Sprite();
global.dialog_y = logo_sprite.GetY() + logo_image.GetHeight() + 45;
progress_sprite.SetPosition(0, global.dialog_y, 0);
progress_sprite.SetOpacity(0);

fun progress_callback (duration, progress) {
    # Hide progress line if password prompt is active
    if (global.password_dialog_active == 1) {
        progress_sprite.SetOpacity(0);
        return;
    }
    
    # Calculate width up to 30% of the screen width
    max_width = Window.GetWidth() * 0.3;
    bar_width = Math.Int(max_width * progress);
    if (bar_width < 1) bar_width = 1;
    
    # Scale the 1x1 pixel to exact width and 3px height
    scaled_bar = pixel_image.Scale(bar_width, 3);
    progress_sprite.SetImage(scaled_bar);
    progress_sprite.SetX(Window.GetWidth() / 2 - bar_width / 2);
    progress_sprite.SetOpacity(1);
}
Plymouth.SetBootProgressFunction(progress_callback);

# --- LUKS Password Prompt ---
prompt_sprite = Sprite();
prompt_sprite.SetPosition(Window.GetWidth() / 2, global.dialog_y, 10);
prompt_sprite.SetOpacity(0);

global.bullet_container = Sprite();
global.bullet_container.SetOpacity(0);

fun display_normal_callback () {
    global.password_dialog_active = 0;
    prompt_sprite.SetOpacity(0);
    global.bullet_container.SetOpacity(0);
}

fun display_password_callback (prompt_text, bullets) {
    global.password_dialog_active = 1;
    progress_sprite.SetOpacity(0);
    
    # Render prompt text
    prompt_image = Image.Text(prompt_text, 0.7, 0.7, 0.7, 1.0, "Cantarell 12");
    prompt_sprite.SetImage(prompt_image);
    prompt_sprite.SetX(Window.GetWidth() / 2 - prompt_image.GetWidth() / 2);
    prompt_sprite.SetOpacity(1);
    
    # Generate smooth, native text bullets instead of pixel scaling
    bullet_string = "";
    for (index = 0; index < bullets; index++) {
        bullet_string += "● ";
    }
    
    if (bullets > 0) {
        bullet_image = Image.Text(bullet_string, 1.0, 1.0, 1.0, 1.0, "Cantarell 14");
        global.bullet_container.SetImage(bullet_image);
        global.bullet_container.SetX(Window.GetWidth() / 2 - bullet_image.GetWidth() / 2);
        global.bullet_container.SetY(prompt_sprite.GetY() + prompt_image.GetHeight() + 10);
        global.bullet_container.SetOpacity(1);
    } else {
        global.bullet_container.SetOpacity(0);
    }
}
Plymouth.SetDisplayNormalFunction(display_normal_callback);
Plymouth.SetDisplayPasswordFunction(display_password_callback);

# --- Systemd Message Broadcasting (Retained at Bottom) ---
message_sprite = Sprite();
message_sprite.SetPosition(Window.GetWidth() / 2, Window.GetHeight() * 0.85, 10000);

fun display_message_callback (text) {
    # Render logs in a muted grey/white
    my_image = Image.Text(text, 0.6, 0.6, 0.6, 1.0, "Cantarell 10");
    message_sprite.SetImage(my_image);
    message_sprite.SetX(Window.GetWidth() / 2 - my_image.GetWidth() / 2);
    message_sprite.SetOpacity(1);
}

fun hide_message_callback (text) {
    message_sprite.SetOpacity(0);
}

Plymouth.SetMessageFunction(display_message_callback);
Plymouth.SetHideMessageFunction(hide_message_callback);
Plymouth.SetUpdateStatusFunction(display_message_callback);

fun quit_callback () { logo_sprite.SetOpacity(1); }
Plymouth.SetQuitFunction(quit_callback);
EOF

chmod 0644 "${THEME_DIR}"/*

info "Patching mkinitcpio drop-in config to inject plymouth hook..."
if [[ -f "$MKINITCPIO_CONF" ]]; then
    if ! grep -q "^[^#]*HOOKS=.*plymouth" "$MKINITCPIO_CONF"; then
        # Inject directly after systemd hook
        sed -i --follow-symlinks -E 's/^([^#]*HOOKS=\([^)]*systemd)([[:space:]]*)/\1 plymouth /' "$MKINITCPIO_CONF"
        info "Injected modern plymouth hook into $MKINITCPIO_CONF"
    else
        info "plymouth hook already present."
    fi
else
    # Fallback to standard config if the drop-in isn't found yet
    if grep -q "^[^#]*HOOKS=.*systemd" /etc/mkinitcpio.conf && ! grep -q "^[^#]*HOOKS=.*plymouth" /etc/mkinitcpio.conf; then
         sed -i -E 's/^([^#]*HOOKS=\([^)]*systemd)([[:space:]]*)/\1 plymouth /' /etc/mkinitcpio.conf
         info "Injected modern plymouth hook into /etc/mkinitcpio.conf"
    fi
fi

info "Setting default theme to ${THEME_NAME} and rebuilding initramfs..."
# The -R flag must happen AFTER the mkinitcpio hook is injected
plymouth-set-default-theme -R "$THEME_NAME"

info "Minimalist Dusky Plymouth deployment and initramfs generation successful."
