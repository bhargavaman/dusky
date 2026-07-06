-- ================================================================================================
-- TITLE: NeoVim keymaps
-- ABOUT: sets some quality-of-life keymaps
-- ================================================================================================

-- Center screen when jumping
vim.keymap.set("n", "n", "nzzzv", { desc = "Next search result (centered)" })
vim.keymap.set("n", "N", "Nzzzv", { desc = "Previous search result (centered)" })
vim.keymap.set("n", "<C-d>", "<C-d>zz", { desc = "Half page down (centered)" })
vim.keymap.set("n", "<C-u>", "<C-u>zz", { desc = "Half page up (centered)" })

-- Spell Check "Wizard" Mode
-- Press <leader>z to jump to the next error and open the suggestion list instantly
vim.keymap.set("n", "<leader>z", "]sz=", { desc = "Next Spell Suggestion" })

-- Clear search highlights and dismiss notifications on Esc
vim.keymap.set("n", "<Esc>", function()
  vim.cmd("nohlsearch")
  pcall(function()
    require("notify").dismiss()
  end)
end, { desc = "Clear search highlight and notifications" })

-- Better window navigation
vim.keymap.set("n", "<C-h>", "<C-w>h", { desc = "Move to left window" })
vim.keymap.set("n", "<C-j>", "<C-w>j", { desc = "Move to bottom window" })
vim.keymap.set("n", "<C-k>", "<C-w>k", { desc = "Move to top window" })
vim.keymap.set("n", "<C-l>", "<C-w>l", { desc = "Move to right window" })

-- Splitting & Resizing
vim.keymap.set("n", "<leader>sv", "<Cmd>vsplit<CR>", { desc = "Split window vertically" })
vim.keymap.set("n", "<leader>sh", "<Cmd>split<CR>", { desc = "Split window horizontally" })
vim.keymap.set("n", "<C-Up>", "<Cmd>resize +2<CR>", { desc = "Increase window height" })
vim.keymap.set("n", "<C-Down>", "<Cmd>resize -2<CR>", { desc = "Decrease window height" })
vim.keymap.set("n", "<C-Left>", "<Cmd>vertical resize -2<CR>", { desc = "Decrease window width" })
vim.keymap.set("n", "<C-Right>", "<Cmd>vertical resize +2<CR>", { desc = "Increase window width" })

-- Better indenting in visual mode
vim.keymap.set("v", "<", "<gv", { desc = "Indent left and reselect" })
vim.keymap.set("v", ">", ">gv", { desc = "Indent right and reselect" })

-- Better J behavior
vim.keymap.set("n", "J", "mzJ`z", { desc = "Join lines and keep cursor position" })

-- Quick config editing
vim.keymap.set("n", "<leader>rc", "<Cmd>e ~/.config/nvim/init.lua<CR>", { desc = "Edit config" })

-- File Explorer
vim.keymap.set("n", "<leader>m", "<Cmd>NvimTreeFocus<CR>", { desc = "Focus on File Explorer" })
vim.keymap.set("n", "<leader>e", "<Cmd>NvimTreeToggle<CR>", { desc = "Toggle File Explorer" })

-- Buffer Management
vim.keymap.set("n", "<leader>fn", "<Cmd>enew<CR>", { desc = "New Empty Buffer" })
vim.keymap.set("n", "<leader>bd", "<Cmd>bdelete<CR>", { desc = "Delete/Close Buffer" })

-- Toggle Color Hightlighter
vim.keymap.set("n", "<leader>hc", "<cmd>HighlightColorsToggle<CR>", { desc = "Toggle highlight colors" })

-- Custom user command to push current file to dusky bare repo
vim.api.nvim_create_user_command("DuskyPush", function()
  local file = vim.api.nvim_buf_get_name(0)
  if file == "" then
    vim.notify("Error: No file associated with current buffer", vim.log.levels.ERROR)
    return
  end
  
  -- Resolve relative to HOME
  local home = os.getenv("HOME")
  local relative_file = vim.fn.fnamemodify(file, ":~:.") -- Relative to home (e.g. .config/nvim/init.lua)
  
  -- Check if file is within home
  if relative_file:sub(1, 1) == "/" or relative_file:sub(1, 2) == ".." then
    vim.notify("Error: File is outside home directory / working tree", vim.log.levels.ERROR)
    return
  end

  -- Check if file has any changes compared to the git repository
  local status_cmd = string.format("git --git-dir=%s/dusky --work-tree=%s status --porcelain %q", home, home, relative_file)
  local status_out = vim.fn.system(status_cmd):gsub("%s+", "") -- strip whitespaces
  if status_out == "" then
    vim.notify("No changes detected for " .. relative_file, vim.log.levels.INFO)
    return
  end

  -- Ask for commit message
  vim.ui.input({ prompt = "Commit message for " .. relative_file .. ": " }, function(msg)
    if not msg or msg == "" then
      vim.notify("Push aborted: empty commit message", vim.log.levels.WARN)
      return
    end

    -- Run commands in background and show output
    local cmd = string.format(
      "git --git-dir=%s/dusky --work-tree=%s add %q && git --git-dir=%s/dusky --work-tree=%s commit -m %q && git --git-dir=%s/dusky --work-tree=%s push",
      home, home, relative_file, home, home, msg .. " (" .. relative_file .. ")", home, home
    )
    
    vim.notify("Pushing " .. relative_file .. "...", vim.log.levels.INFO)
    
    local stderr_data = {}
    local stdout_data = {}
    
    -- Run asynchronously to prevent UI lockup
    vim.fn.jobstart(cmd, {
      stdout_buffered = true,
      stderr_buffered = true,
      on_stdout = function(_, data)
        for _, line in ipairs(data) do
          if line ~= "" then table.insert(stdout_data, line) end
        end
      end,
      on_stderr = function(_, data)
        for _, line in ipairs(data) do
          if line ~= "" then table.insert(stderr_data, line) end
        end
      end,
      on_exit = function(_, exit_code, _)
        if exit_code ~= 0 then
          local err_msg = table.concat(stderr_data, "\n")
          if err_msg == "" then
            err_msg = table.concat(stdout_data, "\n")
          end
          if err_msg == "" then
            err_msg = "Unknown error (exit code " .. exit_code .. ")"
          end
          vim.notify("Push failed:\n" .. err_msg, vim.log.levels.ERROR)
        else
          vim.notify("Successfully pushed " .. relative_file .. "!", vim.log.levels.INFO)
        end
      end
    })
  end)
end, {})

-- Bind to a keymap: <leader>gp for Git Push
vim.keymap.set("n", "<leader>gp", ":DuskyPush<CR>", { desc = "Push current file to dotfiles repo" })
