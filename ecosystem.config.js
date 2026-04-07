module.exports = {
  apps: [
    {
      name: 'dental-api',
      cwd: '/root/dental-agent',
      script: 'venv/bin/python',
      args: '-m uvicorn dental.api.webhook:app --host 0.0.0.0 --port 8005',
      env: {
        // Copy from .env or set in environment
        // ANTHROPIC_API_KEY: 'your-key-here',
        // DATABASE_URL: 'postgresql://user:pass@localhost:5432/dental_agent',
        REDIS_URL: 'redis://localhost:6379/0',
        ASYNC_MODE: 'false',
        WHATSAPP_WEBHOOK_SECRET: 'dev_secret_changeme',
        VERIFY_SIGNATURES: 'false',
        BASE_URL: 'https://dental.softlogic.ee',
        ENVIRONMENT: 'development'
      }
    },
    {
      name: 'dental-dashboard',
      cwd: '/root/dental-agent/dashboard',
      script: 'npm',
      args: 'run start -- -p 3005'
    }
  ]
};
