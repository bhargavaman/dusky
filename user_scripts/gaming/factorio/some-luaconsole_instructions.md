# Someone's LUA-Console — Installation Manual

**Mod**: some-luaconsole v2.1.1  
**What it does**: Opens an in-game Lua console (`Ctrl+]`) where you can run any Lua command. Achievements stay enabled.  
**Author**: someone1337  
**Source**: https://git.somenet.org/factorio/some-luaconsole.git

---

## Contents

- [Before You Start](#before-you-start)
- [What You Will Need](#what-you-will-need)
- [Step 1: Get the Mod Archive](#step-1-get-the-mod-archive)
- [Step 2: Open Your Mods Folder](#step-2-open-your-mods-folder)
- [Step 3: Extract the Mod](#step-3-extract-the-mod)
- [Step 4: Fix the Factorio Version](#step-4-fix-the-factorio-version)
- [Step 5: Enable the Mod](#step-5-enable-the-mod)
- [Step 6: Launch and Test](#step-6-launch-and-test)
- [Using the Console](#using-the-console)
- [Uninstalling](#uninstalling)
- [Problems?](#problems)
- [Why Achievements Stay Enabled](#why-achievements-stay-enabled)
- [How to Update Later](#how-to-update-later)
- [Quick Command List](#quick-command-list)

---

## Before You Start

### What is `~/.factorio/`?

When you see `~/.factorio/`, the `~` symbol means **your home folder** (on Linux this is usually `/home/your-username/`). So `~/.factorio/` is a hidden folder inside your home folder where Factorio stores your saves, mods, and settings.

If you ever need to find it manually: open your file browser, go to your home folder, press **Ctrl+H** to show hidden files, and look for `.factorio`.

### Do I need to use the terminal?

Yes, a few steps require typing commands into a terminal (also called "command line" or "console"). Don't worry — you can copy and paste each command exactly as written. On Linux you can open a terminal with **Ctrl+Alt+T**.

### Is this safe for my game?

Yes. The mod only adds a console window — it changes nothing about recipes, technologies, or gameplay. Your achievements stay on. If something goes wrong, you can simply delete the mod folder and everything is back to normal.

---

## What You Will Need

- **Factorio (jc141 portable version)** already installed and launched at least once.
- **A terminal** (Ctrl+Alt+T on most Linux systems).
- **A text editor** — you can use any of these:
  - **Gedit** (simple, graphical): search for "Text Editor" in your apps
  - **Nano** (terminal-based): already installed on most systems
  - **VS Code**, **Sublime Text**, or any other editor you like
- **The mod archive file** (`some-luaconsole-master.tar.gz`) — see Step 1.

---

## Step 1: Get the Mod Archive

The mod's website does not allow direct `git clone` downloads, so you need to download a snapshot file instead. Pick **one** of these methods:

### Method A — Download with your browser (easiest)

1. Open https://git.somenet.org/factorio/some-luaconsole.git in your web browser.
2. Near the top of the page, click the **"snapshot"** link.
3. Your browser will download a file called `some-luaconsole-master.tar.gz` (about 34 KB).
4. Move or note where this file was saved. You will need it in Step 3.

### Method B — Download with curl (if you like the terminal)

Open a terminal and run:

```bash
curl -sL -o some-luaconsole-master.tar.gz \
  "https://git.somenet.org/factorio/some-luaconsole.git/snapshot/master.tar.gz"
```

This saves the file in whatever folder your terminal is currently in.

> **What is curl?** It's a tool for downloading files from the internet. It comes pre-installed on most Linux systems. If you get "command not found", use Method A instead.

### Method C — Use the file from this folder

If a file called `some-luaconsole-master.tar.gz` was already provided next to this manual, you already have it. Skip to Step 2.

---

## Step 2: Open Your Mods Folder

First, check if your mods folder already exists:

```bash
ls ~/.factorio/mods/
```

If you see a list of files (like `mod-list.json`), the folder exists — move to Step 3.

If you get an error like "No such file or directory", you need to create it:

```bash
mkdir -p ~/.factorio/mods
```

Then create a basic `mod-list.json` file inside it:

```bash
echo '{"mods":[{"name":"base","enabled":true}]}' > ~/.factorio/mods/mod-list.json
```

> **What did that command do?** It created a small settings file that tells Factorio which mods are enabled. The file lists only the "base" game for now — you will add the console mod in Step 5.

---

## Step 3: Extract the Mod

Now you will unpack the downloaded archive into the correct folder.

**Make sure the archive file is in your current terminal folder.** If you downloaded it with your browser, the file is probably in `~/Downloads/`. First navigate there:

```bash
cd ~/Downloads
```

(If you saved it somewhere else, use that folder instead.)

Now run these commands one by one:

```bash
# 1. Create the mod's folder
mkdir -p ~/.factorio/mods/some-luaconsole_2.1.1

# 2. Extract the archive into it
tar xzf some-luaconsole-master.tar.gz \
  -C ~/.factorio/mods/some-luaconsole_2.1.1 \
  --strip-components=1
```

**Line 2 explained**: `tar xzf` unpacks a `.tar.gz` file. The `-C` says "put the files into this folder". The `--strip-components=1` removes the outer wrapper folder that comes inside the archive (its name contains a random-looking hash, so we strip it automatically).

**Check that it worked** — list the mod folder:

```bash
ls ~/.factorio/mods/some-luaconsole_2.1.1/
```

You should see several files and folders including `info.json`, `control.lua`, `data.lua`, and `locale`. If instead you see only **one folder** (something like `some-luaconsole-master-9d68ca4/`), the `--strip-components=1` didn't work. Fix it with:

```bash
cd ~/.factorio/mods/some-luaconsole_2.1.1
mv some-luaconsole-master-*/* .
rmdir some-luaconsole-master-*
```

> **What if `tar` is not found?** Try `tar --version`. If it says "command not found", you may need to install it: on Ubuntu/Debian run `sudo apt install tar`. Most systems already have it.

---

## Step 4: Fix the Factorio Version

**You only need to do this if you have Factorio 2.0.** If you have Factorio 2.1 or later, skip this step.

### 4a. Check your Factorio version

Open Factorio and look at the **bottom-left corner** of the title screen. You'll see a version number like `2.0.76` or `2.1.x`.

If you can run the terminal, you can also check with:

```bash
# Replace the path below with the actual path to your Factorio
/path/to/Factorio/factorio --version | head -1
```

### 4b. Open info.json for editing

```bash
nano ~/.factorio/mods/some-luaconsole_2.1.1/info.json
```

> **Don't know nano?** Press **Ctrl+X** to exit, then use a graphical editor instead:
> - Gedit: `gedit ~/.factorio/mods/some-luaconsole_2.1.1/info.json`
> - VS Code: `code ~/.factorio/mods/some-luaconsole_2.1.1/info.json`
> - Or open your file browser, navigate to `.factorio/mods/some-luaconsole_2.1.1/`, and double-click `info.json`.

### 4c. Change two lines

The file will look like this:

```json
{
    "name": "some-luaconsole",
    "version": "2.1.1",
    "title": "Someone's LUA-Console",
    "author": "someone1337",
    "homepage": "https://git.somenet.org/factorio/some-luaconsole.git",
    "description": "Run lua commands without losing achievements. ...",
    "factorio_version": "2.1",
    "dependencies": [
        "base>=2.1.0"
    ]
}
```

You need to change **two numbers**. Find these two lines and edit them:

| Old value | Change to |
|-----------|-----------|
| `"factorio_version": "2.1"` | `"factorio_version": "2.0"` |
| `"base>=2.1.0"` | `"base>=2.0.0"` |

When you're done, those two lines should look like this:

```json
    "factorio_version": "2.0",
    "dependencies": [
        "base>=2.0.0"
    ]
```

Save the file and close the editor.

> **Wait, I have a different Factorio version — what do I change to?**
>
> | Your Factorio | `factorio_version` | `base` dependency |
> |---|---|---|
> | 2.0.x | `"2.0"` | `"base>=2.0.0"` |
> | 2.1.x | No change needed | No change needed |
> | 1.1.x | `"1.1"` | `"base>=1.1.0"` |
>
> If your Factorio version is the same or newer than what the mod asks for, don't change anything.

> **Is this safe?** Yes. The mod uses basic Lua features that haven't changed since Factorio 1.1. The author set "2.1" because that's what they tested with — the code works fine on 2.0. If the game crashes after this change, just undo it (change the numbers back).

---

## Step 5: Enable the Mod

You need to tell Factorio to load this mod by editing `mod-list.json`.

### Step 5a: Back up the file first (just in case)

```bash
cp ~/.factorio/mods/mod-list.json ~/.factorio/mods/mod-list.json.bak
```

This creates a copy called `mod-list.json.bak`. If something goes wrong, you can delete the broken file and rename the backup.

### Step 5b: Open the file for editing

```bash
nano ~/.factorio/mods/mod-list.json
```

### Step 5c: Add the mod entry

The file contains a list of mods inside square brackets `[...]`. Add a comma after the last entry, then add a new entry for the console mod.

**If the file has only "base" in it**, make it look like this:

```json
{
  "mods": [
    {"name": "base", "enabled": true},
    {"name": "some-luaconsole", "enabled": true}
  ]
}
```

Notice:
- There is a **comma** after the `"base"` line.
- There is **no comma** after the last line (`some-luaconsole`).
- The last line does **not** have a comma.

**If the file has other mods already**, find the last mod entry, add a comma after it, then add `{"name": "some-luaconsole", "enabled": true}` before the closing `]`.

### Step 5d: Three common mistakes to avoid

1. **Trailing comma on the last entry** — do NOT put a comma after `some-luaconsole`. Factorio will silently ignore the whole file.
2. **Missing comma between entries** — every entry except the last must end with a comma.
3. **Typos in the name** — the `"name"` field must be exactly `"some-luaconsole"` (all lowercase, no spaces).

### Step 5e: Validate the file

Run this command to check that the file is valid:

```bash
python3 -m json.tool ~/.factorio/mods/mod-list.json
```

If it prints your file back in a neat, organized way, it's valid. If it prints an error message, there's a typo — open the file again and check the commas.

> **Don't have python3?** That's fine — you can skip this validation, just be extra careful with the commas.

---

## Step 6: Launch and Test

1. **Launch Factorio** normally.
2. On the main menu, click **Mods**. You should see "Someone's LUA-Console" in the list with a check mark next to it.
3. Click back to the main menu. Load any save (or start a new game).
4. Once inside the game, press and hold **Ctrl**, then press the **]** key (the right square bracket key). A console window should appear at the bottom of the screen.
5. Type this test command: `game.print("Hello from Lua!")`
6. Press **Ctrl+Enter** (hold Ctrl, press Enter) to run the command.
7. You should see "Hello from Lua!" printed in the chat area in the top-left.
8. Press **Ctrl+]** again to close the console.

> **IMPORTANT: Do NOT use the `/c` prefix.** The mod console (opened with Ctrl+]) expects **raw Lua code only**. Typing `/c game.print("hi")` will cause an error and may behave unexpectedly. The `/c` prefix is for Factorio's **built-in** console (opened with the tilde `~` key), which always disables achievements. The two consoles are separate.

**If the console doesn't appear**, go to **Settings → Controls**, scroll down to the "some-luaconsole" section, and check if the key bindings are set. If they show `---` (unbound), click on them and press the key combination you want to use.

**To confirm achievements are still enabled**: Open the save-load screen (from the menu or by pressing Escape in-game). If there is **no** trophy icon with a red slash next to your save, achievements are active.

---

## Using the Console

### Key shortcuts

| Shortcut | What it does |
|----------|-------------|
| Ctrl + ] | Open or close the console |
| Ctrl + Enter | Run the code you typed |
| Ctrl + Enter (empty box) | Re-run the last code you ran |

All of these can be changed in **Settings → Controls → some-luaconsole**.

### Things you can type

- `game.print("Hello!")` — prints a message on screen
- `game.players[1].insert{name="iron-plate", count=50}` — adds 50 iron plates to your inventory (single-player only)
- `game.surfaces[1].count_entities_filtered{name="stone-furnace"}` — counts how many stone furnaces exist on the map

### Things you cannot do

- Spawn items on multiplayer servers (you need admin rights)
- Access your computer's files through the console (restricted for safety)

### Tips

- The console **remembers what you typed** even after you close the game.
- If you get an error, the error message appears in the console — read it to see what went wrong.
- For multi-line scripts, press **Shift+Enter** to add a new line without running the code yet.

### WARNING: What disables achievements

The mod itself is safe, but **the commands you run through it can still disable achievements**. Here is the rule:

| Command type | Disables achievements? | Example |
|---|---|---|
| Reading info (printing, counting, inspecting) | **No** | `game.print("hi")`, counting entities |
| Spawning items in single-player | **No** | `game.players[1].insert{name="iron-plate"}` |
| Changing visuals (LUTs, colors) | **No** | (only affects how things look) |
| Changing game mechanics | **YES** | `game.player.surface.always_day=true` |
| Changing player stats or research | **YES** | Any tech unlock, god mode, etc. |
| Using Factorio's built-in `/c` console | **YES** | The tilde `~` key console always marks the save as cheated |

**`always_day=true` is a game mechanic change** — it stops the day/night cycle, which affects solar panel output. Factorio treats this the same as editing recipes or technologies: achievements off.

**To keep achievements:**
- Only run commands that **read** game state, not **change** it.
- Never use Factorio's built-in `/c` console (tilde key).
- If you need to test whether a command is safe, check the save-load screen for the trophy-with-slash icon before saving.

---

## Uninstalling

If you want to remove the mod later:

```bash
# Remove the mod files (this is permanent — be sure first)
rm -rf ~/.factorio/mods/some-luaconsole_2.1.1
```

Then edit `~/.factorio/mods/mod-list.json` and either:
- Change `"enabled": true` to `"enabled": false` (keeps the entry but turns it off), or
- Delete the line with `"some-luaconsole"` entirely.

> **What does `rm -rf` mean?** It's a permanent delete command. There is no trash bin or undo for this. Make sure you typed the path correctly before pressing Enter.

---

## Problems?

### Mod doesn't appear in the game's mod list

| Likely cause | How to fix |
|---|---|
| Wrong folder name | The folder must be named **exactly** `some-luaconsole_2.1.1` in `~/.factorio/mods/` |
| `info.json` is in a subfolder | It should be at `~/.factorio/mods/some-luaconsole_2.1.1/info.json` — if it's inside another folder, move it up (see Step 3) |
| `info.json` has a typo | Open it in a text editor and check that it's proper JSON (quotes, commas, braces all match) |
| `mod-list.json` has a typo | Open it and check commas (see Step 5d) |

### "Incompatible Factorio version"

You didn't change the version numbers in Step 4. Or you changed them wrong.

Check what's currently in the file:

```bash
cat ~/.factorio/mods/some-luaconsole_2.1.1/info.json
```

The `factorio_version` must match your Factorio version. If you have Factorio 2.0, it should say `"2.0"`.

### "Dependency ... is not satisfied"

Same problem — the `base` dependency needs to match your Factorio version. Fix both fields in `info.json` as shown in Step 4.

### Console doesn't open when I press Ctrl+]

1. Go to **Settings → Controls** in the game.
2. Scroll down to the "some-luaconsole" section (near the bottom).
3. If the key bindings show `---` (empty), click on "Open console" and press Ctrl+].
4. If another mod or program is using that shortcut, pick a different key combination.

### Game crashes when loading

The mod might be using a feature from Factorio 2.1 that doesn't exist in 2.0. Revert the changes you made in Step 4 (change `factorio_version` back to `"2.1"` and `base>=2.0.0` back to `"base>=2.1.0"`). Then either:

- Upgrade Factorio to version 2.1, or
- Look for an older version of the mod that works with 2.0.

You can check the crash log for details:

```bash
tail -50 ~/.factorio/factorio-current.log
```

### "Ctrl+]" opens my browser or another program

Some systems use Ctrl+] as a system shortcut. Either:

- Change the key binding in Factorio's controls menu, or
- Look in your system settings for keyboard shortcuts and disable the one that uses Ctrl+].

### The console opens but nothing happens when I type

Click inside the console's input box first to give it keyboard focus, then press Ctrl+Enter.

### I ran a command and now achievements are disabled!

If you ran something like `game.player.surface.always_day=true` or used Factorio's built-in `/c` console, achievements are off for that save. There is **no way to re-enable them** on an existing save — you must load a backup save from before the command, or start a new game.

**Common commands that disable achievements:**

| Command | Why it disables achievements |
|---|---|
| `game.player.surface.always_day=true` | Changes the day/night cycle (affects solar) |
| `/c anything` | Built-in console always marks save as cheated |
| `game.player.cheat_mode=true` | Enables god mode / cheating |
| `game.player.force.research_all_technologies()` | Unlocks all tech |

**Safe alternatives that do the same thing visually:**

Instead of `always_day=true` (which changes mechanics), use the **Bright Universe mod** (`afraid-of-the-dark`) which makes the world look like daytime by swapping color LUTs only — the day/night cycle still runs underneath, so achievements stay on.

---

## Why Achievements Stay Enabled

The mod itself does not disable achievements because:

1. Factorio only turns off achievements permanently when a mod changes **prototypes** during loading (recipes, items, technologies, entities, etc.).
2. This mod adds **no new prototypes** — its `data.lua` is empty, and `control.lua` only registers a console window.
3. The mod's description says: *"Run lua commands without losing achievements"* — meaning the **act of using the mod's console** does not flag your save as cheated. This is unlike Factorio's built-in `/c` console, which always marks the save as cheated regardless of what you type.
4. **However**, the specific Lua commands you run *through* the console can still disable achievements if they change game mechanics (see the warning above).

### How to tell if any mod is safe

Look at the mod's files:
- `data.lua`, `data-updates.lua`, `data-final-fixes.lua` — if these contain `data:extend(...)` or `data.raw.recipe[...] = ...`, the mod changes game content and **will** disable achievements.
- Mods that only add UI, console, or map features are usually safe.
- Commands you type at runtime that change mechanics (day cycle, player stats, etc.) disable achievements **per save**, not permanently.

---

## How to Update Later

When a new version of the mod comes out:

```bash
# 1. Delete the old mod folder
rm -rf ~/.factorio/mods/some-luaconsole_2.1.1

# 2. Download the new snapshot (see Step 1)

# 3. Extract it (see Step 3)
#    The version number in the folder name might be different now!
#    Check the new info.json and adjust the folder name.

# 4. Patch version if needed (see Step 4)

# 5. You do NOT need to edit mod-list.json again —
#    it already has the mod listed by name.
```

---

## Quick Command List

Copy and paste these one at a time in order.

```bash
# --- Install ---

# Create folder and extract
mkdir -p ~/.factorio/mods/some-luaconsole_2.1.1
tar xzf some-luaconsole-master.tar.gz \
  -C ~/.factorio/mods/some-luaconsole_2.1.1 \
  --strip-components=1

# Verify extraction
ls ~/.factorio/mods/some-luaconsole_2.1.1/
```

```bash
# --- Patch version for Factorio 2.0 ---
# Open info.json and change:
#   "factorio_version": "2.1"  ->  "2.0"
#   "base>=2.1.0"              ->  "base>=2.0.0"
nano ~/.factorio/mods/some-luaconsole_2.1.1/info.json
```

```bash
# --- Enable ---
# Open mod-list.json and add the entry
nano ~/.factorio/mods/mod-list.json
```

```bash
# --- Verify ---
ls ~/.factorio/mods/some-luaconsole_2.1.1/info.json
cat ~/.factorio/mods/mod-list.json
```

```bash
# --- Uninstall ---
rm -rf ~/.factorio/mods/some-luaconsole_2.1.1
# Then remove "some-luaconsole" from mod-list.json
```

```bash
# --- Debug ---
tail -50 ~/.factorio/factorio-current.log
python3 -m json.tool ~/.factorio/mods/mod-list.json
python3 -m json.tool ~/.factorio/mods/some-luaconsole_2.1.1/info.json
```
