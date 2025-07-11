# Admin Setup Guide

This guide explains how to set up and configure administrators for the AIVA Detect System.

## Prerequisites

- A running instance of the AIVA Detect System
- Access to the server's environment variables
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)

## Configuration

### 1. Setting Up Admin Users

Admin users are configured through the `ADMIN_IDS` environment variable. This should be a comma-separated list of Telegram User IDs.

#### How to Find Your Telegram User ID

1. Start a chat with [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send any message to the bot
3. The bot will reply with your user ID

#### Setting Admin IDs

In your `.env` file or server environment variables, set:

```bash
ADMIN_IDS=123456789,987654321  # Replace with actual user IDs
```

### 2. Webhook Configuration (Production)

For production use, configure these environment variables:

```bash
# Required
BOT_TOKEN=your_telegram_bot_token
WEBHOOK_MODE=true
WEBHOOK_URL=https://your-domain.com/webhook
WEBHOOK_SECRET=your_secure_secret_string

# Optional (with defaults)
PORT=8080
LOG_LEVEL=INFO
```

### 3. First-Time Setup

1. **Add the bot to your group**
   - Make the bot an admin in your group
   - Grant it permissions to read messages and send messages

2. **Start a chat with the bot**
   - Each admin must start a private chat with the bot
   - This is required for the bot to be able to send notifications

3. **Verify Admin Access**
   - In your group, send the command `/status`
   - The bot should respond with status information
   - If you don't see a response, check the bot's logs for errors

## Troubleshooting

### Common Issues

1. **Bot doesn't respond to commands**
   - Verify the bot has been added as an admin in the group
   - Check that the bot has the necessary permissions
   - Ensure the bot is running and connected

2. **Admin notifications not working**
   - Make sure admin users have started a chat with the bot
   - Verify the `ADMIN_IDS` are correct and properly formatted
   - Check the logs for any error messages

3. **Webhook issues**
   - Ensure the webhook URL is accessible from the internet
   - Verify the `WEBHOOK_SECRET` matches in your configuration
   - Check that the port is open and not blocked by a firewall

## Security Considerations

- Keep your `BOT_TOKEN` and `WEBHOOK_SECRET` secure
- Only add trusted users as admins
- Regularly rotate your webhook secret in production
- Monitor the bot's logs for any suspicious activity

## Support

If you encounter any issues, please check the logs and refer to the [Troubleshooting](#troubleshooting) section. For additional help, please open an issue in the project repository.
