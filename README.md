# PUBG Scam Detector Bot

Python Telegram bot using Upstash Redis REST, ready for Railway.

## Railway Variables
- `BOT_TOKEN`: BotFather token (secret)
- `OWNER_IDS`: `8121013255`
- `UPSTASH_REDIS_REST_URL`: Upstash REST URL beginning with `https://`
- `UPSTASH_REDIS_REST_TOKEN`: freshly rotated Upstash token
- `SOURCE_CHANNEL`: `@Nsabin3`
- `GROUP_WARNING_COOLDOWN`: `60`
- `SEARCH_RESULTS_LIMIT`: `5`
- `LOG_LEVEL`: `INFO`

Do not put tokens in GitHub. Add them in Railway → Variables only.

## Setup
1. Add all project files to your GitHub repository.
2. In Railway, deploy from that GitHub repository.
3. Add the environment variables above.
4. Add the bot as an administrator in `@Nsabin3` so it can receive new channel posts.
5. For group monitoring, make the bot an admin in each group or disable Group Privacy through BotFather.
6. Start a private chat with the bot and send `/start`. Use `/admin` to open the restricted admin panel.

## Behavior and limits
- Starts recording new source-channel posts only after the bot is added as channel admin; it does not import historical posts.
- Search supports PUBG IDs, usernames, wallet numbers, and text from saved reports.
- No result means no matching report was found, not that a person is safe.
- A source-message button appears only when a public source message URL exists. Manual admin-added reports do not have that button.
- Automatic extraction depends on how the channel formats reports. Test with real examples and refine `extract_keys()` if needed.
- Owner IDs are configured by `OWNER_IDS`; only owners can add/remove extra admins.
