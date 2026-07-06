-- lua/plugins/grug-far.lua
return {
  "MagicDuck/grug-far.nvim",
  cmd = { "GrugFar" },
  keys = {
    {
      "<leader>sr",
      function()
        require("grug-far").open({ prefills = { paths = vim.fn.expand("%") } })
      end,
      desc = "Search and Replace (current file)",
    },
    {
      "<leader>sg",
      function()
        require("grug-far").open()
      end,
      desc = "Search and Replace (workspace)",
    },
  },
  opts = {
    headerInfoMuted = true,
  },
  config = function(_, opts)
    require("grug-far").setup(opts)
  end,
}
