#!/bin/bash

# MatugenFox Native Host Setup Script
# Automatically detects all supported Firefox-based browsers and installs
# the native messaging host manifest into each. Designed for autonomous dotfile setup.

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HOST_PATH="$SCRIPT_DIR/matugenfox_host.py"
MANIFEST_NAME="matugenfox.json"

echo "🦊 MatugenFox Autonomous Setup"

# 1. Make host executable
echo "  > Ensuring host script is executable..."
chmod +x "$HOST_PATH"

# 2. Detect all supported browser environments
TARGETS=()

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Standard Firefox & Forks
    [ -d "$HOME/.mozilla" ] && TARGETS+=("$HOME/.mozilla/native-messaging-hosts")
    [ -d "$HOME/.librewolf" ] && TARGETS+=("$HOME/.librewolf/native-messaging-hosts")
    [ -d "$HOME/.waterfox" ] && TARGETS+=("$HOME/.waterfox/native-messaging-hosts")
    [ -d "$HOME/.floorp" ] && TARGETS+=("$HOME/.floorp/native-messaging-hosts")
    [ -d "$HOME/.zen" ] && TARGETS+=("$HOME/.zen/native-messaging-hosts")
    
    # Flatpak Environments
    [ -d "$HOME/.var/app/org.mozilla.firefox/.mozilla" ] && TARGETS+=("$HOME/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts")
    [ -d "$HOME/.var/app/io.gitlab.librewolf-community/.librewolf" ] && TARGETS+=("$HOME/.var/app/io.gitlab.librewolf-community/.librewolf/native-messaging-hosts")
    [ -d "$HOME/.var/app/io.github.zen_browser.zen/.zen" ] && TARGETS+=("$HOME/.var/app/io.github.zen_browser.zen/.zen/native-messaging-hosts")
    [ -d "$HOME/.var/app/app.zen_browser.zen/.zen" ] && TARGETS+=("$HOME/.var/app/app.zen_browser.zen/.zen/native-messaging-hosts")

elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS Environments
    [ -d "$HOME/Library/Application Support/Mozilla" ] && TARGETS+=("$HOME/Library/Application Support/Mozilla/NativeMessagingHosts")
    [ -d "$HOME/Library/Application Support/LibreWolf" ] && TARGETS+=("$HOME/Library/Application Support/LibreWolf/NativeMessagingHosts")
    [ -d "$HOME/Library/Application Support/ZenBrowser" ] && TARGETS+=("$HOME/Library/Application Support/ZenBrowser/NativeMessagingHosts")
else
    echo "❌ Unsupported OS for automated setup: $OSTYPE"
    exit 1
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
    echo "❌ No supported Firefox-based browser profiles detected."
    echo "   Ensure you have launched Firefox, Zen, or LibreWolf at least once before running this."
    exit 1
fi

# 3. Install manifest into each detected browser
INSTALLED=0
for TARGET_DIR in "${TARGETS[@]}"; do
    mkdir -p "$TARGET_DIR"
    cat <<EOF > "$TARGET_DIR/$MANIFEST_NAME"
{
  "name": "matugenfox",
  "description": "MatugenFox Native Messaging Host",
  "path": "$HOST_PATH",
  "type": "stdio",
  "allowed_extensions": [
    "matugenfox@ubaid.com"
  ]
}
EOF
    echo "  ✓ Linked to: $TARGET_DIR"
    INSTALLED=$((INSTALLED + 1))
done

# 4. Initialize default config.json if missing (using universal '~' paths)
if [ ! -f "$SCRIPT_DIR/config.json" ]; then
    echo "  > Initializing default config.json with universal paths..."
    cat <<EOF > "$SCRIPT_DIR/config.json"
{
  "smoothTransitions": true,
  "ecoMode": false,
  "showSyncIndicator": true,
  "colorsPath": "~/.config/matugen/generated/firefox_websites.css",
  "websitesDir": "~/.config/dusky_sites",
  "transitionMs": 300,
  "autoDisableDarkSites": false,
  "nakedMode": false,
  "paletteShortcut": "ctrl+alt+c",
  "presets": [],
  "blocklist": []
}
EOF
fi

echo ""
echo "✅ Setup Complete! Wired into $INSTALLED browser environment(s)."
echo "--------------------------------------------------"
echo "Because you are using ~ (tilde) in your paths, the extension"
echo "will automatically adapt to any user who clones these dotfiles."
echo "No manual path configuration is required in the extension popup."
echo "--------------------------------------------------"
