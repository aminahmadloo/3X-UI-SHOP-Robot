# ToonelVPN System Admin Health Monitoring

هدف: ایجاد منوی مدیریت سیستم برای گزارش سلامت ربات، دیتابیس، Redis و Nodeها.

ماژول فعلی:
- گزارش uptime ربات
- نسخه Python و hostname
- ساختار آماده برای افزودن health check دیتابیس، Redis و Xray nodes

مراحل بعدی:
- اتصال به ServicesContainer
- تست DB/Redis
- گزارش وضعیت سرورها
- هشدار خودکار
