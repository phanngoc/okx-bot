// pm2 process config for the OKX live trader.
//
// Usage:
//   pm2 start ecosystem.config.js
//   pm2 status
//   pm2 logs okx-bot
//   pm2 restart okx-bot
//   pm2 stop okx-bot        # graceful: sends SIGINT → STOP_NOW path
//   pm2 delete okx-bot      # remove from list
//
// Auto-start on Mac reboot:
//   pm2 startup             # prints sudo command to run
//   pm2 save                # snapshot current process list

module.exports = {
  apps: [{
    name:        'okx-bot',
    script:      'live_trader.py',
    interpreter: '/Users/ngocp/.pyenv/versions/3.12.4/bin/python',
    cwd:         '/Users/ngocp/goterm-workspace/okx-bot',

    // Crash recovery
    autorestart:        true,
    max_restarts:       10,        // stop trying after 10 crashes
    min_uptime:         '60s',     // consider a crash if exits < 60s
    restart_delay:      5000,      // wait 5s between restarts
    max_memory_restart: '500M',    // restart if memory bloat

    // Stop handling — give bot time for graceful shutdown
    kill_timeout: 35000,           // 35s to handle SIGINT before SIGKILL
                                   // (matches our 30s health-check interval)

    // Logs
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    error_file:      'data/pm2-error.log',
    out_file:        'data/pm2-out.log',
    merge_logs:      true,
    time:            true,

    // Env
    env: {
      PYTHONUNBUFFERED: '1',       // immediate stdout flush
    },
  }],
};
