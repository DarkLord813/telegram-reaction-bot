# Telegram Reaction Bot 🤖

A powerful Telegram bot that sends permanent reactions to channel posts automatically.

## Features

- 🔥 **Permanent Reactions** - Reactions that never get removed
- 📢 **Channel Support** - Auto-reacts when added to channels
- ⭐ **Premium System** - Different limits for premium users
- 👑 **Admin Panel** - Full control for admins
- 🏥 **Health Checks** - Monitoring and keep-alive
- ☁️ **Deployment Ready** - Ready for Render deployment

## Deployment

### Render Deployment

1. Fork this repository
2. Create a new Web Service on Render
3. Connect your GitHub repository
4. Set environment variables:
   - `BOT_TOKEN`: Your Telegram bot token

5. Deploy!

### Environment Variables

- `BOT_TOKEN`: Your Telegram bot token from @BotFather
- `DATABASE_URL`: (Optional) For PostgreSQL database

## Admin Commands

- `/admin_stats` - View bot statistics
- `/admin_channels` - Manage channels
- `/admin_addpremium` - Add premium to users
- `/health` - Health check

## Required Channels

Users must join these channels to use the bot:
- [PSP GAMERS™](https://t.me/pspgamers5)
- [PSP GAMERS™ 2.0](https://t.me/pspgamers20)
