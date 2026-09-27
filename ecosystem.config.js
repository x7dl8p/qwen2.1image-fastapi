// PM2 process file. Use scripts/pm2.sh (it also makes the API come back after a reboot).
module.exports = {
  apps: [
    {
      name: "qwen-api",
      script: "scripts/start.sh",
      interpreter: "bash",
      cwd: __dirname,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 50,
      kill_timeout: 30000, // let the API shut ComfyUI down cleanly
      out_file: "logs/pm2-out.log",
      error_file: "logs/pm2-error.log",
      time: true,
    },
  ],
};
