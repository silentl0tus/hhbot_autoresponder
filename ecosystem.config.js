module.exports = {
  apps: [
    {
      name: "hh-autoresponder",
      script: "run_linux.sh",
      interpreter: "bash",
      cwd: __dirname,
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      restart_delay: 5000,
    },
  ],
};
