<div align="center" markdown>

<p align="center">
    <a href="https://github.com/snoups/3xui-shop/blob/main/README.md"><u><b>ENGLISH</b></u></a> •
    <a href="https://github.com/snoups/3xui-shop/blob/main/README.ru_RU.md"><u><b>РУССКИЙ</b></u></a>
</p>

![3xui-shop](https://github.com/user-attachments/assets/282d10db-a355-4c65-a2cf-eb0e8ec8eed1)

**This project is a Telegram bot for selling VPN subscriptions. It works with 3X-UI.**

<p align="center">
    <a href="#overview">Overview</a> •
    <a href="#installation-guide">Installation guide</a> •
</p>

![GitHub License](https://img.shields.io/github/license/snoups/3xui-shop)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/snoups/3xui-shop/total)
![GitHub Release](https://img.shields.io/github/v/release/snoups/3xui-shop)
![GitHub Issues or Pull Requests](https://img.shields.io/github/issues/snoups/3xui-shop)


[![Static Badge](https://img.shields.io/badge/public_channel-white?style=social&logo=Telegram&logoColor=blue&logoSize=auto&labelColor=white&link=https%3A%2F%2Ft.me%2Fsn0ups)](https://t.me/sn0ups)
[![Static Badge](https://img.shields.io/badge/contact_me-white?style=social&logo=Telegram&logoColor=blue&logoSize=auto&labelColor=white&link=https%3A%2F%2Ft.me%2Fsnoups)](https://t.me/snoups)
![GitHub Repo stars](https://img.shields.io/github/stars/snoups/3xui-shop)
</div>

>[!WARNING]
>**This repository is no longer maintained.**  
**The bot has moved to a new panel and now has its own new [repository](https://github.com/snoups/remnashop/) with an improved architecture, expanded functionality, and better stability — all built thanks to Remnawave.**
>
>**[Check out the new project](https://github.com/snoups/remnashop/) — it’s faster, cleaner, and much more capable!**

<a id="overview"></a>

## 📝 Overview

**3X-UI-SHOP** is a comprehensive solution designed to automate the sale of VPN subscriptions through Telegram.
The bot uses the **3X-UI** panel API for client management and supports multiple payment methods, including
**Cryptomus**, **Heleket**, **YooKassa**, **YooMoney**, and **Telegram Stars**.

The bot enables efficient subscription sales with advanced features:

- **Server Manager**
    - Add, remove, disable, and check servers in the pool
    - Automatically distribute new clients across servers
    - Manage servers without restarting or reconfiguring the bot
    - ~~Replace a server with another one~~
- **Promocode System**
    - Create, edit, and delete promocodes
    - Promocodes for adding extra subscription time
    - ~~Promocodes with discounts~~
- **Notifications**
    - Send messages to a specific user or all users
    - Edit the last sent notification
    - Format text using HTML
    - Preview notifications before sending
    - System notifications for the developer and administrators
- **Two-Level Referral Program** (by [@Heimlet](https://github.com/Heimlet))
    - View referral statistics
    - Reward users for inviting new members
    - Support for two-tier referral rewards
- **Trial Period** (by [@Heimlet](https://github.com/Heimlet))
    - Provide free trial subscription
    - Extend trial period for referred users
    - Configure and disable the trial period
- **Flexible Payment System**
    - Change the default currency
    - Easily extendable architecture for adding new payment gateways
    - ~~Add, edit, and delete subscription plans at any time~~
    - ~~Change the display order of payment options~~
- **~~User Editor~~**
    - ~~View user information~~
    - ~~View referral statistics~~
    - ~~View payment history and activated promocodes~~
    - ~~View server information~~
    - ~~Edit user subscriptions~~
    - ~~Block or unblock users~~
    - ~~Quick access to a user via forwarded messages~~
    - ~~Personal discounts for users~~

### ⚙️ Admin Panel
The bot includes a user-friendly admin panel with tools for efficient management.
Administrators do not have access to server management.

- **`Server Manager`**: Add, remove, disable, and check servers in the pool
- **`Statistics`**: View usage analytics and performance data
- **`User Editor`**: Manage user accounts and subscriptions
- **`Promocode Editor`**: Create, edit, and delete promocodes
- **`Notification Sender`**: Send custom notifications to users
- **`Database Backup`**: Create and send database backups
- **`Maintenance Mode`**: Disable user access during updates or fixes


### 🚧 Current Tasks
- [x] Trial period
- [x] Referral system
- [ ] Statistics
- [ ] User editor
- [ ] Plans editor
- [ ] Flexible server pool
- [ ] Custom promocodes

<a id="installation-guide"></a>

## 🛠️ Installation guide
<a id="production-installer"></a>

### 🚀 Fresh VPS Production Installer

For a fresh Ubuntu 22.04/24.04/26.04 VPS, the repository includes a production bootstrap installer at `/install.sh`.

Because this repository is private, the server must first have GitHub CLI installed and authenticated to an account that can read this repository. GitHub recommends `gh auth login` for CLI authentication and fine-grained tokens can be limited to repository Contents: Read. 

Run the installer with:

```bash
GH_TOKEN="$(gh auth token)" sudo --preserve-env=GH_TOKEN bash -c 'curl -fsSL -H "Accept: application/vnd.github.raw+json" -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/aminahmadloo/ToonelVpn/contents/install.sh?ref=main" | bash'
```

The installer:

- validates Ubuntu version, architecture, ports, DNS and GitHub access before making changes;
- installs Docker Engine + Compose Plugin from Docker's official APT repository;
- installs and configures Nginx;
- obtains and installs Let's Encrypt TLS and runs a renewal dry-run;
- creates `.env` with mode `600`;
- asks for essential configuration first and optional payment/storage settings later;
- leaves optional gateways disabled when their credentials are skipped;
- creates `plans.json` from `plans.example.json` on a clean install;
- builds and starts the current ToonelVPN containers;
- performs a final container and HTTPS health check.

> **Important:** HTTP-01 validation requires inbound TCP port 80 to be reachable from the Internet. If the DNS record is not pointing to the new VPS yet, the installer stops before installation. 

For an installation from a specific Git ref:

```bash
TOONELVPN_REF=main GH_TOKEN="$(gh auth token)" sudo --preserve-env=GH_TOKEN bash -c 'curl -fsSL -H "Accept: application/vnd.github.raw+json" -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/aminahmadloo/ToonelVpn/contents/install.sh?ref=main" | bash'
```


### Dependencies

Before starting the installation, make sure you have the installed [**Docker**](https://www.docker.com/)

### Docker Installation

1. **Install & Upgrade:**
   ```bash
   bash <(curl -Ls https://raw.githubusercontent.com/snoups/3xui-shop/main/scripts/install.sh) -q
   cd 3xui-shop
   ```

2. **Set up environment variables and plans:**
- Copy `plans.example.json` to `plans.json` and `.env.example` to `.env`:
    ```bash
    cp plans.example.json plans.json
    cp .env.example .env
    ```
    > Update `plans.json` file with your subscription plans. [(Subscription Plans Configuration)](#subscription-plans-configuration) 

    > Update `.env` file with your configuration. [(Environment Variables Configuration)](#environment-variables-configuration)

3. **Build the Docker image:**
   ```bash
   docker compose build
   ```

4. **Run the Docker container:**
   ```bash
   docker compose up -d
   ```

### Environment Variables Configuration

| Variable | Required | Default | Description |
|-|-|-|-|
| LETSENCRYPT_EMAIL | 🔴 | - | Email for generating certificates |
| | | |
| BOT_TOKEN | 🔴 | - | Telegram bot token |
| BOT_ADMINS | ⭕ | - | List of admin IDs (e.g., 123456789,987654321) |
| BOT_DEV_ID | 🔴 | - | ID of the bot developer |
| BOT_SUPPORT_ID | 🔴 | - | ID of the support person |
| BOT_DOMAIN | 🔴 | - | Domain of the bot (e.g., 3xui-shop.com) |
| BOT_PORT | ⭕ | 8080 | Port of the bot |
| | | |
| SHOP_EMAIL | ⭕ | support@3xui-shop.com | Email for receipts |
| SHOP_CURRENCY | ⭕ | RUB | Currency for buttons (e.g., RUB, USD, XTR) |
| SHOP_TRIAL_ENABLED | ⭕ | True | Enable trial subscription for new users |
| SHOP_TRIAL_PERIOD | ⭕ | 3 | Duration of the trial subscription in days |
| SHOP_REFERRED_TRIAL_ENABLED | ⭕ | False | Enable extended trial period for referred users |
| SHOP_REFERRED_TRIAL_PERIOD | ⭕ | 7 | Duration of the extended trial for referred users (in days) |
| SHOP_REFERRER_REWARD_ENABLED | ⭕ | True | Enable the two-level referral reward system |
| SHOP_REFERRER_LEVEL_ONE_PERIOD | ⭕ | 10 | Reward in days for the first-level referrer (inviter) |
| SHOP_REFERRER_LEVEL_TWO_PERIOD | ⭕ | 3 | Reward in days for the second-level referrer (inviter of the inviter). |
| SHOP_BONUS_DEVICES_COUNT | ⭕ | 1 | Default Device Limit for Promocode, Trial, and Referral Users (Based on Plan Settings) |
| SHOP_PAYMENT_STARS_ENABLED | ⭕ | True | Enable Telegram stars payment |
| SHOP_PAYMENT_CRYPTOMUS_ENABLED | ⭕ | False | Enable Cryptomus payment |
| SHOP_PAYMENT_HELEKET_ENABLED | ⭕ | False | Enable Heleket payment |
| SHOP_PAYMENT_YOOKASSA_ENABLED | ⭕ | False | Enable Yookassa payment |
| SHOP_PAYMENT_YOOMONEY_ENABLED | ⭕ | False | Enable Yoomoney payment |
| | | |
| XUI_USERNAME | 🔴 | - | Username for authentication in the 3X-UI panel |
| XUI_PASSWORD | 🔴 | - | Password for authentication in the 3X-UI panel |
| XUI_TOKEN | ⭕ | - | Token for authentication (if configured in the panel) |
| XUI_SUBSCRIPTION_PORT | ⭕ | 2096 | Port for subscription |
| XUI_SUBSCRIPTION_PATH | ⭕ | /user/ | Path for subscription |
| | | |
| CRYPTOMUS_API_KEY | ⭕ | - | API key for Cryptomus payment |
| CRYPTOMUS_MERCHANT_ID | ⭕ | - | Merchant ID for Cryptomus payment |
| | | |
| HELEKET_API_KEY | ⭕ | - | API key for Heleket payment |
| HELEKET_MERCHANT_ID | ⭕ | - | Merchant ID for Heleket payment |
| | | |
| YOOKASSA_TOKEN | ⭕ | - | Token for YooKassa payment |
| YOOKASSA_SHOP_ID | ⭕ | - | Shop ID for YooKassa payment |
| | | |
| YOOMONEY_WALLET_ID | ⭕ | - | Wallet ID for Yoomoney payment |
| YOOMONEY_NOTIFICATION_SECRET | ⭕ | - | Notification secret key for Yoomoney payment |
| | | |
| LOG_LEVEL | ⭕ | DEBUG | Log level (e.g., INFO, DEBUG) |
| LOG_FORMAT | ⭕ | %(asctime)s \| %(name)s \| %(levelname)s \| %(message)s | Log format |
| LOG_ARCHIVE_FORMAT | ⭕ | zip | Log archive format (e.g., zip, gz) |


### Subscription Plans Configuration

```json
{
    "durations": [30, 60, 180, 365],  // Available subscription durations in days

    "plans": 
    [
        {
            "devices": 1,  // Number of devices supported by the plan
            "prices": {
                "RUB": {  // Prices for Russian rubles (RUB)
                    "30": 70,   // Price for 30 days
                    "60": 120,  // Price for 60 days
                    "180": 300, // Price for 180 days
                    "365": 600  // Price for 365 days
                },
                "USD": {  // Prices for US dollars (USD)
                    "30": 0.7,  // Price for 30 days
                    "60": 1.2,  // Price for 60 days
                    "180": 3,   // Price for 180 days
                    "365": 6    // Price for 365 days
                },
                "XTR": {  // Prices for Telegram stars (XTR)
                    "30": 60,   // Price for 30 days
                    "60": 100,  // Price for 60 days
                    "180": 250, // Price for 180 days
                    "365": 500  // Price for 365 days
                }
            }
        },
        {
            // Next plan
        }
    ]
}
```

### YooKassa Configuration

1. **Webhook Setup:**
    - Visit the [HTTP Notifications](https://yookassa.ru/my/merchant/integration/http-notifications) page.
    - Enter the bot’s domain in the notification URL, ending with `/yookassa` (e.g., `https://3xui-shop.com/yookassa`).
    - Select the following events:
        - `payment.succeeded`
        - `payment.waiting_for_capture`
        - `payment.canceled`

2. **Environment Variables Setup:**
    - Set the following environment variables:
        - `YOOKASSA_TOKEN`: Your secret key
        - `YOOKASSA_SHOP_ID`: Your shop ID

### YooMoney Configuration

1. **Webhook Setup:**
    - Visit the [HTTP Notifications](https://yoomoney.ru/transfer/myservices/http-notification) page.
    - Enter the bot’s domain in the notification URL, ending with `/yoomoney` (e.g., `https://3xui-shop.com/yoomoney`).
    - Copy the notification secret key.
    - Check the box for `sending HTTP-notifications`.
    - Save the changes.

2. **Environment Variables Setup:**
    - Set the following environment variables:
        - `YOOMONEY_WALLET_ID`: Your wallet ID
        - `YOOMONEY_NOTIFICATION_SECRET`: Your notification secret key

### 3X-UI Configuration

To ensure the bot functions correctly, you must configure the 3X-UI panel:

- [Set up SSL certificate.](https://github.com/MHSanaei/3x-ui?tab=readme-ov-file#ssl-certificate)
- Set up an Inbound **(the first one will be used)** for adding clients.
- Enable the subscription service with port `2096` and path `/user/`.
    > **Don’t forget to specify certificate for the subscription.**
- Disabling configuration encryption is recommended.

<a id="bugs-and-feature-requests"></a>

### Referral and Trial Rewards Configuration

Bot now supports **trial subscriptions** and a **two-level referral reward system**. Here’s how it works:
All configuration is available via `.env` [(see it above)](#environment-variables-configuration).

| Type of reward | How it works |
| - | - |
| Trial period | A trial subscription is available by 'TRY FOR FREE' button at start menu to any user who opens the bot and does not have an active subscription. |
| Extended Trial period | This option is just like previous 'trial period', but allows to configure **extended trial period** for an invited user. |
| Two-Level Referral Payment Rewards | When a referred user pays for a subscription, the referrer and the second-level referrer (the user who invited the referrer) receive fixed count of days at the moment fore each level. |