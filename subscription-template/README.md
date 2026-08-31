# ToonelVPN custom 3X-UI subscription page

قالب اختصاصی فارسی و RTL صفحه Subscription برای ToonelVPN.

## مسیر نصب روی سرور

```text
/etc/3x-ui/sub_templates/toonelvpn/
```

فایل اصلی 3X-UI:

```text
index.html
```

مسیر **Sub Theme Directory** در 3X-UI را روی مسیر بالا قرار دهید.

## لوگوی واقعی ToonelVPN

قالب از لوگوی واقعی به‌صورت inline Base64 استفاده می‌کند تا به سرویس فایل جداگانه، endpoint جدید یا URL عمومی تصویر نیاز نباشد.

لوگوی اصلی قبل از deploy باید در این مسیر باشد:

```text
/etc/3x-ui/sub_templates/toonelvpn/logo.png
```

اسکریپت `deploy.sh` قالب را از ریپو می‌خواند، لوگوی موجود روی سرور را داخل HTML قرار می‌دهد و خروجی نهایی را در `index.html` مسیر 3X-UI می‌نویسد.

## ویژگی‌های قالب

- طراحی کاملاً فارسی و RTL
- Responsive برای موبایل و دسکتاپ
- لوگوی واقعی ToonelVPN
- جلوگیری از نمایش تکراری emailهای اشتراک در سربرگ
- وضعیت فعال / نزدیک انقضا / منقضی / اتمام حجم
- نمایش حجم مصرف‌شده، باقی‌مانده و درصد مصرف به‌صورت گرافیکی
- نمایش تاریخ و زمان باقی‌مانده اشتراک
- شمارش کانفیگ‌ها
- کارت جداگانه برای هر کانفیگ
- استخراج و نمایش نام کانفیگ/این‌باند از remark لینک
- حذف suffix مربوط به email از نام این‌باند در نمایش
- نمایش Protocol / Transport / Security
- کپی لینک هر کانفیگ
- کپی Subscription اصلی، JSON و Clash در صورت فعال بودن
- افزودن مستقیم به V2Box، V2RayNG و Happ
- بخش اعلان و پشتیبانی در صورت تنظیم شدن در 3X-UI
- انیمیشن‌های ظریف و ظاهر مدرن
- بدون تغییر endpointهای Subscription، JSON یا Clash

## Deploy

بعد از قرار گرفتن `logo.png` در مسیر مقصد، از داخل همین پوشه اجرا کنید:

```bash
chmod +x deploy.sh
auto_backup="/etc/3x-ui/sub_templates/toonelvpn/index.html.bak-$(date +%Y%m%d-%H%M%S)"
[[ -f /etc/3x-ui/sub_templates/toonelvpn/index.html ]] && cp /etc/3x-ui/sub_templates/toonelvpn/index.html "$auto_backup"
./deploy.sh
```

سپس یک URL Subscription را با مرورگر باز کنید.

## نکته مهم

این قالب فقط HTML صفحه اطلاعات Subscription را سفارشی می‌کند و به endpointهای اصلی 3X-UI دست نمی‌زند. برای بازگشت به صفحه پیش‌فرض کافی است مقدار **Sub Theme Directory** را خالی کنید.

قالب از view-model رسمی custom subscription templates در 3X-UI استفاده می‌کند، از جمله `subUrl`، `subJsonUrl`، `subClashUrl`، `sId`، `enabled`، `used`، `remained`، `total`، `expire`، `links`، `emails`، `announce` و `subSupportUrl`.
